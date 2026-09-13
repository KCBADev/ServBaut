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

import streamlit as st

# ---------------------------------------------------------------------------
# Paleta de interfaz — tablero claro con la paleta pedida por el taller
#
# Lienzo blanco y tarjetas en el verde-menta más claro de la paleta, para que
# el fondo y las tarjetas se distingan sin salir de los cinco colores dados.
# El texto va en negro casi puro (pedido explícito: "el texto preferentemente
# negro"), y los tres verdes-azulados quedan reservados para lo interactivo —
# botones, pestaña activa, enlace de navegación activo, foco — que es donde el
# taller pidió que la paleta "resalte". Los bordes en reposo van en un tono
# suave derivado (blanco mezclado con el acento), no en el acento a toda
# fuerza: así el color se nota más precisamente cuando algo se selecciona o
# recibe foco, en vez de repetirse igual de fuerte en cada recuadro.
# ---------------------------------------------------------------------------
FONDO = "#FFFFFF"           # lienzo, tal cual lo pidió el taller
PANEL = "#E0F2F1"           # el verde-menta de la paleta: tarjetas, barra
                            # lateral (base), campos
PANEL_HOVER = "#B4DBDA"     # panel + acento claro: hover y encabezados
BORDE = "#C0D7D7"           # blanco + acento al 30%: contorno en reposo
BORDE_TENUE = "#E6EFEF"     # blanco + acento al 12%: separadores discretos
TEXTO = "#1A1A1A"           # negro casi puro, pedido explícito
TEXTO_TENUE = "#275F5E"     # negro + acento claro: etiquetas, texto secundario
TEXTO_APAGADO = "#2B7473"   # el paso más apagado, siempre ≥ AA sobre blanco
ACENTO = "#2C7A7B"          # verde-azulado principal: botones, activo, foco
ACENTO_CLARO = "#319795"    # el más vivo de los tres: resaltes suaves
ACENTO_PROFUNDO = "#1E524C" # el más oscuro: hover de botón y degradado

# ---------------------------------------------------------------------------
# Paleta de datos
#
# `#2C7A7B` (el mismo acento de la interfaz) lleva las gráficas de una sola
# serie: barras de magnitud, área de tendencia, etc.
#
# El naranja sigue siendo el ÚNICO color fuera de la paleta del taller, y por
# la misma razón que antes: la paleta pedida es monocromática (tres verdes-
# azulados) y no puede separar dos categorías por tono sin salirse de la banda
# de luminosidad. Se revalida aquí sobre el lienzo BLANCO, no sobre el navy
# oscuro de antes: texto oscuro sobre cualquiera de las dos barras del mix
# pasa ≥3:1 (3.46:1 sobre el acento, 5.49:1 sobre el naranja), que es lo que
# usa la etiqueta directa del gráfico de mezcla.
# ---------------------------------------------------------------------------
SERIE_1 = ACENTO           # el acento del taller: serie única y magnitudes
SERIE_2 = "#D9772F"        # naranja: segundo elemento del mix
REJILLA = "#DAECEC"        # líneas de rejilla, discretas, sobre blanco
EJE = TEXTO_TENUE          # ejes y líneas base: mismo peso que el texto tenue


