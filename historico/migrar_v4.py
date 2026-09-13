"""
Migración v4 — catálogo de productos e inventario.

Añade el catálogo maestro de productos que se compran y se venden (aceites,
refrigerantes, aerosoles…), con su propia taxonomía de categorías.

Convive con el catálogo de conceptos cobrables que ya existía: aquel incluye
unos 30 SERVICIOS (Alineación, Afinación, Rectificados, Mano de obra) que son
el grueso de la facturación y no son productos físicos. Son dos cosas
distintas y ninguna reemplaza a la otra.

Lo mismo con las categorías: `categorias` clasifica por SISTEMA DEL CARRO
(Suspensión, Motor, Frenos) y la usan las 246 partidas históricas;
`categorias_producto` clasifica por TIPO DE PRODUCTO (Aceites, Pintura,
Grasa y lubricantes). Un cambio de aceite es producto «Aceites» y sistema
«Motor» a la vez.

Es idempotente. Respalda antes de tocar nada.

Uso:
    .venv\\Scripts\\python.exe migrar_v4.py
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

CATEGORIAS = [
    ("C-01", "Aceites"),
    ("C-02", "Refrigerante"),
    ("C-03", "Frenos"),
    ("C-04", "Suspensión"),
    ("C-05", "Componente eléctrico"),
    ("C-06", "Chasis"),
    ("C-07", "Bombas"),
    ("C-08", "Pintura"),
    ("C-09", "Motor"),
    ("C-10", "Grasa y lubricantes"),
    ("C-11", "Limpieza de interior"),
]

# Los productos de la hoja de ejemplo. Precio en pesos; None = sin capturar.
# Nota: «Lmpiador» venía así en la hoja; se corrige a «Limpiador».
PRODUCTOS = [
    ("AB-001", "C-10", "HSS-2000", "ml", "Aerosol", 500, "Wurth", None, None, 8),
    ("AB-002", "C-10", "Rost off", "ml", "Aerosol", 400, "Wurth", None, None, 0),
    ("AB-003", "C-09", "Limpiador de carburador", "ml", "Aerosol", 500,
     "Wurth", None, None, 0),
    ("AB-004", "C-09", "Limpiador de cuerpo de aceleración", "ml", "Aerosol",
     500, "Zooms", 60.00, 150.00, 0),
    ("AB-005", "C-02", "Coolant Diesel long life", "L", "Galón", 3.7,
     "Roshfrans", 145.00, 300.00, 3),
    ("AB-006", "C-11", "Shampoo limpia parabrisas", "L", "Galón", 3.7,
     "Cartek", None, None, 0),
    ("AB-007", "C-01", "Aceite Roshfrans 5w-30", "L", "Botella", 1,
     "Roshfrans", 95.00, 110.00, 15),
]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS categorias_producto (
    id_cat TEXT PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    CHECK (id_cat GLOB 'C-[0-9][0-9]')
);

-- Las marcas de producto van en su propia tabla, igual que las de vehículo:
-- como texto libre acabarías con «Wurth» y «Würth» como dos proveedores.
CREATE TABLE IF NOT EXISTS marcas_producto (
    nombre TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS productos (
    id_producto  TEXT PRIMARY KEY,
    id_cat       TEXT NOT NULL REFERENCES categorias_producto(id_cat),
    nombre       TEXT NOT NULL,
    unidad       TEXT,                       -- ml, L, pza…
    presentacion TEXT,                       -- Aerosol, Galón, Botella…
    contenido    REAL,                       -- 500 (ml), 3.7 (L)…
    marca        TEXT REFERENCES marcas_producto(nombre),

    precio_compra_centavos INTEGER,
    precio_venta_centavos  INTEGER,

    -- Sin existencias, un mínimo no puede disparar ninguna alerta: por eso
    -- se agrega `stock_actual`, que la hoja original no tenía.
    stock_actual REAL NOT NULL DEFAULT 0,
    stock_min    REAL NOT NULL DEFAULT 0,

    activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en    TEXT NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT,

    CHECK (length(trim(nombre)) > 0),
    CHECK (precio_compra_centavos IS NULL OR precio_compra_centavos >= 0),
    CHECK (precio_venta_centavos IS NULL OR precio_venta_centavos >= 0),
    CHECK (stock_actual >= 0 AND stock_min >= 0)
);

CREATE INDEX IF NOT EXISTS idx_productos_cat    ON productos(id_cat);
CREATE INDEX IF NOT EXISTS idx_productos_activo ON productos(activo);
"""


