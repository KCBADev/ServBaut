"""
Migración del esquema — Auto Servicio Bautista.

Actualiza una base existente al esquema nuevo:

  * Saca los datos del vehículo de `notas` y los mueve a la tabla `vehiculos`,
    agrupando por cliente + marca + modelo. Así el mismo carro que hoy aparece
    repetido en varias notas queda como una sola ficha con su historial.
  * Añade a `notas` el estado del trabajo y lo pagado.
  * Crea la tabla `taller` con los datos que necesita la nota impresa.

Es idempotente: si la base ya está migrada, no hace nada.
Hace un respaldo antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Las notas del histórico ya se entregaron y se cobraron.
ESTADO_HISTORICO = "Entregado"


def log(mensaje: str = "") -> None:
    print(mensaje)


def columnas(conexion: sqlite3.Connection, tabla: str) -> set[str]:
    return {f["name"] for f in conexion.execute(f"PRAGMA table_info({tabla})")}


def hace_falta(conexion: sqlite3.Connection) -> bool:
    """La base vieja tiene `marca` dentro de notas; la nueva no."""
    return "marca" in columnas(conexion, "notas")


def respaldar() -> None:
    marca_tiempo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.respaldo-{marca_tiempo}")
    shutil.copy2(db.RUTA_DB, destino)
    log(f"  Respaldo: {destino.name}")


def derivar_vehiculos(conexion: sqlite3.Connection) -> tuple[dict, list[str]]:
    """
    Agrupa las notas en vehículos y devuelve (mapa de nota->vehículo, avisos).

    Se agrupa por cliente + marca + modelo, SIN incluir el año: si el mismo
    carro tiene años distintos entre notas es un error de captura, y meter el
    año en la llave partiría el carro en dos fichas en vez de destapar el
    problema. Se toma el año más frecuente y se avisa del conflicto.
    """
    filas = conexion.execute(
        """
        SELECT id_nota, id_cliente, marca, modelo, anio, color, fecha
          FROM notas
         ORDER BY fecha, id_nota
        """
    ).fetchall()

    grupos: dict[tuple, list[sqlite3.Row]] = {}
    for fila in filas:
        clave = (fila["id_cliente"], fila["marca"], (fila["modelo"] or "").strip())
        grupos.setdefault(clave, []).append(fila)

    mapa_notas: dict[str, int] = {}
    avisos: list[str] = []

    for (id_cliente, marca, modelo), notas in grupos.items():
        anios = [n["anio"] for n in notas if n["anio"] is not None]
        colores = [n["color"] for n in notas if n["color"]]

        anio = Counter(anios).most_common(1)[0][0] if anios else None
        color = Counter(colores).most_common(1)[0][0] if colores else None

        if len(set(anios)) > 1:
            detalle = ", ".join(
                f"{n['id_nota']}={n['anio']}" for n in notas if n["anio"] is not None
            )
            avisos.append(
                f"{marca} {modelo or '?'} del cliente #{id_cliente}: "
                f"años distintos entre notas ({detalle}). "
                f"Se toma {anio}; revísalo en la pantalla de Vehículos."
            )
        if len(set(colores)) > 1:
            avisos.append(
                f"{marca} {modelo or '?'} del cliente #{id_cliente}: "
                f"colores distintos ({', '.join(sorted(set(colores)))}). "
                f"Se toma {color}."
            )

        cursor = conexion.execute(
            """
            INSERT INTO vehiculos (id_cliente, marca, modelo, anio, color)
            VALUES (?, ?, ?, ?, ?)
            """,
            (id_cliente, marca, modelo or None, anio, color),
        )
        id_vehiculo = int(cursor.lastrowid)
        for nota in notas:
            mapa_notas[nota["id_nota"]] = id_vehiculo

    return mapa_notas, avisos


def reconstruir_notas(conexion: sqlite3.Connection, mapa: dict) -> None:
    """
    Rehace `notas` con la forma nueva.

    SQLite no permite quitar columnas con restricciones asociadas de forma
    limpia, así que se sigue el procedimiento oficial: crear la tabla nueva,
    copiar, borrar la vieja y renombrar.
    """
    conexion.executescript(
        """
        DROP TRIGGER IF EXISTS trg_partidas_insert;
        DROP TRIGGER IF EXISTS trg_partidas_update;
        DROP TRIGGER IF EXISTS trg_partidas_delete;

        CREATE TABLE notas_nueva (
            id_nota    TEXT PRIMARY KEY,
            id_cliente INTEGER NOT NULL REFERENCES clientes(id_cliente),
            id_vehiculo INTEGER REFERENCES vehiculos(id_vehiculo),
            fecha      TEXT NOT NULL,
            estado     TEXT NOT NULL DEFAULT 'Recibido'
                       CHECK (estado IN ('Recibido', 'En proceso',
                                         'Esperando refacción', 'Terminado',
                                         'Entregado')),
            total_centavos INTEGER NOT NULL DEFAULT 0
                       CHECK (total_centavos >= 0),
            pagado_centavos INTEGER NOT NULL DEFAULT 0
                       CHECK (pagado_centavos >= 0),
            creado_en  TEXT NOT NULL DEFAULT (datetime('now')),
            CHECK (id_nota GLOB 'N-[0-9][0-9][0-9]*'),
            CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
        );
        """
    )

    for fila in conexion.execute(
        "SELECT id_nota, id_cliente, fecha, total_centavos, creado_en FROM notas"
    ).fetchall():
        conexion.execute(
            """
            INSERT INTO notas_nueva (id_nota, id_cliente, id_vehiculo, fecha,
                                     estado, total_centavos, pagado_centavos,
                                     creado_en)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (fila["id_nota"], fila["id_cliente"], mapa.get(fila["id_nota"]),
             fila["fecha"], ESTADO_HISTORICO, fila["total_centavos"],
             # El histórico ya se cobró: se da por pagado por completo.
             fila["total_centavos"], fila["creado_en"]),
        )

    conexion.executescript(
        """
        DROP TABLE notas;
        ALTER TABLE notas_nueva RENAME TO notas;

        CREATE INDEX IF NOT EXISTS idx_notas_cliente  ON notas(id_cliente);
        CREATE INDEX IF NOT EXISTS idx_notas_vehiculo ON notas(id_vehiculo);
        CREATE INDEX IF NOT EXISTS idx_notas_fecha    ON notas(fecha);
        CREATE INDEX IF NOT EXISTS idx_notas_estado   ON notas(estado);

        CREATE TRIGGER trg_partidas_insert
        AFTER INSERT ON partidas
        BEGIN
            UPDATE notas
               SET total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                       FROM partidas WHERE id_nota = NEW.id_nota)
             WHERE id_nota = NEW.id_nota;
        END;

        CREATE TRIGGER trg_partidas_delete
        AFTER DELETE ON partidas
        BEGIN
            UPDATE notas
               SET total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                       FROM partidas WHERE id_nota = OLD.id_nota)
             WHERE id_nota = OLD.id_nota;
        END;

        CREATE TRIGGER trg_partidas_update
        AFTER UPDATE ON partidas
        BEGIN
            UPDATE notas
               SET total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                       FROM partidas WHERE id_nota = OLD.id_nota)
             WHERE id_nota = OLD.id_nota;
            UPDATE notas
               SET total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                       FROM partidas WHERE id_nota = NEW.id_nota)
             WHERE id_nota = NEW.id_nota;
        END;
        """
    )


