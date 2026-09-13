"""
Genera `ejemplo_taller.xlsx` — datos INVENTADOS con la estructura real.

Existe por una razón de privacidad: el archivo de origen del taller
(`1.MySQL_AutoSB.xlsx`) trae los nombres y teléfonos de clientes reales, así
que no se publica ni se versiona. Sin él, quien clone el repositorio no
tendría con qué probar `cargar_datos.py`. Este guion produce un libro con la
MISMA estructura —hojas `TC_TA` y `TSA`, mismos encabezados, misma columna D
vacía— pero con clientes que no existen.

Los nombres son ficticios y los teléfonos usan el prefijo 555, que no se
asigna a líneas reales. Las marcas, categorías y descripciones sí son las de
verdad: un modelo de coche o «Balatas delanteras» no identifican a nadie, y
usarlas hace que el ejemplo se parezca a un taller de verdad.

Los datos van escritos a mano, sin `random`, para que correrlo dos veces dé
exactamente el mismo archivo y el repositorio no se llene de diferencias que
no significan nada.

Uso:
    .venv\\Scripts\\python.exe generar_ejemplo.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pandas as pd

import exportar

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DESTINO = Path(__file__).resolve().parent / "ejemplo_taller.xlsx"

# (id, nombre, teléfono). El teléfono es TEXT de 10 dígitos: lo exige el
# CHECK de `esquema.sql`, y el prefijo 555 lo delata como inventado.
CLIENTES = [
    (1, "Alma Rosa Villaseñor", "5550100001"),
    (2, "Bernardo Quiroz Lander", "5550100002"),
    (3, "Carmen Elizondo Vega", None),
    (4, "Damián Ortuño Belmont", "5550100004"),
    (5, "Estela Zambrano Nava", "5550100005"),
    (6, "Faustino Arrieta Cepeda", "5550100006"),
    (7, "Gabriela Montiel Arroyo", "5550100007"),
    (8, "Hugo Everardo Lascurain", None),
    (9, "Irene Bustamante Loera", "5550100009"),
    (10, "Joaquín Berrones Prieto", "5550100010"),
    (11, "Leticia Cárdenas Mora", "5550100011"),
    (12, "Mauricio Tejeda Ibarra", "5550100012"),
]

# Cada renglón de servicio: tipo, categoría, acción, descripción, posición,
# lado, cantidad, precio unitario en pesos.
#
# Dos reglas del esquema que hay que respetar o la carga falla:
#   * un Servicio SIEMPRE lleva acción; un Producto NUNCA.
#   * posición solo admite Anterior/Posterior; lado, Derecho/Izquierdo/Par/
#     Centro.
NOTAS = [
    ("N-001", 1, date(2025, 1, 14), "Nissan", 2016, "Versa", "Blanco", [
        ("Producto", "Motor", None, "Aceite sintético 5W-30", None, None, 1, 850.0),
        ("Producto", "Motor", None, "Filtro de aceite", None, None, 1, 180.0),
        ("Servicio", "Motor", "Mantenimiento", "Cambio de aceite y filtro", None, None, 1, 350.0),
    ]),
    ("N-002", 2, date(2025, 1, 22), "Chevrolet", 2014, "Aveo", "Gris", [
        ("Producto", "Frenos", None, "Balatas delanteras", "Anterior", "Par", 1, 1010.0),
        ("Servicio", "Frenos", "Reemplazo", "Cambio de balatas", "Anterior", "Par", 1, 600.0),
        ("Servicio", "Frenos", "Rectificación", "Rectificado de discos", "Anterior", "Par", 2, 140.0),
    ]),
    ("N-003", 3, date(2025, 2, 3), "Ford", 2012, "Fiesta", "Rojo", [
        ("Producto", "Eléctrico", None, "Batería 12V 45Ah", None, None, 1, 2450.0),
        ("Servicio", "Eléctrico", "Instalación", "Instalación de batería", None, None, 1, 250.0),
    ]),
    ("N-004", 4, date(2025, 2, 17), "Volkswagen", 2018, "Jetta", "Negro", [
        ("Producto", "Suspensión", None, "Amortiguadores traseros", "Posterior", "Par", 2, 1850.0),
        ("Servicio", "Suspensión", "Reemplazo", "Cambio de amortiguadores", "Posterior", "Par", 1, 900.0),
        ("Servicio", "Dirección", "Ajuste", "Alineación y balanceo", None, None, 1, 450.0),
    ]),
    ("N-005", 5, date(2025, 3, 1), "Toyota", 2019, "Corolla", "Plata", [
        ("Servicio", "General", "Mantenimiento", "Servicio mayor de 40,000 km", None, None, 1, 3200.0),
        ("Producto", "Motor", None, "Bujías de iridio", None, None, 4, 320.0),
    ]),
    ("N-006", 6, date(2025, 3, 14), "Honda", 2015, "Civic", "Azul", [
        ("Producto", "Frenos", None, "Balatas traseras", "Posterior", "Par", 1, 890.0),
        ("Servicio", "Frenos", "Reemplazo", "Cambio de balatas", "Posterior", "Par", 1, 600.0),
    ]),
    ("N-007", 7, date(2025, 3, 28), "Mazda", 2017, "Mazda-3", "Blanco", [
        ("Servicio", "Transmisión", "Reparación", "Reparación de clutch", None, None, 1, 6800.0),
        ("Producto", "Transmisión", None, "Kit de clutch", None, None, 1, 4200.0),
    ]),
    ("N-008", 8, date(2025, 4, 9), "Jeep", 2013, "Patriot", "Cobre", [
        ("Servicio", "Escape", "Soldadura", "Soldadura de escape", None, "Centro", 1, 700.0),
    ]),
    ("N-009", 9, date(2025, 4, 23), "KIA", 2020, "Rio", "Gris", [
        ("Producto", "Llantas y rines", None, "Llanta 185/65 R15", None, None, 2, 1650.0),
        ("Servicio", "Llantas y rines", "Instalación", "Montaje y balanceo", None, "Par", 2, 150.0),
    ]),
    ("N-010", 10, date(2025, 5, 6), "Nissan", 2011, "Tsuru", "Blanco", [
        ("Servicio", "Motor", "Reparación", "Reparación de bomba de agua", None, None, 1, 1500.0),
        ("Producto", "Motor", None, "Bomba de agua", None, None, 1, 1250.0),
        ("Producto", "Motor", None, "Anticongelante", None, None, 2, 190.0),
    ]),
    ("N-011", 11, date(2025, 5, 20), "Chevrolet", 2016, "Spark", "Verde", [
        ("Servicio", "General", "Mantenimiento", "Lavado de motor y chasis", None, None, 1, 550.0),
        ("Servicio", "Eléctrico", "Programación", "Programación de llave", None, None, 1, 900.0),
    ]),
    ("N-012", 12, date(2025, 6, 11), "Ford", 2009, "F-150", "Azul", [
        ("Servicio", "Chasis", "Enderezado", "Enderezado de salpicadera", "Anterior", "Derecho", 1, 2400.0),
        ("Producto", "Chasis", None, "Salpicadera", "Anterior", "Derecho", 1, 3100.0),
    ]),
    ("N-013", 1, date(2025, 7, 2), "Nissan", 2016, "Versa", "Blanco", [
        ("Servicio", "Frenos", "Mantenimiento", "Purga de sistema de frenos", None, None, 1, 400.0),
        ("Producto", "Frenos", None, "Líquido de frenos DOT 4", None, None, 1, 250.0),
    ]),
    ("N-014", 5, date(2025, 8, 19), "Toyota", 2019, "Corolla", "Plata", [
        ("Servicio", "Combustible", "Mantenimiento", "Limpieza de inyectores", None, None, 4, 380.0),
    ]),
    ("N-015", 7, date(2025, 9, 5), "Mazda", 2017, "Mazda-3", "Blanco", [
        ("Producto", "Motor", None, "Aceite sintético 5W-30", None, None, 1, 850.0),
        ("Servicio", "Motor", "Mantenimiento", "Cambio de aceite y filtro", None, None, 1, 350.0),
        ("Producto", "Motor", None, "Filtro de aire", None, None, 1, 420.0),
    ]),
]


def construir() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Arma los tres marcos con las columnas exactas de la hoja del taller."""
    clientes = pd.DataFrame(
        [{"ID_Cliente (PK)": i, "Nombre": n, "Telefono": t}
         for i, n, t in CLIENTES],
        columns=["ID_Cliente (PK)", "Nombre", "Telefono"],
    )

    filas_notas, filas_servicios = [], []
    for folio, id_cliente, fecha, marca, anio, tipo, color, partidas in NOTAS:
        # El TOTAL de la nota se calcula aquí, no se escribe a mano: si no
        # cuadrara con la suma de sus renglones, `cargar_datos.py` abortaría.
        total = sum(cantidad * precio
                    for *_, cantidad, precio in partidas)
        filas_notas.append({
            "ID_N (PK)": folio,
            "ID_Cliente (FK)": id_cliente,
            "Fecha": fecha,
            "Marca": marca,
            "Año": anio,
            "Tipo": tipo,
            "Color": color,
            "TOTAL": round(total, 2),
        })
        for (concepto, categoria, accion, descripcion,
             posicion, lado, cantidad, precio) in partidas:
            filas_servicios.append({
                "ID_N (FK)": folio,
                "Tipo De concepto": concepto,
                "Categoría": categoria,
                "Acción": accion,
                "Descripción": descripcion,
                "Posición": posicion,
                "Lado": lado,
                "Cantidad": cantidad,
                "Precio unitario": round(precio, 2),
                "Total": round(cantidad * precio, 2),
                "Notas": None,
            })

    notas = pd.DataFrame(
        filas_notas,
        columns=["ID_N (PK)", "ID_Cliente (FK)", "Fecha", "Marca", "Año",
                 "Tipo", "Color", "TOTAL"],
    )
    servicios = pd.DataFrame(
        filas_servicios,
        columns=["ID_N (FK)", "Tipo De concepto", "Categoría", "Acción",
                 "Descripción", "Posición", "Lado", "Cantidad",
                 "Precio unitario", "Total", "Notas"],
    )
    return clientes, notas, servicios


def main() -> None:
    clientes, notas, servicios = construir()

    # Se escribe con el MISMO escritor que usa la exportación de la app, para
    # que el ejemplo y lo que descarga el taller no puedan divergir.
    DESTINO.write_bytes(
        exportar.escribir_libro_original(clientes, notas, servicios))

    print(f"Escrito: {DESTINO.name}")
    print(f"  {len(clientes)} clientes (inventados)")
    print(f"  {len(notas)} notas")
    print(f"  {len(servicios)} renglones de servicio")
    print(f"  Suma de TOTAL: ${notas['TOTAL'].sum():,.2f}")


if __name__ == "__main__":
    main()