def log(mensaje: str = "") -> None:
    print(mensaje)


def main() -> None:
    log("=" * 74)
    log("MIGRACIÓN v4 — catálogo de productos")
    log("=" * 74)

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    with db.conectar() as c:
        existe = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='productos'"
        ).fetchone()
        cols_partidas = [f["name"] for f in c.execute("PRAGMA table_info(partidas)")]

    falta_costo = "costo_unitario_centavos" not in cols_partidas
    if existe and not falta_costo:
        log("\nLa base ya tiene el catálogo de productos. Nada que hacer.")
        return

    marca_tiempo = datetime.now().strftime("%Y%m%d-%H%M%S")
    destino = db.RUTA_DB.with_name(f"{db.RUTA_DB.name}.respaldo-{marca_tiempo}")
    shutil.copy2(db.RUTA_DB, destino)
    log(f"\n  Respaldo: {destino.name}")

    conexion = sqlite3.connect(db.RUTA_DB, timeout=30.0)
    conexion.row_factory = sqlite3.Row
    try:
        conexion.execute("PRAGMA foreign_keys = ON")
        conexion.executescript(ESQUEMA)
        log("  Tablas creadas: categorias_producto, marcas_producto, productos")

        if falta_costo:
            # El precio de compra cambia con el tiempo. Para calcular margen
            # real de una nota vieja hay que saber cuánto costó ENTONCES, no
            # cuánto cuesta hoy; por eso la partida guarda su propia copia.
            conexion.execute(
                "ALTER TABLE partidas ADD COLUMN costo_unitario_centavos INTEGER")
            conexion.execute(
                "ALTER TABLE partidas ADD COLUMN id_producto TEXT "
                "REFERENCES productos(id_producto)")
            log("  partidas: columnas `costo_unitario_centavos` e `id_producto`")

        conexion.executemany(
            "INSERT INTO categorias_producto (id_cat, nombre) VALUES (?, ?) "
            "ON CONFLICT DO NOTHING", CATEGORIAS)

        marcas = sorted({p[6] for p in PRODUCTOS if p[6]})
        conexion.executemany(
            "INSERT INTO marcas_producto (nombre) VALUES (?) ON CONFLICT DO NOTHING",
            [(m,) for m in marcas])

        filas = [
            (id_prod, id_cat, nombre, unidad, present, contenido, marca,
             db.pesos_a_centavos(compra), db.pesos_a_centavos(venta),
             0, stock_min)
            for (id_prod, id_cat, nombre, unidad, present, contenido, marca,
                 compra, venta, stock_min) in PRODUCTOS
        ]
        conexion.executemany(
            """
            INSERT INTO productos (id_producto, id_cat, nombre, unidad,
                                   presentacion, contenido, marca,
                                   precio_compra_centavos, precio_venta_centavos,
                                   stock_actual, stock_min)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id_producto) DO NOTHING
            """,
            filas,
        )
        conexion.commit()

        violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
        if violaciones:
            raise SystemExit(
                f"{len(violaciones)} violaciones de llave foránea. "
                f"Restaura {destino.name}.")
    finally:
        conexion.close()

    log("\n--- Resultado ---")
    with db.conectar() as c:
        for tabla in ("categorias_producto", "marcas_producto", "productos"):
            n = c.execute(f"SELECT COUNT(*) n FROM {tabla}").fetchone()["n"]
            log(f"  {tabla:<22} {n}")

        sin_precio = c.execute(
            "SELECT COUNT(*) n FROM productos WHERE precio_venta_centavos IS NULL"
        ).fetchone()["n"]
        if sin_precio:
            log(f"\n  [!] {sin_precio} productos quedaron sin precio de venta. "
                f"Complétalos en Catálogo → Productos antes de usarlos en una nota.")

        # El catálogo de conceptos cobrables sigue intacto: es lo que permite
        # seguir cobrando servicios, que son el grueso de la facturación.
        conceptos = c.execute("SELECT COUNT(*) n FROM catalogo").fetchone()["n"]
        servicios = c.execute(
            "SELECT COUNT(*) n FROM catalogo WHERE tipo_concepto = 'Servicio'"
        ).fetchone()["n"]
        log(f"\n  [i]  Catálogo de conceptos intacto: {conceptos} "
            f"({servicios} servicios)")

    log()
    log("=" * 74)
    log("MIGRACIÓN COMPLETADA")
    log("=" * 74)


if __name__ == "__main__":
    main()
