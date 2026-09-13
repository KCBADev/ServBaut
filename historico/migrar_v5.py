"""
Migración v5 — IVA, dueño obligatorio y membrete.

Tres cambios:

  1. IVA. La nota gana `subtotal_centavos` (la suma de sus partidas, que
     mantienen los triggers) y `tasa_iva`. `total_centavos` pasa a ser el
     total FINAL que paga el cliente: subtotal + IVA.
     Las 62 notas del histórico quedan con tasa 0, así que subtotal = total y
     el cuadre de $381,146.50 no se mueve.

  2. El dueño del vehículo vuelve a ser obligatorio. Se aclaró que un carro
     siempre llega con dueño: nunca se da de alta uno suelto.

  3. `taller` gana la línea de especialidades y la ruta del logo, que necesita
     el membrete de la orden de trabajo.

Es idempotente. Respalda antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar_v5.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Datos reales del membrete del taller.
MEMBRETE = {
    "nombre": "SERVICIO BAUTISTA",
    "subtitulo": "MECÁNICA AUTOMOTRIZ",
    "direccion": "Humboldt #547, Col. Centro Barranquitas, Guadalajara, Jalisco",
    "telefono": "(33) 36-14-65-63 | 33-39-54-86-35",
    "correo": "albama-67@hotmail.com",
    "especialidades": (
        "ALINEACIÓN · SUSPENSIÓN · BALANCEO · FRENOS · LLANTAS · "
        "AMORTIGUADORES · SOLDADURA · MICRO ALAMBRE · EJES · "
        "ENDEREZADO DE CHASIS"
    ),
}

# Los triggers pasan a mantener dos columnas: el subtotal que sale de las
# partidas y el total final que le suma el IVA. Se recalculan enteros en vez
# de sumar diferencias para que un error de redondeo no se acumule.
TRIGGERS = """
DROP TRIGGER IF EXISTS trg_partidas_insert;
DROP TRIGGER IF EXISTS trg_partidas_update;
DROP TRIGGER IF EXISTS trg_partidas_delete;
DROP TRIGGER IF EXISTS trg_notas_iva;

CREATE TRIGGER trg_partidas_insert
AFTER INSERT ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = NEW.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = NEW.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = NEW.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;

CREATE TRIGGER trg_partidas_delete
AFTER DELETE ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = OLD.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = OLD.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = OLD.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = OLD.id_nota;
END;

CREATE TRIGGER trg_partidas_update
AFTER UPDATE ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = OLD.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = OLD.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = OLD.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = OLD.id_nota;
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = NEW.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = NEW.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = NEW.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;

