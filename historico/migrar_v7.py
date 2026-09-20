"""
Migración v7 — Diagnósticos con escáner.

Agrega `diagnosticos` y `diagnostico_codigos`: el reporte de códigos de falla
(DTC) que hoy se entrega en papel, capturado con el mismo cliente y vehículo
que una nota. No toca ninguna tabla existente ni el histórico de notas.

Es idempotente. Respalda antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar_v7.py
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
CREATE TABLE IF NOT EXISTS diagnosticos (
    id_diagnostico TEXT PRIMARY KEY,
    id_cliente     INTEGER NOT NULL REFERENCES clientes(id_cliente),
    id_vehiculo    INTEGER NOT NULL REFERENCES vehiculos(id_vehiculo),
    fecha          TEXT NOT NULL,
    tecnico        TEXT,
    num_modulos    INTEGER,
    otros_modulos  TEXT,
    resumen        TEXT,
    creado_en      TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (id_diagnostico GLOB 'DX-[0-9][0-9][0-9]*'),
    CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    CHECK (num_modulos IS NULL OR num_modulos >= 0)
);

CREATE TABLE IF NOT EXISTS diagnostico_codigos (
    id_item        INTEGER PRIMARY KEY AUTOINCREMENT,
    id_diagnostico TEXT NOT NULL REFERENCES diagnosticos(id_diagnostico)
                       ON DELETE CASCADE ON UPDATE CASCADE,
    linea          INTEGER NOT NULL CHECK (linea > 0),
    sistema        TEXT NOT NULL,
    sistema_nota   TEXT,
    codigo         TEXT NOT NULL,
    descripcion    TEXT NOT NULL,
    significado    TEXT NOT NULL,
    gravedad       TEXT NOT NULL DEFAULT 'MEDIA'
                   CHECK (gravedad IN ('ALTA', 'MEDIA', 'BAJA', 'INFO')),

    UNIQUE (id_diagnostico, linea),
    CHECK (length(trim(sistema)) > 0),
    CHECK (length(trim(codigo)) > 0),
    CHECK (length(trim(descripcion)) > 0),
    CHECK (length(trim(significado)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_diagnosticos_cliente  ON diagnosticos(id_cliente);
CREATE INDEX IF NOT EXISTS idx_diagnosticos_vehiculo ON diagnosticos(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_diagnostico_codigos_diag
    ON diagnostico_codigos(id_diagnostico);
"""


def log(mensaje: str = "") -> None:
    print(mensaje)


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v7 — Diagnósticos con escáner")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        existe = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='diagnosticos'"
        ).fetchone()
        antes_notas = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM notas"
        ).fetchone()

    if existe:
        log("\nLa base ya tiene diagnosticos. Nada que hacer.")
        return

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
        log("  Tablas creadas: diagnosticos, diagnostico_codigos")

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
        despues_notas = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM notas"
        ).fetchone()
        igual = (despues_notas["n"] == antes_notas["n"]
                 and despues_notas["t"] == antes_notas["t"])
        ok &= igual
        log(f"  {'[OK]' if igual else '[!!]'} notas intactas: "
            f"{antes_notas['n']} filas, "
            f"{db.formato_pesos(despues_notas['t'])}")

        n_diagnosticos = c.execute(
            "SELECT COUNT(*) n FROM diagnosticos"
        ).fetchone()["n"]
        log(f"  [i]  diagnosticos: {n_diagnosticos} (nueva tabla, vacía)")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
