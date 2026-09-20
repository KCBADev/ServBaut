"""
Migración v8 — Candados contra duplicados.

Agrega tres índices únicos que impiden volver a registrar el mismo cliente o
el mismo vehículo. No crea ni borra tablas, no toca ninguna fila: solo añade
índices.

Es idempotente. Respalda antes de tocar nada y, lo más importante, COMPRUEBA
ANTES que ninguna fila actual viole los índices; si encuentra alguna, aborta
sin haber modificado nada y dice cuáles son, para limpiarlas primero.

Uso:
    .venv\\Scripts\\python.exe migrar_v8.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ESQUEMA = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_vehiculos_placa_unica
    ON vehiculos (upper(trim(placas)))
 WHERE placas IS NOT NULL AND trim(placas) <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_vehiculos_sin_placa_unico
    ON vehiculos (id_cliente, upper(trim(marca)), ifnull(upper(trim(modelo)), ''),
                  ifnull(anio, 0), ifnull(upper(trim(color)), ''))
 WHERE placas IS NULL OR trim(placas) = '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_clientes_unico
    ON clientes (lower(trim(nombre)), ifnull(telefono, ''));
"""

# Cada consulta devuelve los grupos que YA están repetidos hoy. Si alguna trae
# filas, el índice correspondiente no se puede crear.
CONFLICTOS = {
    "placa repetida": """
        SELECT upper(trim(placas)) AS llave, COUNT(*) AS cuantos,
               group_concat(id_vehiculo) AS ids
          FROM vehiculos
         WHERE placas IS NOT NULL AND trim(placas) <> ''
         GROUP BY llave HAVING COUNT(*) > 1
    """,
    "vehículo sin placa repetido": """
        SELECT id_cliente || ' ' || upper(trim(marca)) || ' '
               || ifnull(upper(trim(modelo)), '') || ' ' || ifnull(anio, 0) || ' '
               || ifnull(upper(trim(color)), '') AS llave,
               COUNT(*) AS cuantos, group_concat(id_vehiculo) AS ids
          FROM vehiculos
         WHERE placas IS NULL OR trim(placas) = ''
         GROUP BY llave HAVING COUNT(*) > 1
    """,
    "cliente repetido": """
        SELECT lower(trim(nombre)) || ' / ' || ifnull(telefono, '') AS llave,
               COUNT(*) AS cuantos, group_concat(id_cliente) AS ids
          FROM clientes
         GROUP BY llave HAVING COUNT(*) > 1
    """,
}


def log(mensaje: str = "") -> None:
    print(mensaje)


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v8 — Candados contra duplicados")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        existe = c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name='idx_clientes_unico'"
        ).fetchone()
        if existe:
            log("\nLa base ya tiene los candados. Nada que hacer.")
            return

        log("\n--- Revisión previa: ¿hay duplicados que impidan el candado? ---")
        problemas = 0
        for descripcion, consulta in CONFLICTOS.items():
            filas = c.execute(consulta).fetchall()
            if filas:
                problemas += len(filas)
                log(f"  [!!] {descripcion}: {len(filas)} grupo(s)")
                for f in filas:
                    log(f"       «{f['llave']}» ×{f['cuantos']} → ids {f['ids']}")
            else:
                log(f"  [OK] sin {descripcion}")

        antes_clientes = c.execute("SELECT COUNT(*) n FROM clientes").fetchone()["n"]
        antes_vehiculos = c.execute("SELECT COUNT(*) n FROM vehiculos").fetchone()["n"]

    if problemas:
        raise SystemExit(
            f"\nABORTADO sin tocar la base: hay {problemas} grupo(s) duplicados. "
            f"Límpialos primero (deja el registro que tenga historial) y vuelve "
            f"a correr esta migración."
        )

    marca = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.respaldo-{marca}")
    shutil.copy2(db.RUTA_DB, destino)
    log(f"\n  Respaldo: {destino.name}")

    conexion = sqlite3.connect(db.RUTA_DB, timeout=30.0)
    conexion.row_factory = sqlite3.Row
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.executescript(ESQUEMA)
        conexion.commit()
        log("  Índices creados: idx_vehiculos_placa_unica, "
            "idx_vehiculos_sin_placa_unico, idx_clientes_unico")

        violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise SystemExit(
                f"{len(violaciones)} violaciones de llave foránea. "
                f"Restaura {destino.name}.")
    finally:
        conexion.close()

    log("\n--- Validación ---")
    ok = True
    with db.conectar() as c:
        despues_clientes = c.execute("SELECT COUNT(*) n FROM clientes").fetchone()["n"]
        despues_vehiculos = c.execute("SELECT COUNT(*) n FROM vehiculos").fetchone()["n"]
        intactos = (despues_clientes == antes_clientes
                    and despues_vehiculos == antes_vehiculos)
        ok &= intactos
        log(f"  {'[OK]' if intactos else '[!!]'} filas intactas: "
            f"{despues_clientes} clientes, {despues_vehiculos} vehículos")

        indices = {f["name"] for f in c.execute(
            "SELECT name FROM sqlite_master WHERE type='index' "
            "AND name LIKE 'idx_%unic%'")}
        esperados = {"idx_vehiculos_placa_unica", "idx_vehiculos_sin_placa_unico",
                     "idx_clientes_unico"}
        completos = esperados <= indices
        ok &= completos
        log(f"  {'[OK]' if completos else '[!!]'} los tres índices existen")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