-- Cambiar la tasa también tiene que recalcular el total. SQLite no encadena
-- triggers por omisión, así que esta actualización sobre `notas` no se dispara
-- a sí misma.
CREATE TRIGGER trg_notas_iva
AFTER UPDATE OF tasa_iva ON notas
BEGIN
    UPDATE notas
       SET total_centavos = NEW.subtotal_centavos
                          + CAST(ROUND(NEW.subtotal_centavos * NEW.tasa_iva)
                                 AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;
"""


def log(mensaje: str = "") -> None:
    print(mensaje)


def columnas(conexion: sqlite3.Connection, tabla: str) -> dict:
    return {f["name"]: f for f in conexion.execute(f"PRAGMA table_info({tabla})")}


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v5 — IVA, dueño obligatorio y membrete")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        cols_notas = columnas(c, "notas")
        cols_veh = columnas(c, "vehiculos")
        cols_taller = columnas(c, "taller")

        falta_iva = "tasa_iva" not in cols_notas
        dueno_opcional = not bool(cols_veh["id_cliente"]["notnull"])
        falta_membrete = "especialidades" not in cols_taller

        antes = {
            t: c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            for t in ("clientes", "vehiculos", "notas", "partidas")
        }
        total_antes = c.execute(
            "SELECT COALESCE(SUM(total_centavos), 0) t FROM partidas"
        ).fetchone()["t"]

        sin_dueno = c.execute(
            "SELECT COUNT(*) n FROM vehiculos WHERE id_cliente IS NULL"
        ).fetchone()["n"]

    if not (falta_iva or dueno_opcional or falta_membrete):
        log("\nLa base ya está migrada. No hay nada que hacer.")
        return

    if dueno_opcional and sin_dueno:
        raise SystemExit(
            f"Hay {sin_dueno} vehículos sin dueño. Asígnales uno en la pantalla "
            f"de Vehículos antes de correr esta migración, o el cambio los "
            f"dejaría fuera."
        )

    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.respaldo-{marca}")
    shutil.copy2(db.RUTA_DB, destino)
    log(f"\n  Respaldo: {destino.name}")

    conexion = sqlite3.connect(db.RUTA_DB, timeout=30.0)
    conexion.row_factory = sqlite3.Row
    try:
        # `partidas` tiene borrado en cascada hacia `notas`: reconstruir con las
        # llaves activas arrastraría los renglones.
        conexion.execute("PRAGMA foreign_keys = OFF")

        if falta_iva:
            conexion.execute(
                "ALTER TABLE notas ADD COLUMN subtotal_centavos INTEGER "
                "NOT NULL DEFAULT 0")
            conexion.execute(
                "ALTER TABLE notas ADD COLUMN tasa_iva REAL NOT NULL DEFAULT 0")
            # El histórico no llevaba impuesto: su total ya es el subtotal.
            conexion.execute(
                "UPDATE notas SET subtotal_centavos = total_centavos")
            conexion.commit()
            log("  notas: columnas `subtotal_centavos` y `tasa_iva`")

        conexion.executescript(TRIGGERS)
        log("  triggers reescritos para mantener subtotal y total")

        if falta_membrete:
            conexion.execute("ALTER TABLE taller ADD COLUMN especialidades TEXT")
            conexion.execute("ALTER TABLE taller ADD COLUMN logo TEXT")
            conexion.execute(
                """
                UPDATE taller
                   SET nombre = ?, subtitulo = ?, direccion = ?, telefono = ?,
                       correo = ?, especialidades = ?,
                       actualizado_en = datetime('now')
                 WHERE id = 1
                """,
                (MEMBRETE["nombre"], MEMBRETE["subtitulo"], MEMBRETE["direccion"],
                 MEMBRETE["telefono"], MEMBRETE["correo"],
                 MEMBRETE["especialidades"]),
            )
            conexion.commit()
            log("  taller: membrete real capturado")

        if dueno_opcional:
            conexion.executescript(
                """
                CREATE TABLE vehiculos_nueva (
                    id_vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
                    -- Obligatorio: un carro siempre llega con dueño.
                    id_cliente  INTEGER NOT NULL REFERENCES clientes(id_cliente),
                    marca       TEXT NOT NULL REFERENCES marcas(nombre),
                    modelo      TEXT,
                    anio        INTEGER,
                    color       TEXT,
                    placas      TEXT,
                    vin         TEXT,
                    observaciones TEXT,
                    activo      INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
                    creado_en   TEXT NOT NULL DEFAULT (datetime('now')),
                    CHECK (anio IS NULL OR anio BETWEEN 1900 AND 2100)
                );

                INSERT INTO vehiculos_nueva
                SELECT id_vehiculo, id_cliente, marca, modelo, anio, color,
                       placas, vin, observaciones, activo, creado_en
                  FROM vehiculos;

                DROP TABLE vehiculos;
                ALTER TABLE vehiculos_nueva RENAME TO vehiculos;

                CREATE INDEX IF NOT EXISTS idx_vehiculos_cliente
                    ON vehiculos(id_cliente);
                CREATE INDEX IF NOT EXISTS idx_vehiculos_placas
                    ON vehiculos(placas);
                """
            )
            log("  vehiculos: el dueño vuelve a ser obligatorio")

        conexion.commit()
        violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise SystemExit(
                f"{len(violaciones)} violaciones de llave foránea. "
                f"Restaura {destino.name}.")
        conexion.execute("PRAGMA foreign_keys = ON")
    finally:
        conexion.close()

    log("\n--- Validación ---")
    ok = True
    with db.conectar() as c:
        for tabla, cuantas in antes.items():
            ahora = c.execute(f"SELECT COUNT(*) n FROM {tabla}").fetchone()["n"]
            igual = ahora == cuantas
            ok &= igual
            log(f"  {'[OK]' if igual else '[!!]'} {tabla}: {cuantas} → {ahora}")

        total = c.execute(
            "SELECT COALESCE(SUM(total_centavos), 0) t FROM partidas"
        ).fetchone()["t"]
        igual = total == total_antes
        ok &= igual
        log(f"  {'[OK]' if igual else '[!!]'} Importe de partidas: "
            f"{db.formato_pesos(total_antes)} → {db.formato_pesos(total)}")

        # Lo que de verdad importa: el subtotal de cada nota tiene que seguir
        # siendo la suma de sus renglones.
        descuadradas = c.execute(
            """
            SELECT n.id_nota
              FROM notas n
              LEFT JOIN partidas p ON p.id_nota = n.id_nota
             GROUP BY n.id_nota, n.subtotal_centavos
            HAVING n.subtotal_centavos <> COALESCE(SUM(p.total_centavos), 0)
            """
        ).fetchall()
        ok &= not descuadradas
        log(f"  {'[OK]' if not descuadradas else '[!!]'} "
            f"Subtotales contra partidas: "
            f"{'todas cuadran' if not descuadradas else f'{len(descuadradas)} mal'}")

        sin_iva = c.execute(
            "SELECT COUNT(*) n FROM notas WHERE tasa_iva = 0"
        ).fetchone()["n"]
        total_notas = c.execute(
            "SELECT COALESCE(SUM(total_centavos), 0) t FROM notas"
        ).fetchone()["t"]
        log(f"  [i]  Notas sin IVA: {sin_iva} de {antes['notas']}")
        log(f"  {'[OK]' if total_notas == total_antes else '[!!]'} "
            f"Total de notas: {db.formato_pesos(total_notas)}")
        ok &= total_notas == total_antes

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
