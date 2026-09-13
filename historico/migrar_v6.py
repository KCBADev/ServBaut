"""
Migración v6 — Cotizaciones.

Agrega `cotizaciones` y `cotizacion_partidas`: el mismo formulario que una
nota (cliente, vehículo, renglones, IVA), pero sin folio de servicio, para
capturar presupuestos antes de que el cliente diga que sí. No tocan ninguna
tabla existente ni el histórico de notas.

Es idempotente. Respalda antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar_v6.py
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
CREATE TABLE IF NOT EXISTS cotizaciones (
    id_cotizacion TEXT PRIMARY KEY,
    id_cliente    INTEGER NOT NULL REFERENCES clientes(id_cliente),
    id_vehiculo   INTEGER NOT NULL REFERENCES vehiculos(id_vehiculo),
    fecha         TEXT NOT NULL,

    subtotal_centavos INTEGER NOT NULL DEFAULT 0
        CHECK (subtotal_centavos >= 0),
    tasa_iva      REAL NOT NULL DEFAULT 0 CHECK (tasa_iva >= 0 AND tasa_iva <= 1),
    total_centavos INTEGER NOT NULL DEFAULT 0 CHECK (total_centavos >= 0),

    estado        TEXT NOT NULL DEFAULT 'Pendiente'
                  CHECK (estado IN ('Pendiente', 'Convertida', 'Rechazada')),
    id_nota_generada TEXT REFERENCES notas(id_nota),

    creado_en     TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (id_cotizacion GLOB 'COT-[0-9][0-9][0-9]*'),
    CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    CHECK ((estado = 'Convertida') = (id_nota_generada IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS cotizacion_partidas (
    id_item       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cotizacion TEXT NOT NULL REFERENCES cotizaciones(id_cotizacion)
                      ON DELETE CASCADE ON UPDATE CASCADE,
    linea         INTEGER NOT NULL CHECK (linea > 0),
    id_catalogo   INTEGER REFERENCES catalogo(id_catalogo),
    id_producto   TEXT REFERENCES productos(id_producto),

    tipo_concepto TEXT NOT NULL CHECK (tipo_concepto IN ('Producto', 'Servicio')),
    categoria     TEXT NOT NULL REFERENCES categorias(nombre),
    accion        TEXT REFERENCES acciones(nombre),
    descripcion   TEXT NOT NULL,
    posicion      TEXT CHECK (posicion IS NULL OR posicion IN ('Anterior', 'Posterior')),
    lado          TEXT CHECK (lado IS NULL OR lado IN ('Derecho', 'Izquierdo', 'Par', 'Centro')),

    cantidad      INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario_centavos INTEGER NOT NULL CHECK (precio_unitario_centavos >= 0),
    total_centavos           INTEGER NOT NULL,
    notas         TEXT,

    UNIQUE (id_cotizacion, linea),
    CHECK (total_centavos = cantidad * precio_unitario_centavos),
    CHECK ((tipo_concepto = 'Servicio' AND accion IS NOT NULL)
        OR (tipo_concepto = 'Producto' AND accion IS NULL))
);

CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_insert
AFTER INSERT ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = NEW.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = NEW.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = NEW.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_delete
AFTER DELETE ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = OLD.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = OLD.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = OLD.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = OLD.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_update
AFTER UPDATE ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = OLD.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = OLD.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = OLD.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = OLD.id_cotizacion;
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = NEW.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = NEW.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = NEW.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizaciones_iva
AFTER UPDATE OF tasa_iva ON cotizaciones
BEGIN
    UPDATE cotizaciones
       SET total_centavos = NEW.subtotal_centavos
                          + CAST(ROUND(NEW.subtotal_centavos * NEW.tasa_iva)
                                 AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

CREATE INDEX IF NOT EXISTS idx_cotizaciones_cliente  ON cotizaciones(id_cliente);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_vehiculo ON cotizaciones(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_estado   ON cotizaciones(estado);
CREATE INDEX IF NOT EXISTS idx_cotizacion_partidas_cot
    ON cotizacion_partidas(id_cotizacion);
"""


def log(mensaje: str = "") -> None:
    print(mensaje)


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v6 — Cotizaciones")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        existe = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name='cotizaciones'"
        ).fetchone()
        antes_notas = c.execute(
            "SELECT COUNT(*) n, COALESCE(SUM(total_centavos),0) t FROM notas"
        ).fetchone()

    if existe:
        log("\nLa base ya tiene cotizaciones. Nada que hacer.")
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
        log("  Tablas creadas: cotizaciones, cotizacion_partidas")
        log("  Triggers de subtotal/IVA agregados")

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

        n_cotizaciones = c.execute(
            "SELECT COUNT(*) n FROM cotizaciones"
        ).fetchone()["n"]
        log(f"  [i]  cotizaciones: {n_cotizaciones} (nueva tabla, vacía)")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA" if ok else "MIGRACIÓN CON PROBLEMAS")
    log("=" * 74)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