def _hoja_de_estilo() -> str:
    """El CSS completo de la aplicación."""
    return f"""
    <style>
    /* ------------------------------------------------------------------
       Campos de entrada
       Streamlit envuelve cada control en un contenedor propio; se pinta el
       ENVOLTORIO y no el <input>, porque algunos campos (contraseña, número,
       fecha) meten botones dentro del mismo contenedor y si solo se pintara
       el input esos botones quedarían como recuadros claros pegados.
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
        box-shadow: 0 0 0 2px rgba(44, 122, 123, .35) !important;
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
        background-color: rgba(49, 151, 149, .16) !important;
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
       Sobre fondo claro el hover debe OSCURECER, no aclarar — al revés que
       en un tema oscuro — porque es la convención que se espera y porque da
       mejor contraste: blanco sobre el acento profundo pasa 8.87:1, contra
       apenas 3.51:1 si aclarara hacia el verde más vivo de la paleta.
       ------------------------------------------------------------------ */
    .stButton button,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stDownloadButton"] button {{
        background-color: {ACENTO} !important;
        border: none !important;
        border-radius: 8px !important;
        transition: box-shadow .15s ease, background-color .15s ease;
    }}
    .stButton button, .stButton button p,
    [data-testid="stFormSubmitButton"] button,
    [data-testid="stFormSubmitButton"] button p,
    [data-testid="stDownloadButton"] button,
    [data-testid="stDownloadButton"] button p {{
        color: #FFFFFF !important;
        font-weight: 600 !important;
    }}
    .stButton button:hover,
    [data-testid="stFormSubmitButton"] button:hover,
    [data-testid="stDownloadButton"] button:hover {{
        background-color: {ACENTO_PROFUNDO} !important;
        box-shadow: 0 0 16px rgba(30, 82, 76, .45) !important;
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
        background-color: rgba(49, 151, 149, .14) !important;
        box-shadow: none !important;
    }}

    /* ------------------------------------------------------------------
       Barra lateral
       Degradado con los tres tonos de la paleta (de claro a oscuro, de
       arriba abajo) para que combine con el resto sin salirse de los
       colores pedidos. El texto de la barra lateral es blanco porque va
       sobre un fondo oscuro-medio, aunque el resto de la app use negro
       sobre blanco — es la única zona donde se invierte, a propósito.
       ------------------------------------------------------------------ */
    [data-testid="stSidebar"] {{
        background: linear-gradient(165deg, {ACENTO} 0%, {ACENTO_PROFUNDO} 100%) !important;
        border-right: none;
    }}
    [data-testid="stSidebar"] hr {{
        border-color: rgba(255, 255, 255, .18);
    }}
    [data-testid="stSidebar"] p,
    [data-testid="stSidebar"] span,
    [data-testid="stSidebar"] label,
    [data-testid="stSidebar"] h1,
    [data-testid="stSidebar"] h2,
    [data-testid="stSidebar"] h3 {{
        color: #FFFFFF !important;
    }}
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
        color: rgba(255, 255, 255, .72) !important;
    }}

    /* Navegación: el enlace activo se marca con un filete blanco a la
       izquierda — sobre el degradado, un filete del propio acento no se
       vería con el contraste suficiente en todos los puntos del gradiente. */
    [data-testid="stSidebarNav"] a {{
        border-radius: 6px;
        border-left: 2px solid transparent;
    }}
    [data-testid="stSidebarNav"] a:hover {{
        background-color: rgba(255, 255, 255, .12);
    }}
    [data-testid="stSidebarNav"] a[aria-current="page"] {{
        background-color: rgba(255, 255, 255, .20);
        border-left-color: #FFFFFF;
    }}

    /* El botón «Cerrar sesión» se invierte (blanco sobre el degradado) para
       que siga distinguiéndose de su propio fondo, que ya es del acento. */
    [data-testid="stSidebar"] .stButton button {{
        background-color: #FFFFFF !important;
    }}
    [data-testid="stSidebar"] .stButton button,
    [data-testid="stSidebar"] .stButton button p {{
        color: {ACENTO_PROFUNDO} !important;
    }}
    [data-testid="stSidebar"] .stButton button:hover {{
        background-color: {PANEL} !important;
        box-shadow: 0 0 14px rgba(255, 255, 255, .55) !important;
    }}

    /* «Cambiar mi contraseña» discreto: sin recuadro, chico y apagado
       mientras está cerrado, para que no compita con la navegación ni con
       «Cerrar sesión». Una vez abierto, el formulario de adentro se ve
       normal — lo discreto es solo el renglón de cerrado. */
    [data-testid="stSidebar"] [data-testid="stExpander"] {{
        background-color: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }}
    [data-testid="stSidebar"] [data-testid="stExpander"] summary {{
        padding: 2px 0 !important;
        min-height: unset !important;
    }}
    /* Ojo con el selector: va acotado a "summary" y no a todo el expansor,
       porque el formulario de adentro (una vez abierto) usa el mismo patrón
       stMarkdownContainer > p para sus propias etiquetas, y esas sí necesitan
       tinta oscura — es una tarjeta clara, no la barra lateral oscura. */
    [data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stMarkdownContainer"] p {{
        color: rgba(255, 255, 255, .55) !important;
        font-size: .78rem !important;
        font-weight: 400 !important;
    }}
    [data-testid="stSidebar"] [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {{
        color: rgba(255, 255, 255, .55) !important;
        font-size: 1rem !important;
    }}
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover [data-testid="stMarkdownContainer"] p,
    [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover [data-testid="stIconMaterial"] {{
        color: rgba(255, 255, 255, .9) !important;
    }}
    /* El formulario de adentro es una tarjeta clara igual que cualquier otra:
       sus etiquetas necesitan tinta oscura, no la blanca del resto de la
       barra lateral. Queda además de lo anterior, por si acaso. */
    [data-testid="stSidebar"] [data-testid="stExpanderDetails"] label,
    [data-testid="stSidebar"] [data-testid="stExpanderDetails"] p {{
        color: {TEXTO} !important;
    }}

    /* ------------------------------------------------------------------
       Tablas y dataframes
       ------------------------------------------------------------------ */
    [data-testid="stDataFrame"],
    [data-testid="stTable"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 8px;
    }}
    [data-testid="stDataFrame"] * {{
        color: {TEXTO};
    }}

    /* ------------------------------------------------------------------
       Métricas, expansores y contenedores
       ------------------------------------------------------------------ */
    [data-testid="stMetric"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 10px;
        padding: 14px 16px;
    }}
    [data-testid="stMetricLabel"] {{
        color: {TEXTO_TENUE} !important;
    }}
    [data-testid="stMetricValue"] {{
        color: {TEXTO} !important;
        /* Cuerpo algo menor que el de fábrica: los importes en pesos son
           cifras largas y al tamaño original se truncaban en las tarjetas
           estrechas, que es peor que verlas un punto más chicas. */
        font-size: 1.75rem !important;
        line-height: 1.25 !important;
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

    hr, [data-testid="stDivider"] {{
        border-color: {BORDE} !important;
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
       Densidad de tablero
       El tablero de referencia apila mucha información en poco espacio:
       tarjetas con contorno marcado, cifras grandes, etiquetas chicas en
       mayúsculas y tablas compactas con encabezado marcado.
       ------------------------------------------------------------------ */
    [data-testid="stMetric"] {{
        background-color: {PANEL};
        border: 1px solid {BORDE};
        border-radius: 10px;
        padding: 14px 16px 12px;
        /* Filete superior de acento, como las tarjetas de la referencia. */
        border-top: 2px solid {ACENTO};
        box-shadow: 0 1px 3px rgba(30, 82, 76, .12);
    }}
    [data-testid="stMetricLabel"] p {{
        font-size: .74rem !important;
        letter-spacing: .07em;
        text-transform: uppercase;
        color: {TEXTO_TENUE} !important;
    }}
    [data-testid="stMetricValue"] {{
        font-size: 1.7rem !important;
        line-height: 1.2 !important;
        color: {TEXTO} !important;
        font-weight: 600 !important;
    }}

    /* Encabezados de sección, al estilo «Márketing» / «Ventas». */
    .stApp h2, .stApp h3 {{
        letter-spacing: -.01em;
    }}
    .stApp [data-testid="stHeadingWithActionElements"] h3 {{
        font-size: 1.05rem;
    }}

    /* Tablas compactas con encabezado marcado y filas apretadas. */
    [data-testid="stDataFrame"] {{
        border: 1px solid {BORDE};
        border-radius: 10px;
        overflow: hidden;
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
        font-size: 1.05rem;
        font-weight: 600;
        color: {TEXTO};
    }}
    .seccion-nota {{
        font-size: .78rem;
        color: {TEXTO_APAGADO};
    }}
    </style>
    """


def seccion(titulo: str, nota: str = "") -> None:
    """Encabezado de bloque, al estilo de las secciones del tablero."""
    extra = f'<span class="seccion-nota">{nota}</span>' if nota else ""
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
    """Dibuja un bloque con el borde y el fondo de panel de la aplicación."""
    encabezado = f'<div class="tarjeta-titulo">{titulo}</div>' if titulo else ""
    st.markdown(f'<div class="tarjeta">{encabezado}{contenido}</div>',
                unsafe_allow_html=True)
