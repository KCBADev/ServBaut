"""
Aplicación de administración — Servicio Bautista.

Punto de entrada de Streamlit. Se encarga de la autenticación y de la
navegación; toda la lógica de datos vive en db.py y el contenido de cada
pantalla en el paquete `paginas`.

Uso:
    .venv\\Scripts\\streamlit.exe run app.py
"""

from __future__ import annotations

import random

import streamlit as st

import auth
import db
import styles
from paginas import (catalogo, clientes, configuracion, cotizaciones,
                     crear_nota, dashboard, notas, reportes, vehiculos)

st.set_page_config(
    page_title="Servicio Bautista",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Tras este número de intentos fallidos se bloquea el formulario un momento.
# No es una defensa fuerte, solo evita el tanteo a ciegas.
MAX_INTENTOS = 5

# --- Fondo animado de la pantalla de acceso ---
NEON = "#38e8ff"
PUNTOS = 70
# Semilla fija: sin ella los puntos cambiarían de sitio en cada recarga de
# Streamlit (que ocurre en cada tecla y cada clic) y el fondo daría brincos.
SEMILLA = 20260902


def _css_lluvia() -> str:
    """
    Genera el CSS de los puntos que caen.

    Va todo en una hoja de estilo en vez de estilos en línea porque Streamlit
    filtra el HTML que se le inyecta, y un bloque <style> sobrevive entero.
    Tampoco se puede usar JavaScript: Streamlit no ejecuta los <script> que se
    le pasan, así que la animación es CSS puro.
    """
    aleatorio = random.Random(SEMILLA)
    reglas = []
    for indice in range(1, PUNTOS + 1):
        izquierda = aleatorio.uniform(0, 100)
        tamano = aleatorio.uniform(2, 7)
        duracion = aleatorio.uniform(7, 20)
        # Retraso negativo: al primer pintado los puntos ya vienen cayendo a
        # media pantalla, en vez de aparecer todos juntos desde arriba.
        retraso = -aleatorio.uniform(0, duracion)
        opacidad = aleatorio.uniform(0.25, 1.0)
        desenfoque = 0 if tamano > 4 else aleatorio.choice([0, 0, 1])
        reglas.append(
            f"#lluvia i:nth-child({indice}){{"
            f"left:{izquierda:.2f}%;"
            f"width:{tamano:.1f}px;height:{tamano:.1f}px;"
            f"animation-duration:{duracion:.1f}s;"
            f"animation-delay:{retraso:.1f}s;"
            f"opacity:{opacidad:.2f};"
            f"filter:blur({desenfoque}px)}}"
        )
    return "".join(reglas)


def _fondo_animado() -> None:
    """Pinta el fondo negro y la lluvia de puntos detrás del formulario."""
    puntos = "<i></i>" * PUNTOS
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Jost:wght@200;300;400&display=swap');

        /* --- Fondo --- */
        .stApp {{
            background:
                radial-gradient(ellipse at 50% 0%,
                                rgba(56,232,255,.09), transparent 60%),
                #000000;
        }}
        [data-testid="stHeader"] {{ background: transparent; }}

        /* --- La lluvia va detrás de todo y no intercepta clics --- */
        #lluvia {{
            position: fixed;
            inset: 0;
            overflow: hidden;
            pointer-events: none;
            z-index: 0;
        }}
        #lluvia i {{
            position: absolute;
            top: 0;
            display: block;
            border-radius: 50%;
            background: {NEON};
            box-shadow: 0 0 6px {NEON}, 0 0 16px rgba(56,232,255,.55);
            animation-name: caer;
            animation-timing-function: linear;
            animation-iteration-count: infinite;
        }}
        @keyframes caer {{
            from {{ transform: translateY(-12vh); }}
            to   {{ transform: translateY(112vh); }}
        }}
        {_css_lluvia()}

        /* Quien pidió menos movimiento se queda con el fondo, sin la lluvia. */
        @media (prefers-reduced-motion: reduce) {{
            #lluvia {{ display: none; }}
        }}

        /* --- El contenido, por encima de la lluvia --- */
        [data-testid="stMainBlockContainer"], .block-container {{
            position: relative;
            z-index: 1;
        }}

        /* --- Texto legible sobre el negro --- */
        .stApp h1, .stApp h2, .stApp h3,
        .stApp p, .stApp label, .stApp span {{ color: #dff6ff; }}

        /* --- Wordmark ---
           Geométrica en mayúsculas con tracking amplio y peso ligero, como
           bloquean su nombre las marcas automotrices. Sin resplandor: la
           presencia la da el trazo y el aire entre letras, no el brillo. */
        .marca {{
            text-align: center;
            margin: 4px 0 30px;
        }}
        .marca-nombre {{
            font-family: 'Jost', 'Futura', 'Century Gothic', sans-serif;
            font-weight: 300;
            font-size: clamp(1.05rem, 2.9vw, 1.72rem);
            letter-spacing: .215em;
            /* Compensa el espacio que el tracking añade tras la última letra,
               que si no descuadra el centrado. */
            text-indent: .215em;
            text-transform: uppercase;
            color: #f0fbff;
            line-height: 1.25;
            margin: 0 0 16px;
        }}
        .marca-filete {{
            width: 54px;
            height: 1px;
            background: rgba(56,232,255,.5);
            margin: 0 auto 15px;
        }}
        .marca-descriptor {{
            font-family: 'Jost', 'Futura', 'Century Gothic', sans-serif;
            font-weight: 200;
            font-size: .72rem;
            letter-spacing: .44em;
            text-indent: .44em;
            text-transform: uppercase;
            color: rgba(180,235,250,.82);
            margin: 0;
        }}

        /* Los campos y el botón los estiliza styles.py para toda la app; aquí
           solo se ajusta el panel del formulario, que sobre la lluvia lleva
           algo de transparencia y desenfoque para que los puntos se
           insinúen detrás. */
        [data-testid="stForm"] {{
            border: 1px solid rgba(0,229,255,.20) !important;
            border-radius: 12px;
            background: rgba(14,22,38,.72) !important;
            backdrop-filter: blur(4px);
        }}

        /* En una pantalla de acceso, el botón de desplegar solo estorba. */
        [data-testid="stAppDeployButton"] {{ display: none; }}
        </style>
        <div id="lluvia">{puntos}</div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

def usuario_actual() -> dict | None:
    """Devuelve el usuario de la sesión, o None si nadie se ha autenticado."""
    return st.session_state.get("usuario")


def pantalla_login() -> None:
    """Pantalla previa: sin autenticarse no se llega a nada más."""
    _fondo_animado()

    # Columna central más ancha que el formulario para que el nombre de la
    # marca quepa en un solo renglón: partirlo lo haría ver como un salto
    # accidental en vez de un bloque de marca.
    _, centro, _ = st.columns([1, 2, 1])

    with centro:
        # El nombre y el descriptor van como un bloque de marca, no como un
        # título de Streamlit: así se controla la tipografía por completo.
        st.markdown(
            '<div class="marca">'
            '<div class="marca-nombre">Auto Servicio Bautista</div>'
            '<div class="marca-filete"></div>'
            '<div class="marca-descriptor">Gestión del Taller</div>'
            '</div>',
            unsafe_allow_html=True,
        )

        if not db.RUTA_DB.exists():
            st.error(
                "No existe la base de datos. Corre primero el script de carga:\n\n"
                "`.venv\\Scripts\\python.exe cargar_datos.py`"
            )
            return

        intentos = st.session_state.get("intentos_fallidos", 0)
        if intentos >= MAX_INTENTOS:
            st.error(
                f"Demasiados intentos fallidos ({intentos}). "
                "Recarga la página para volver a intentar."
            )
            return

        with st.form("login"):
            usuario = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Entrar", width="stretch")

        if entrar:
            if not usuario or not password:
                st.warning("Escribe tu usuario y tu contraseña.")
                return

            with db.conectar() as conexion:
                datos = auth.autenticar(conexion, usuario, password)

            if datos:
                st.session_state.usuario = datos
                st.session_state.intentos_fallidos = 0
                st.rerun()
            else:
                st.session_state.intentos_fallidos = intentos + 1
                # Mensaje único a propósito: distinguir "no existe el usuario"
                # de "contraseña incorrecta" revelaría qué usuarios existen.
                st.error("Usuario o contraseña incorrectos.")


def cerrar_sesion() -> None:
    """Limpia la sesión por completo."""
    for clave in list(st.session_state.keys()):
        del st.session_state[clave]


def formulario_cambio_password(usuario: dict) -> None:
    """Permite al usuario cambiar su propia contraseña."""
    with st.form("cambiar_password"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        confirmar = st.text_input("Confirmar contraseña nueva", type="password")
        guardar = st.form_submit_button("Cambiar contraseña")

    if not guardar:
        return

    if not all((actual, nueva, confirmar)):
        st.warning("Llena los tres campos.")
    elif nueva != confirmar:
        st.error("La contraseña nueva y su confirmación no coinciden.")
    elif len(nueva) < 8:
        st.error("La contraseña nueva debe tener al menos 8 caracteres.")
    else:
        with db.conectar() as conexion:
            # Se revalida la contraseña actual: tener la sesión abierta no basta
            # para poder cambiarla.
            if auth.autenticar(conexion, usuario["usuario"], actual) is None:
                st.error("La contraseña actual no es correcta.")
                return
            auth.cambiar_password(conexion, usuario["id_usuario"], nueva)
            conexion.commit()
        st.success("Contraseña actualizada.")


def barra_lateral(usuario: dict) -> None:
    """Datos del usuario, cambio de contraseña y cierre de sesión."""
    with st.sidebar:
        st.markdown("### Auto Servicio Bautista")
        st.caption(f"Sesión de **{usuario['usuario']}** · {usuario['rol']}")
        st.divider()

        with st.expander("Cambiar mi contraseña"):
            formulario_cambio_password(usuario)

        if st.button("Cerrar sesión", width="stretch"):
            cerrar_sesion()
            st.rerun()


# ---------------------------------------------------------------------------

def main() -> None:
    # El tema se aplica antes de dibujar nada, para que ninguna vista alcance
    # a renderizarse con los estilos por omisión.
    styles.apply_global_theme()

    usuario = usuario_actual()

    if usuario is None:
        pantalla_login()
        return

    barra_lateral(usuario)

    # `url_path` explícito en cada página: las cuatro funciones se llaman
    # `mostrar`, y sin esto Streamlit infiere la misma URL para todas y falla
    # con "URL pathnames must be unique".
    # Se agrupa en secciones para que el menú siga leyéndose como navegación:
    # el trabajo del día arriba, lo que se consulta en medio, y los ajustes
    # aparte. Una lista plana de siete entradas se vuelve un directorio.
    navegacion = st.navigation({
        "Taller": [
            st.Page(dashboard.mostrar, title="Dashboard", url_path="dashboard",
                    icon=":material/insights:", default=True),
            st.Page(cotizaciones.mostrar, title="Cotizaciones",
                    url_path="cotizaciones", icon=":material/request_quote:"),
            st.Page(crear_nota.mostrar, title="Crear nota",
                    url_path="crear-nota", icon=":material/note_add:"),
            st.Page(notas.mostrar, title="Notas de servicio", url_path="notas",
                    icon=":material/receipt_long:"),
        ],
        "Registro": [
            st.Page(vehiculos.mostrar, title="Vehículos", url_path="vehiculos",
                    icon=":material/directions_car:"),
            st.Page(clientes.mostrar, title="Clientes", url_path="clientes",
                    icon=":material/group:"),
            st.Page(catalogo.mostrar, title="Catálogo", url_path="catalogo",
                    icon=":material/inventory_2:"),
        ],
        "Análisis": [
            st.Page(reportes.mostrar, title="Reportes", url_path="reportes",
                    icon=":material/query_stats:"),
        ],
        "Ajustes": [
            st.Page(configuracion.mostrar, title="Configuración",
                    url_path="configuracion", icon=":material/settings:"),
        ],
    })
    navegacion.run()


main()
