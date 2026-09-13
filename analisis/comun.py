"""
Utilidades compartidas por los scripts de análisis.

Los análisis son independientes de la aplicación: no importan Streamlit y se
corren desde la terminal. Leen de la misma base que la app a través de db.py.

Todas las salidas van a `analisis/salidas/`, que está en el .gitignore porque
se regeneran corriendo los scripts de nuevo.
"""

from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd

# La raíz del proyecto es la carpeta padre de `analisis/`.
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import db  # noqa: E402  (necesita la ruta de arriba)

SALIDAS = RAIZ / "analisis" / "salidas"

# Misma paleta que el dashboard, validada para la superficie clara.
SERIE_1 = "#2a78d6"
SERIE_2 = "#eb6834"
SUPERFICIE = "#ffffff"
REJILLA = "#e1e0d9"
EJE = "#c3c2b7"
TINTA_TENUE = "#898781"
TINTA_SECUNDARIA = "#52514e"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def preparar() -> None:
    """Crea la carpeta de salidas y verifica que exista la base."""
    if not db.RUTA_DB.exists():
        raise SystemExit(
            "No existe taller.db. Corre primero:  "
            ".venv\\Scripts\\python.exe cargar_datos.py"
        )
    SALIDAS.mkdir(parents=True, exist_ok=True)


def titulo(texto: str) -> None:
    print()
    print("=" * 74)
    print(texto)
    print("=" * 74)


def pesos(centavos: int | None) -> float:
    """Convierte centavos a pesos como float, para graficar."""
    return float(db.centavos_a_pesos(centavos or 0))


def afinar(grafica: alt.Chart) -> alt.Chart:
    """Cromo discreto, igual que en el dashboard."""
    return (
        grafica
        .configure_view(strokeWidth=0)
        .configure_axis(
            gridColor=REJILLA, gridWidth=1, domainColor=EJE, tickColor=EJE,
            labelColor=TINTA_TENUE, titleColor=TINTA_SECUNDARIA,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_legend(
            labelColor=TINTA_SECUNDARIA, titleColor=TINTA_SECUNDARIA,
            labelFontSize=11, titleFontSize=11, symbolType="square",
        )
        .configure_title(color=TINTA_SECUNDARIA, fontSize=13,
                         fontWeight="normal", anchor="start")
    )


def barras(datos: pd.DataFrame, categoria: str, valor: str,
           titulo_valor: str, titulo_grafica: str,
           formato: str = "$,.0f") -> alt.Chart:
    """
    Barras horizontales de un solo color.

    Un color para todas: la longitud de la barra ya codifica la magnitud, y
    pintarlas según su valor gastaría el color en información repetida.
    """
    return afinar(
        alt.Chart(datos)
        .mark_bar(color=SERIE_1, cornerRadiusEnd=4, height=16)
        .encode(
            x=alt.X(f"{valor}:Q", title=titulo_valor,
                    axis=alt.Axis(format=formato)),
            y=alt.Y(f"{categoria}:N", title=None,
                    sort=alt.SortField(valor, order="descending")),
            tooltip=[alt.Tooltip(f"{categoria}:N"),
                     alt.Tooltip(f"{valor}:Q", format=formato)],
        )
        .properties(height=max(160, 26 * len(datos)), title=titulo_grafica)
    )


def guardar(nombre: str, tabla: pd.DataFrame,
            grafica: alt.Chart | None = None) -> None:
    """Guarda la tabla en CSV y, si la hay, la gráfica en PNG."""
    ruta_csv = SALIDAS / f"{nombre}.csv"
    tabla.to_csv(ruta_csv, index=False, encoding="utf-8-sig")
    print(f"\n  -> {ruta_csv.relative_to(RAIZ)}")

    if grafica is not None:
        ruta_png = SALIDAS / f"{nombre}.png"
        grafica.save(str(ruta_png), scale_factor=2)
        print(f"  -> {ruta_png.relative_to(RAIZ)}")


def cargar_notas() -> pd.DataFrame:
    """Todas las notas con su cliente, como DataFrame."""
    with db.conectar() as conexion:
        return pd.read_sql_query(
            """
            SELECT n.id_nota, n.fecha, n.id_cliente, cl.nombre AS cliente,
                   n.marca, n.anio, n.modelo, n.total_centavos
              FROM notas n
              JOIN clientes cl ON cl.id_cliente = n.id_cliente
             ORDER BY n.fecha
            """,
            conexion,
            parse_dates=["fecha"],
        )


def cargar_partidas() -> pd.DataFrame:
    """Todas las partidas con la fecha de su nota."""
    with db.conectar() as conexion:
        return pd.read_sql_query(
            """
            SELECT p.*, n.fecha, n.marca, n.id_cliente
              FROM partidas p
              JOIN notas n ON n.id_nota = p.id_nota
             ORDER BY n.fecha, p.id_nota, p.linea
            """,
            conexion,
            parse_dates=["fecha"],
        )
