"""
Estilos globales — Auto Servicio Bautista.

Un solo lugar define la paleta y el CSS de la aplicación, para que todas las
vistas compartan la estética de la pantalla de acceso.

El grueso del tema lo hace `.streamlit/config.toml`: al fijar ahí
`backgroundColor`, `secondaryBackgroundColor` y `textColor`, todos los
componentes de Streamlit nacen con la paleta correcta. Este módulo solo añade
encima los acentos, los bordes de los paneles y los detalles que el tema base
no cubre. Es más robusto que reescribir cada componente a mano: si Streamlit
cambia su marcado interno, el tema base sigue funcionando.
"""

from __future__ import annotations

import html

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta de interfaz — panel de control oscuro
#
# Dos azules-carbón distintos hacen de lienzo y de tarjeta: así una tarjeta se
# recorta del fondo sin necesitar borde, que es lo que da el aire de tablero.
# El verde menta queda reservado para lo que de verdad importa —cifras,
# botones, estado activo, foco— y no se reparte por todos lados: si todo
# brilla, nada resalta.
#
# Dos reglas de contraste que decidieron varias cosas de más abajo, medidas
# sobre esta misma paleta:
#   * Dentro de un botón o barra de menta, la tinta va OSCURA (10.05:1);
#     clara daría 1.32:1 y sería ilegible. Es al revés que en el tema claro.
#   * El coral solo sirve de RELLENO. Como texto sobre tarjeta da 2.85:1 y no
#     pasa ni para cuerpo grande.
# ---------------------------------------------------------------------------
FONDO = "#091017"            # azul marino / carbón: lienzo general
PANEL = "#171B24"            # gris azulado: tarjetas y campos
PANEL_HOVER = "#1F2530"      # un paso más claro: hover y encabezados de tabla
BORDE = "#2F3742"            # contorno de tarjeta, discreto
BORDE_TENUE = "#1D242B"      # separadores que casi no se ven
TEXTO = "#D2D8DE"            # gris claro: cifras y títulos
TEXTO_TENUE = "#898F96"      # gris azulado medio: etiquetas y ejes
TEXTO_APAGADO = "#6E757C"    # el paso más apagado
ACENTO = "#18D59C"           # verde menta: botones, activo, foco
ACENTO_PROFUNDO = "#124839"  # verde esmeralda oscuro: rellenos y degradados
ALERTA = "#A2444C"           # rojo coral: saldos, avisos, variación negativa

# Tinta que va ENCIMA del acento (botones, barras). Oscura a propósito: ver
# la nota de contraste de arriba.
TINTA_SOBRE_ACENTO = FONDO

# ---------------------------------------------------------------------------
# Paleta de datos
#
# El menta lleva las series de un solo color. El coral es el segundo tono del
# mix: separado del menta por 3.18:1 y del lienzo por 3.16:1, que es el piso
# para marcas de gráfica. Los dos vienen de la paleta del taller; no hace
# falta inventar un color de fuera como en el tema anterior.
#
# Las etiquetas que van DENTRO de una barra no pueden ser de un solo color:
# sobre el menta necesitan tinta oscura (10.05:1) y sobre el coral, clara
# (4.22:1). `dashboard.py` las calcula por serie.
# ---------------------------------------------------------------------------
SERIE_1 = ACENTO             # serie única y magnitudes
SERIE_2 = ALERTA             # segundo elemento del mix
SERIE_3 = ACENTO_PROFUNDO    # relleno de área, fondo de barra
REJILLA = "#1D242B"          # líneas de rejilla, apenas visibles
EJE = TEXTO_TENUE            # ejes y etiquetas: mismo peso que el texto tenue

# Para destacar el extremo de una magnitud (las barras del dashboard: la
# categoría, marca o cliente con el valor más alto). Un verde MÁS OSCURO que
# el menta de las demás barras, no otro color de familia distinta — se lee
# como "la misma serie, pero la que gana", en vez de una categoría aparte.
DESTACADO = "#00632B"        # verde esmeralda oscuro: la barra de mayor valor
# La de menor valor reutiliza ALERTA (rojo coral): ya es el color de
# "atención" en toda la app, no hace falta uno nuevo para lo mismo.

# Rampa para repartir un todo en varias partes por categoría (el pastel de
# ingresos): verdes elegidos a propósito, con suficiente variación de tono y
# saturación entre sí (no solo de claridad) para que cada rebanada se
# distinga de sus vecinas a simple vista, de la más oscura a la más clara.
# El gris queda para el cajón de «Otras», que no es una categoría más sino
# el resto; y aun con colores distintos cada rebanada sigue rotulada con su
# nombre y su porcentaje, y debajo va la tabla.
RAMPA = ["#00632B", "#42AD72", "#44AB00", "#5A8B00", "#7AE582"]
RAMPA_RESTO = TEXTO_APAGADO

# Tipografía de los títulos. Se carga de Google Fonts; si la máquina está sin
# red, cae a la de sistema y la app se ve bien igual, solo menos personal.
FUENTE_TITULOS = "'Sora', 'Segoe UI', system-ui, sans-serif"


