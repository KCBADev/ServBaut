"""
Estilos globales — System KCBA.

Un solo lugar define la paleta y el CSS de la aplicación, para que todas las
vistas compartan la misma estética.

El grueso del tema lo hace `.streamlit/config.toml` (colores base, barra
lateral negra, tipografía Inter, radios y colores de gráficas): todos los
componentes de Streamlit nacen ya con la paleta correcta. Este módulo solo
añade encima lo que el tema base no cubre: tarjetas, métricas, la tarjeta
destacada en negro y detalles de pestañas y tablas. Es más robusto que
reescribir cada componente a mano: si Streamlit cambia su marcado interno, el
tema base sigue funcionando.
"""

from __future__ import annotations

import html

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta de interfaz — blanco y negro
#
# Lienzo gris muy claro y tarjetas blancas: la tarjeta se recorta del fondo
# con apenas un borde y una sombra suave. El negro hace de acento —botones,
# pestaña activa, foco, la tarjeta destacada— porque en un diseño sin color
# lo que resalta es el contraste, no el tono.
#
# El único color fuera de la escala de grises es ALERTA: los errores y los
# saldos negativos siguen necesitando una señal que no dependa de leer.
# ---------------------------------------------------------------------------
FONDO = "#F4F5F7"            # lienzo general
PANEL = "#FFFFFF"            # tarjetas y campos
PANEL_HOVER = "#F0F1F3"      # hover y encabezados de tabla
BORDE = "#E3E5E8"            # contorno de tarjeta, discreto
BORDE_TENUE = "#ECEEF0"      # separadores que casi no se ven
TEXTO = "#111111"            # negro: cifras y títulos
TEXTO_TENUE = "#5F6368"      # gris medio: etiquetas y ejes (6.3:1 sobre blanco)
TEXTO_APAGADO = "#8A8F96"    # el paso más apagado, solo para notas
ACENTO = "#111111"           # negro: botones, activo, foco
ACENTO_PROFUNDO = "#2B2B2B"  # hover de botones y rellenos oscuros
ALERTA = "#B3261E"           # rojo: saldos, avisos, variación negativa

# Tinta que va ENCIMA del acento (botones, tarjeta destacada).
TINTA_SOBRE_ACENTO = "#FFFFFF"

# ---------------------------------------------------------------------------
# Paleta de datos — escala de grises, como la gráfica de referencia
#
# Negro para la serie principal y un gris medio para la segunda: se separan
# por claridad, que es lo único que distingue series en un diseño sin color.
# Las etiquetas DENTRO de una barra van claras sobre el negro y oscuras sobre
# el gris medio (`dashboard.py` las elige por serie).
# ---------------------------------------------------------------------------
SERIE_1 = "#1A1A1A"          # serie única y magnitudes
SERIE_2 = "#9A9A9A"          # segundo elemento del mix
SERIE_3 = "#D0D0D0"          # relleno de área, fondo de barra
REJILLA = "#ECEEF0"          # líneas de rejilla, apenas visibles
EJE = TEXTO_TENUE            # ejes y etiquetas

# El extremo de una magnitud (la barra de mayor valor): negro puro, un paso
# más fuerte que las demás barras — "la misma serie, pero la que gana".
DESTACADO = "#000000"
# La de menor valor reutiliza ALERTA: ya es el color de "atención" en toda
# la app, no hace falta uno nuevo para lo mismo.

# Rampa para repartir un todo en partes (el pastel de ingresos): grises con
# pasos de claridad parejos, del más oscuro al más claro, como la dona de la
# referencia. Cada rebanada sigue rotulada con su nombre y porcentaje.
RAMPA = ["#1A1A1A", "#4D4D4D", "#7A7A7A", "#A6A6A6", "#CFCFCF"]
RAMPA_RESTO = "#E6E6E6"

# Tipografía de títulos y cifras. La carga el tema (`config.toml`); aquí solo
# se nombra para las reglas que la necesitan explícita.
FUENTE_TITULOS = "'Inter', 'Segoe UI', system-ui, sans-serif"

SOMBRA = "0 1px 2px rgba(16,24,40,.04), 0 1px 3px rgba(16,24,40,.06)"


