"""
Migración v3 — Auto Servicio Bautista.

Dos cambios:

  1. El dueño del vehículo pasa a ser OPCIONAL. Un carro puede existir en el
     padrón sin estar amarrado a un cliente. La relación cliente–vehículo de
     cada servicio la sigue guardando la nota, que lleva ambos, así que el
     historial no pierde nada: al consultar un servicio se sabe quién lo trajo,
     y al consultar el padrón de vehículos no se obliga a nadie a tener dueño.

  2. `partidas` gana la columna `notas`, que existía en el Excel original
     (la columna «Notas» de la hoja TSA) y nunca se migró.

Es idempotente. Respalda antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar_v3.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def log(mensaje: str = "") -> None:
    print(mensaje)


def columnas(conexion: sqlite3.Connection, tabla: str) -> dict:
    return {f["name"]: f for f in conexion.execute(f"PRAGMA table_info({tabla})")}


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v3 — dueño opcional y notas de partida")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        cols_veh = columnas(c, "vehiculos")
        cols_par = columnas(c, "partidas")
        dueno_obligatorio = bool(cols_veh["id_cliente"]["notnull"])
        falta_notas = "notas" not in cols_par
        antes = {
            t: c.execute(f"SELECT COUNT(*) n FROM {t}").fetchone()["n"]
            for t in ("vehiculos", "notas", "partidas")
        }
        total_antes = c.execute(
            "SELECT COALESCE(SUM(total_centavos),0) t FROM partidas"
        ).fetchone()["t"]

    if not dueno_obligatorio and not falta_notas:
        log("\nLa base ya está migrada. No hay nada que hacer.")
        return

    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.respaldo-{marca}")
    shutil.copy2(db.RUTA_DB, destino)
    log(f"\n  Respaldo: {destino.name}")

    conexion = sqlite3.connect(db.RUTA_DB, timeout=30.0)
    conexion.row_factory = sqlite3.Row
    try:
        # `notas` referencia a `vehiculos`; reconstruir la tabla con las llaves
        # activas dejaría las referencias apuntando al vacío a media operación.
        conexion.execute("PRAGMA foreign_keys = OFF")

        # Sin BEGIN explícito a propósito: `executescript` de sqlite3 hace un
        # COMMIT implícito antes de correr, así que una transacción abierta a
        # mano se cierra sola y el COMMIT posterior falla. Se deja que cada
        # script se confirme y se revisa la integridad al final.
        if falta_notas:
            conexion.execute("ALTER TABLE partidas ADD COLUMN notas TEXT")
            log("  partidas: columna `notas` agregada")

        if dueno_obligatorio:
            conexion.executescript(
                """
                CREATE TABLE vehiculos_nueva (
                    id_vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
                    -- Ahora opcional: el padrón de vehículos vive por su cuenta.
                    id_cliente  INTEGER REFERENCES clientes(id_cliente),
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
            log("  vehiculos: el dueño ahora es opcional")

        conexion.commit()
        violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise SystemExit(
                f"{len(violaciones)} violaciones de llave foránea. "
                f"La base quedó a medias: restaura {destino.name}.")
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
            "SELECT COALESCE(SUM(total_centavos),0) t FROM partidas"
        ).fetchone()["t"]
        igual = total == total_antes
        ok &= igual
        log(f"  {'[OK]' if igual else '[!!]'} Importe: "
            f"{db.formato_pesos(total_antes)} → {db.formato_pesos(total)}")

        sin_dueno = c.execute(
            "SELECT COUNT(*) n FROM vehiculos WHERE id_cliente IS NULL"
        ).fetchone()["n"]
        log(f"  [i]  Vehículos sin dueño registrado: {sin_dueno}")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