def sembrar_taller(conexion: sqlite3.Connection) -> None:
    conexion.execute(
        """
        INSERT INTO taller (id, nombre, subtitulo, pie_nota, actualizado_en)
        VALUES (1, 'Auto Servicio Bautista', 'Nota de servicio',
                'Gracias por su preferencia.', datetime('now'))
        ON CONFLICT (id) DO NOTHING
        """
    )


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN DEL ESQUEMA")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as conexion:
        if not hace_falta(conexion):
            log("\nLa base ya está migrada. No hay nada que hacer.")
            db.inicializar_esquema()  # por si faltan tablas nuevas
            return
        antes_notas = conexion.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM notas"
        ).fetchone()
        antes_partidas = conexion.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM partidas"
        ).fetchone()

    log("\n--- Respaldo ---")
    respaldar()

    log("\n--- Migrando ---")
    conexion = sqlite3.connect(db.RUTA_DB, timeout=30.0)
    conexion.row_factory = sqlite3.Row
    try:
        # Indispensable: `partidas` tiene ON DELETE CASCADE hacia `notas`.
        # Con las llaves activas, borrar la tabla vieja arrastraría las 246
        # partidas. Se apagan durante la reconstrucción y se revisa al final.
        conexion.execute("PRAGMA foreign_keys = OFF")
        conexion.execute("BEGIN")

        # Se declara aquí en vez de leer esquema.sql: ese archivo describe la
        # base ya migrada y ejecutarlo a medias contra la vieja es frágil.
        conexion.executescript(
            """
            CREATE TABLE IF NOT EXISTS vehiculos (
                id_vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
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
            CREATE INDEX IF NOT EXISTS idx_vehiculos_cliente
                ON vehiculos(id_cliente);
            """
        )

        mapa, avisos = derivar_vehiculos(conexion)
        log(f"  Vehículos derivados: {len(set(mapa.values()))}")
        log(f"  Notas enlazadas    : {len(mapa)}")

        reconstruir_notas(conexion, mapa)
        log("  Tabla `notas` reconstruida con estado y pagos")

        conexion.executescript(
            """
            CREATE TABLE IF NOT EXISTS taller (
                id        INTEGER PRIMARY KEY CHECK (id = 1),
                nombre    TEXT NOT NULL,
                subtitulo TEXT,
                direccion TEXT,
                telefono  TEXT,
                correo    TEXT,
                rfc       TEXT,
                pie_nota  TEXT,
                actualizado_en TEXT
            );
            """
        )
        sembrar_taller(conexion)
        log("  Tabla `taller` creada")

        violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            conexion.execute("ROLLBACK")
            raise SystemExit(
                f"Se revirtió todo: {len(violaciones)} violaciones de llave foránea."
            )

        conexion.execute("COMMIT")
        conexion.execute("PRAGMA foreign_keys = ON")
    except Exception:
        conexion.execute("ROLLBACK")
        raise
    finally:
        conexion.close()

    if avisos:
        log(f"\n--- Conflictos encontrados al agrupar ({len(avisos)}) ---")
        for aviso in avisos:
            log(f"  [!] {aviso}")

    log("\n--- Validación ---")
    with db.conectar() as conexion:
        despues_notas = conexion.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM notas"
        ).fetchone()
        despues_partidas = conexion.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM partidas"
        ).fetchone()
        vehiculos = conexion.execute(
            "SELECT COUNT(*) n FROM vehiculos"
        ).fetchone()["n"]
        sin_vehiculo = conexion.execute(
            "SELECT COUNT(*) n FROM notas WHERE id_vehiculo IS NULL"
        ).fetchone()["n"]

    ok = True
    for etiqueta, antes, despues in (
        ("Notas", antes_notas, despues_notas),
        ("Partidas", antes_partidas, despues_partidas),
    ):
        igual = antes["n"] == despues["n"] and antes["t"] == despues["t"]
        ok &= igual
        log(f"  {'[OK]' if igual else '[!!]'} {etiqueta}: "
            f"{antes['n']} → {despues['n']} filas, "
            f"{db.formato_pesos(antes['t'])} → {db.formato_pesos(despues['t'])}")

    log(f"  [i]  Vehículos creados: {vehiculos}")
    if sin_vehiculo:
        ok = False
        log(f"  [!!] {sin_vehiculo} notas quedaron sin vehículo")
    else:
        log("  [OK] Todas las notas tienen vehículo")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS — revisa arriba")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