def _hoja_de_estilo() -> str:
    """El CSS completo de la aplicación."""
    return f"""
    <style>
    /* ------------------------------------------------------------------
       Títulos: Inter pesada con el interletrado cerrado, como los
       encabezados de un producto de software, no como un párrafo grande.
       ------------------------------------------------------------------ */
    .stApp h1 {{
        font-family: {FUENTE_TITULOS} !important;
        font-weight: 800 !important;
        font-size: 2.1rem !important;
        letter-spacing: -.035em !important;
        line-height: 1.15 !important;
        color: {TEXTO} !important;
        margin-bottom: .2rem !important;
    }}
    .stApp h2, .stApp h3 {{
        font-family: {FUENTE_TITULOS} !important;
        font-weight: 700 !important;
        letter-spacing: -.02em !important;
        color: {TEXTO} !important;
    }}
    .stApp [data-testid="stHeadingWithActionElements"] h3 {{
        font-size: 1.05rem;
    }}

    /* ------------------------------------------------------------------
       Campos de entrada: blancos, borde gris claro, foco en negro.
       Se pinta el ENVOLTORIO y no el <input>: algunos campos (contraseña,
       número, fecha) meten botones dentro del mismo contenedor.
       ------------------------------------------------------------------ */
    [data-testid="stTextInputRootElement"],
    [data-testid="stNumberInputContainer"],
    [data-baseweb="select"] > div,
    [data-baseweb="textarea"] {{
        background-color: {PANEL} !important;
        border-color: {BORDE} !important;
    }}
    [data-testid="stTextInputRootElement"]:focus-within,
    [data-testid="stNumberInputContainer"]:focus-within,
    [data-baseweb="select"] > div:focus-within,
    [data-baseweb="textarea"]:focus-within {{
        border-color: {ACENTO} !important;
        box-shadow: 0 0 0 3px rgba(17,17,17,.08) !important;
    }}

    /* ------------------------------------------------------------------
       Pestañas: inactivas en gris, activa en negro con subrayado.
       ------------------------------------------------------------------ */
    .stTabs [data-baseweb="tab-list"] {{
        border-bottom: 1px solid {BORDE};
        gap: 6px;
    }}
    .stTabs [data-baseweb="tab"] {{
        color: {TEXTO_TENUE} !important;
        font-weight: 500;
    }}
    .stTabs [data-baseweb="tab"]:hover,
    .stTabs [aria-selected="true"] {{
        color: {TEXTO} !important;
    }}
    .stTabs [aria-selected="true"] {{ font-weight: 600; }}
    .stTabs [data-baseweb="tab-highlight"] {{
        background-color: {ACENTO} !important;
    }}

    /* ------------------------------------------------------------------
       Botones: los de acción, negros con texto blanco; en un tema claro
       el hover se nota aclarando un poco el negro, no brillando.
       ------------------------------------------------------------------ */
    /* Streamlit marca cada botón con data-testid="stBaseButton-<tipo>". */
    [data-testid="stBaseButton-primary"],
    [data-testid$="FormSubmit"],
    [data-testid="stDownloadButton"] button {{
        background-color: {ACENTO} !important;
        border: 1px solid {ACENTO} !important;
        transition: background-color .15s ease;
    }}
    [data-testid="stBaseButton-primary"],
    [data-testid="stBaseButton-primary"] p,
    [data-testid$="FormSubmit"],
    [data-testid$="FormSubmit"] p,
    [data-testid="stDownloadButton"] button,
    [data-testid="stDownloadButton"] button p {{
        color: {TINTA_SOBRE_ACENTO} !important;
        font-weight: 600 !important;
    }}
    [data-testid="stBaseButton-primary"]:hover,
    [data-testid$="FormSubmit"]:hover,
    [data-testid="stDownloadButton"] button:hover {{
        background-color: {ACENTO_PROFUNDO} !important;
        border-color: {ACENTO_PROFUNDO} !important;
    }}
    /* Los secundarios: blancos con borde, como en la referencia. */
    [data-testid="stBaseButton-secondary"] {{
        background-color: {PANEL} !important;
        border: 1px solid {BORDE} !important;
        color: {TEXTO} !important;
        font-weight: 500;
    }}
    [data-testid="stBaseButton-secondary"]:hover {{
        border-color: {TEXTO} !important;
        background-color: {PANEL} !important;
    }}

    /* ------------------------------------------------------------------
       Barra lateral (negra por el tema): el enlace activo en una píldora
       blanca translúcida y el título de la marca en blanco.
       ------------------------------------------------------------------ */
    [data-testid="stSidebarNav"] a {{
        border-radius: 8px;
    }}
    [data-testid="stSidebarNav"] a:hover {{
        background-color: rgba(255,255,255,.06);
    }}
    [data-testid="stSidebarNav"] a[aria-current="page"] {{
        background-color: rgba(255,255,255,.12);
    }}
    [data-testid="stSidebar"] h3 {{
        color: #FFFFFF !important;
        font-weight: 700 !important;
        letter-spacing: -.01em !important;
    }}
    [data-testid="stSidebar"] [data-testid^="stBaseButton"] {{
        background-color: transparent !important;
        border: 1px solid #3A3A3A !important;
        color: #E6E6E6 !important;
    }}
    [data-testid="stSidebar"] [data-testid^="stBaseButton"]:hover {{
        border-color: #FFFFFF !important;
    }}

    /* ------------------------------------------------------------------
       Tarjetas, métricas y contenedores
       ------------------------------------------------------------------ */
    [data-testid="stMetric"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 14px;
        padding: 16px 18px 14px;
        box-shadow: {SOMBRA};
    }}
    [data-testid="stMetricLabel"] p {{
        font-size: .8rem !important;
        font-weight: 600 !important;
        color: {TEXTO_TENUE} !important;
    }}
    [data-testid="stMetricValue"] {{
        font-family: {FUENTE_TITULOS} !important;
        /* Algo menor que el de fábrica: los importes en pesos son cifras
           largas y al tamaño original se truncaban en tarjetas estrechas. */
        font-size: 1.65rem !important;
        line-height: 1.2 !important;
        color: {TEXTO} !important;
        font-weight: 700 !important;
        letter-spacing: -.02em;
    }}

    /* La tarjeta destacada del dashboard, en negro (la «Total Sales» de la
       referencia). La llave del contenedor la pone `dashboard.py`. */
    .st-key-kpi-destacado [data-testid="stMetric"] {{
        background-color: {ACENTO};
        border-color: {ACENTO};
    }}
    .st-key-kpi-destacado [data-testid="stMetricLabel"] p,
    .st-key-kpi-destacado [data-testid="stMetricValue"] {{
        color: {TINTA_SOBRE_ACENTO} !important;
    }}
    .st-key-kpi-destacado [data-testid="stMetricLabel"] p {{
        opacity: .75;
    }}

    [data-testid="stExpander"],
    [data-testid="stForm"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE} !important;
        border-radius: 14px;
        box-shadow: {SOMBRA};
    }}

    /* Tarjeta reutilizable para agrupar contenido en cualquier vista. */
    .tarjeta {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
        box-shadow: {SOMBRA};
    }}
    .tarjeta-titulo {{
        color: {TEXTO_TENUE};
        font-size: .8rem;
        font-weight: 600;
        margin-bottom: 8px;
    }}

    /* ------------------------------------------------------------------
       Tablas: tarjeta blanca, encabezado gris claro.
       ------------------------------------------------------------------ */
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {{
        background-color: {PANEL};
        border-radius: 14px;
        overflow: hidden;
    }}

    /* Los separadores compiten con los bordes de tarjeta: se atenúan. */
    hr, [data-testid="stDivider"] {{
        border-color: {BORDE_TENUE} !important;
    }}

    /* Encabezado de bloque dentro de una pantalla. */
    .seccion {{
        display: flex;
        align-items: baseline;
        gap: 12px;
        margin: 4px 0 12px;
    }}
    .seccion-titulo {{
        font-family: {FUENTE_TITULOS};
        font-size: 1.05rem;
        font-weight: 700;
        letter-spacing: -.01em;
        color: {TEXTO};
    }}
    .seccion-nota {{
        font-size: .8rem;
        color: {TEXTO_APAGADO};
    }}
    </style>
    """


def seccion(titulo: str, nota: str = "") -> None:
    """
    Encabezado de bloque, al estilo de las secciones del tablero.

    `titulo` y `nota` son siempre una etiqueta plana (hoy, literales escritos
    a mano en cada pantalla) — se escapan por si algún día alguien pasa aquí
    un dato de la base sin pensarlo dos veces.
    """
    titulo = html.escape(titulo)
    extra = (f'<span class="seccion-nota">{html.escape(nota)}</span>'
            if nota else "")
    st.markdown(
        f'<div class="seccion"><span class="seccion-titulo">{titulo}</span>'
        f'{extra}</div>',
        unsafe_allow_html=True,
    )


def apply_global_theme() -> None:
    """
    Inyecta el tema en la vista actual.

    Se llama desde `app.py` y también desde cada vista. Streamlit vuelve a
    ejecutar el script completo en cada interacción, así que `app.py` bastaría;
    llamarla desde cada módulo hace que una vista siga viéndose bien aunque se
    ejecute por separado (por ejemplo, desde las pruebas). Repetir una hoja de
    estilo idéntica no cambia el resultado.
    """
    st.markdown(_hoja_de_estilo(), unsafe_allow_html=True)