def _hoja_de_estilo() -> str:
    """El CSS completo de la aplicación."""
    return f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Sora:wght@600;700;800&display=swap');

    /* ------------------------------------------------------------------
       Títulos
       El título de cada pantalla es lo primero que se ve, y de fábrica es
       solo texto un poco más grande. Con una tipografía de display, más
       peso y el interletrado cerrado, la pantalla arranca con algo que se
       lee como encabezado y no como párrafo.
       ------------------------------------------------------------------ */
    .stApp h1 {{
        font-family: {FUENTE_TITULOS} !important;
        font-weight: 800 !important;
        font-size: 2.6rem !important;
        letter-spacing: -.03em !important;
        line-height: 1.1 !important;
        color: {TEXTO} !important;
        margin-bottom: .35rem !important;
    }}
    .stApp h2, .stApp h3 {{
        font-family: {FUENTE_TITULOS} !important;
        font-weight: 700 !important;
        letter-spacing: -.015em !important;
        color: {TEXTO} !important;
    }}
    .stApp [data-testid="stHeadingWithActionElements"] h3 {{
        font-size: 1.05rem;
    }}

    /* ------------------------------------------------------------------
       Campos de entrada
       Streamlit envuelve cada control en un contenedor propio; se pinta el
       ENVOLTORIO y no el <input>, porque algunos campos (contraseña, número,
       fecha) meten botones dentro del mismo contenedor y si solo se pintara
       el input esos botones quedarían como recuadros de otro color.
       ------------------------------------------------------------------ */
    [data-testid="stTextInputRootElement"],
    [data-testid="stNumberInputContainer"],
    [data-baseweb="input"],
    [data-baseweb="select"] > div,
    [data-baseweb="textarea"],
    .stDateInput [data-baseweb="input"],
    .stTextArea textarea {{
        background-color: {PANEL} !important;
        border: 1px solid {BORDE} !important;
        border-radius: 8px !important;
        color: {TEXTO} !important;
    }}

    [data-testid="stTextInputRootElement"]:focus-within,
    [data-testid="stNumberInputContainer"]:focus-within,
    [data-baseweb="input"]:focus-within,
    [data-baseweb="select"] > div:focus-within,
    [data-baseweb="textarea"]:focus-within,
    .stTextArea textarea:focus {{
        border-color: {ACENTO} !important;
        box-shadow: 0 0 0 2px rgba(24, 213, 156, .30) !important;
    }}

    /* El campo en sí queda transparente: el color lo pone el envoltorio. */
    [data-testid="stTextInputField"],
    .stNumberInput input,
    .stTextArea textarea,
    [data-baseweb="input"] input {{
        background-color: transparent !important;
        color: {TEXTO} !important;
    }}

    /* Menús desplegables (se montan fuera del contenedor del campo). */
    [data-baseweb="popover"] [role="listbox"],
    [data-baseweb="menu"],
    [data-baseweb="calendar"] {{
        background-color: {PANEL} !important;
        border: 1px solid {BORDE} !important;
    }}
    [data-baseweb="menu"] li:hover {{
        background-color: rgba(24, 213, 156, .16) !important;
    }}

    /* ------------------------------------------------------------------
       Pestañas: fondo transparente, inactivas atenuadas, activa en acento
       ------------------------------------------------------------------ */
    .stTabs [data-baseweb="tab-list"] {{
        background-color: transparent !important;
        border-bottom: 1px solid {BORDE};
        gap: 4px;
    }}
    .stTabs [data-baseweb="tab"] {{
        background-color: transparent !important;
        color: {TEXTO_TENUE} !important;
        font-weight: 500;
    }}
    .stTabs [data-baseweb="tab"]:hover {{
        color: {TEXTO} !important;
    }}
    .stTabs [aria-selected="true"] {{
        color: {ACENTO} !important;
    }}
    .stTabs [data-baseweb="tab-highlight"],
    .stTabs [data-baseweb="tab-border"] {{
        background-color: {ACENTO} !important;
    }}

    /* ------------------------------------------------------------------
       Botones
       Sobre fondo oscuro el hover ACLARA, no oscurece: es la convención en
       un tema oscuro y es lo único que se nota sobre este lienzo. La tinta
       del botón va oscura porque el menta es un color claro — ver la nota
       de contraste de la paleta.
       ------------------------------------------------------------------ */
    .stButton button,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stDownloadButton"] button {{
        background-color: {ACENTO} !important;
        border: none !important;
        border-radius: 8px !important;
        transition: box-shadow .15s ease, filter .15s ease;
    }}
    .stButton button, .stButton button p,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stFormSubmitButton"] button p,
    [data-testid="stDownloadButton"] button,
    [data-testid="stDownloadButton"] button p {{
        color: {TINTA_SOBRE_ACENTO} !important;
        font-weight: 700 !important;
    }}
    .stButton button:hover,
    [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stDownloadButton"] button:hover {{
        filter: brightness(1.12) !important;
        box-shadow: 0 0 18px rgba(24, 213, 156, .35) !important;
    }}

    /* El ojito de la contraseña y los pasos del campo numérico no son
       botones de acción: no deben ir en color de acento. */
    [data-testid="stTextInputRootElement"] button,
    [data-testid="stNumberInputContainer"] button {{
        background-color: transparent !important;
        color: {TEXTO_TENUE} !important;
        box-shadow: none !important;
    }}
    [data-testid="stTextInputRootElement"] button:hover,
    [data-testid="stNumberInputContainer"] button:hover {{
        background-color: rgba(24, 213, 156, .14) !important;
        box-shadow: none !important;
        filter: none !important;
    }}

    /* ------------------------------------------------------------------
       Barra lateral
       Un punto más oscura que el lienzo, no más clara: así el contenido
       queda al frente y la navegación se va al fondo, que es el orden en
       que se miran.
       ------------------------------------------------------------------ */
    [data-testid="stSidebar"] {{
        background: linear-gradient(180deg, {PANEL} 0%, {FONDO} 100%) !important;
        border-right: 1px solid {BORDE};
    }}
    [data-testid="stSidebar"] hr {{
        border-color: {BORDE};
    }}

    /* Navegación: filete de acento a la izquierda del enlace activo, en vez
       de un bloque de color que competiría con los botones. */
    [data-testid="stSidebarNav"] a {{
        border-radius: 6px;
        border-left: 2px solid transparent;
    }}
    [data-testid="stSidebarNav"] a:hover {{
        background-color: rgba(24, 213, 156, .10);
    }}
    [data-testid="stSidebarNav"] a[aria-current="page"] {{
        background-color: rgba(24, 213, 156, .16);
        border-left-color: {ACENTO};
    }}

    /* ------------------------------------------------------------------
       Tarjetas, métricas y contenedores
       ------------------------------------------------------------------ */
    [data-testid="stMetric"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 10px;
        padding: 14px 16px 12px;
        /* Filete superior de acento, como las tarjetas de un tablero. */
        border-top: 2px solid {ACENTO};
    }}
    [data-testid="stMetricLabel"] p {{
        font-size: .74rem !important;
        letter-spacing: .07em;
        text-transform: uppercase;
        color: {TEXTO_TENUE} !important;
    }}
    [data-testid="stMetricValue"] {{
        font-family: {FUENTE_TITULOS} !important;
        /* Cuerpo algo menor que el de fábrica: los importes en pesos son
           cifras largas y al tamaño original se truncaban en las tarjetas
           estrechas, que es peor que verlas un punto más chicas. */
        font-size: 1.7rem !important;
        line-height: 1.2 !important;
        color: {TEXTO} !important;
        font-weight: 700 !important;
    }}

    [data-testid="stExpander"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE} !important;
        border-radius: 8px;
    }}

    [data-testid="stForm"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE} !important;
        border-radius: 10px;
    }}

    /* Tarjeta reutilizable para agrupar contenido en cualquier vista. */
    .tarjeta {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 10px;
        padding: 18px 20px;
        margin-bottom: 14px;
    }}
    .tarjeta-titulo {{
        color: {TEXTO_TENUE};
        font-size: .74rem;
        letter-spacing: .14em;
        text-transform: uppercase;
        margin-bottom: 8px;
    }}

    /* Avisos: se conserva el color semántico, se ajusta el fondo. */
    [data-testid="stAlert"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 8px;
    }}

    /* ------------------------------------------------------------------
       Tablas compactas, con encabezado marcado y filas apretadas
       ------------------------------------------------------------------ */
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 10px;
        overflow: hidden;
    }}
    [data-testid="stDataFrame"] * {{
        color: {TEXTO};
    }}
    [data-testid="stDataFrame"] thead tr th {{
        background-color: {PANEL_HOVER} !important;
        color: {TEXTO_TENUE} !important;
        font-size: .74rem !important;
        letter-spacing: .06em;
        text-transform: uppercase;
    }}
    [data-testid="stDataFrame"] tbody tr:hover td {{
        background-color: {PANEL_HOVER} !important;
    }}

    /* Los separadores compiten con los bordes de tarjeta: se atenúan. */
    hr, [data-testid="stDivider"] {{
        border-color: {BORDE_TENUE} !important;
        opacity: .8;
    }}

    /* Contenedor de sección: agrupa un bloque de tarjetas bajo un título. */
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
        color: {TEXTO};
    }}
    .seccion-nota {{
        font-size: .78rem;
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


def tarjeta(contenido: str, titulo: str | None = None) -> None:
    """
    Dibuja un bloque con el borde y el fondo de panel de la aplicación.

    `titulo` es una etiqueta plana y se escapa. `contenido` se inserta TAL
    CUAL, sin escapar — a propósito, porque el punto de esta función es
    aceptar marcado (un `<b>`, un `<div>` anidado). Quien la llame es
    responsable de escapar cualquier dato que no controle (un nombre de
    cliente, una descripción) antes de pasarlo aquí.
    """
    encabezado = (f'<div class="tarjeta-titulo">{html.escape(titulo)}</div>'
                 if titulo else "")
    st.markdown(f'<div class="tarjeta">{encabezado}{contenido}</div>',
                unsafe_allow_html=True)
