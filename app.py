"""
Aplicación de administración — System KCBA.

Punto de entrada de Streamlit. Se encarga de la autenticación y de la
navegación; toda la lógica de datos vive en db.py y el contenido de cada
pantalla en el paquete `paginas`.

Uso:
    .venv\\Scripts\\streamlit.exe run app.py
"""

from __future__ import annotations

import base64
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st

import arranque
import auth
import config
import db
import migraciones
import styles
from paginas import (aviso_confidencialidad, catalogo, clientes, configuracion, cotizaciones,
                     crear_nota, dashboard, diagnosticos, notas, reportes,
                     vehiculos)

# El monograma del taller, ya revisado al gris claro del tema y recortado al
# ícono. Se genera desde el logo original con `assets/README.md`.
RUTA_LOGO = Path(__file__).resolve().parent / "assets" / "ctm-logo.png"

st.set_page_config(
    page_title="System KCBA",
    page_icon="🔧",
    layout="wide",
    initial_sidebar_state="expanded",
)

# El límite de intentos vive en config.max_intentos() y en la tabla
# `intentos_acceso` (db.py), no aquí: tiene que sobrevivir a que alguien
# recargue la página, y una constante en session_state no lo hace.

# --- Pantalla de acceso: dividida en imagen + panel blanco ---
RUTA_FONDO_ACCESO = Path(__file__).resolve().parent / \
    "assets" / "fondo-login.jpg"


@st.cache_resource
def _fondo_acceso_base64() -> str | None:
    """
    La imagen del panel izquierdo, en base64, leída una sola vez por proceso.

    Va incrustada en el CSS porque Streamlit no sirve archivos sueltos del
    proyecto. Si falta, el panel queda en negro sólido: una imagen ausente no
    puede impedir que alguien inicie sesión.
    """
    if not RUTA_FONDO_ACCESO.is_file():
        return None
    return base64.b64encode(RUTA_FONDO_ACCESO.read_bytes()).decode("ascii")


def _estilo_acceso() -> None:
    """
    Pinta la pantalla de acceso: todo centrado sobre blanco, con la imagen
    de fondo en toda la pantalla pero desvanecida — un velo blanco casi
    opaco al centro, donde van el texto y los campos, que se abre hacia los
    bordes para que la imagen se funda con el fondo en vez de competir con
    el formulario.
    """
    imagen = _fondo_acceso_base64()
    velo = ("radial-gradient(ellipse 60% 70% at 50% 45%, #FFFFFF 0%, "
            "rgba(255,255,255,.92) 45%, rgba(255,255,255,.55) 100%)")
    fondo = (f"{velo}, url('data:image/jpeg;base64,{imagen}') right bottom / "
             f"cover no-repeat, #FFFFFF" if imagen else "#FFFFFF")
    st.markdown(
        f"""
        <style>
        .stApp {{ background: #FFFFFF; }}
        [data-testid="stHeader"] {{ background: transparent; }}
        [data-testid="stAppDeployButton"] {{ display: none; }}

        /* --- Fondo: fijo, detrás de todo, no intercepta clics --- */
        #panel-acceso {{
            position: fixed;
            inset: 0;
            background: {fondo};
            pointer-events: none;
            z-index: 0;
        }}

        /* --- El contenido, centrado y por encima del fondo --- */
        [data-testid="stMainBlockContainer"], .block-container {{
            position: relative;
            z-index: 1;
            max-width: 960px;
            padding: 12vh 1.5rem 4rem;
        }}
        .acceso {{ text-align: center; margin: 0 auto; }}

        .acceso-marca {{
            font-weight: 700;
            font-size: 1.1rem;
            letter-spacing: .01em;
            color: #5F6368;
            margin: 0 0 1rem;
        }}
        .acceso-saludo {{
            font-weight: 800;
            font-size: 1.6rem;
            letter-spacing: -.035em;
            line-height: 1.05;
            color: #111111;
            margin: 0 0 .9rem;
        }}
        /* El saludo del login, tres veces el tamaño normal (1.35rem → ~4rem);
           en pantallas angostas baja solo para no desbordarse. */
        .acceso-saludo.grande {{
            font-size: clamp(2.3rem, 7.5vw, 4.05rem);
        }}
        .acceso-nota {{
            font-size: 1rem;
            color: #5F6368;
            margin: 0 auto 2.2rem;
            max-width: 480px;
        }}

        /* El formulario va sin caja: sobre blanco sólido, los campos solos
           ya se leen como formulario. */
        [data-testid="stForm"] {{
            border: none !important;
            box-shadow: none !important;
            padding: 0 !important;
            background: transparent !important;
            max-width: 400px;
            margin: 0 auto;
        }}
        [data-testid="stAlert"] {{ max-width: 400px; margin: 0 auto; }}

        @media (max-width: 768px) {{
            [data-testid="stMainBlockContainer"], .block-container {{
                padding: 9vh 1.25rem 3rem;
            }}
        }}
        </style>
        <div id="panel-acceso"></div>
        """,
        unsafe_allow_html=True,
    )


def _encabezado_acceso(saludo: str, nota: str, *, grande: bool = False) -> None:
    """Marca, saludo y línea de ayuda de la pantalla de acceso (textos fijos).

    `grande` es para un saludo corto como el del login; uno largo, como el
    del cambio de contraseña, a ese tamaño ocuparía media pantalla.
    """
    clase = "acceso-saludo grande" if grande else "acceso-saludo"
    st.markdown(
        '<div class="acceso">'
        '<div class="acceso-marca">System KCBA: Gestión del Taller</div>'
        f'<div class="{clase}">{saludo}</div>'
        f'<div class="acceso-nota">{nota}</div>'
        '</div>',
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Arranque autónomo
# ---------------------------------------------------------------------------

@st.cache_resource(show_spinner="Preparando la base de datos…")
def _preparar_base() -> arranque.Informe:
    """
    Crea o migra la base y asegura el administrador, una sola vez por
    proceso.

    `st.cache_resource` es la parte que importa aquí: a diferencia de
    `st.cache_data`, su resultado no se guarda por sesión sino por proceso,
    así que aunque cien personas abran la app al mismo tiempo esto corre una
    sola vez y las demás reciben el resultado ya calculado.
    """
    informe = arranque.preparar()
    if informe.admin_creado:
        # A un registro del servidor, nunca a pantalla: esto corre antes de
        # cualquier autenticación, y lo que se pintara en la pantalla de
        # acceso lo vería cualquier visitante. La contraseña en sí nunca
        # llega ni siquiera hasta aquí —queda en el archivo que escribió
        # `arranque.py`—, solo su ruta.
        print(f"Administrador «{informe.admin_creado}» creado. Contraseña "
              f"inicial en: {informe.ruta_clave_inicial}", file=sys.stderr)
    return informe


# ---------------------------------------------------------------------------
# Autenticación
# ---------------------------------------------------------------------------

def usuario_actual() -> dict | None:
    """Devuelve el usuario de la sesión, o None si nadie se ha autenticado."""
    return st.session_state.get("usuario")


def _mensaje_espera(segundos: int) -> str:
    """Texto del aviso de bloqueo, en minutos redondeados hacia arriba."""
    minutos = -(-segundos // 60)  # división hacia arriba, sin importar math
    plural = "un minuto" if minutos == 1 else f"{minutos} minutos"
    return f"Demasiados intentos seguidos. Espera {plural} y vuelve a intentar."


def pantalla_login() -> None:
    """Pantalla previa: sin autenticarse no se llega a nada más."""
    _estilo_acceso()

    with st.container():
        _encabezado_acceso("Bienvenido Administrador",
                           "Ingresa tus credenciales para continuar.",
                           grande=True)

        with st.form("login"):
            usuario = st.text_input("Usuario")
            password = st.text_input("Contraseña", type="password")
            entrar = st.form_submit_button("Entrar", width="stretch")

        if not entrar:
            return

        if not usuario or not password:
            st.warning("Escribe tu usuario y tu contraseña.")
            return

        # El límite se consulta por el nombre tecleado, exista o no: si solo
        # se consultara para usuarios reales, la espera misma delataría
        # cuáles sí existen — lo mismo que el mensaje único de más abajo ya
        # evita. Vive en la base, no en `session_state`, para que recargar la
        # página no lo reinicie.
        espera = db.segundos_de_bloqueo(usuario)
        if espera:
            st.error(_mensaje_espera(espera))
            return

        with db.conectar() as conexion:
            datos = auth.autenticar(conexion, usuario, password)

        if datos:
            db.limpiar_intentos(usuario)
            st.session_state.usuario = datos
            st.rerun()
        else:
            db.registrar_intento_fallido(usuario)
            # Se vuelve a consultar de inmediato: si este intento fue el que
            # cruzó el máximo, hay que avisarlo AHORA, no dejar que la
            # persona lo descubra hasta el siguiente intento (que además
            # gastaría un envío de más contra el límite).
            espera = db.segundos_de_bloqueo(usuario)
            if espera:
                st.error(_mensaje_espera(espera))
            else:
                # Mensaje único a propósito: distinguir "no existe el
                # usuario" de "contraseña incorrecta" revelaría qué usuarios
                # existen.
                st.error("Usuario o contraseña incorrectos.")


def cerrar_sesion() -> None:
    """Limpia la sesión por completo."""
    for clave in list(st.session_state.keys()):
        del st.session_state[clave]


def _sesion_vigente() -> bool:
    """
    Aplica los dos límites de sesión: inactividad y duración absoluta.

    `st.session_state` no expira sola —vive mientras viva la pestaña del
    navegador—, así que sin esto una sesión abierta se queda autenticada
    indefinidamente. El alcance es el que es: cubre "se quedó la pestaña
    abierta" (la tablet del taller, siempre encendida), no robo de
    credenciales — aquí no hay ningún token que alguien pueda robar.

    Streamlit reejecuta el script completo en cada interacción, así que
    refrescar `ultima_actividad` en cada llamada no cuesta una consulta
    aparte: es solo leer y escribir `session_state`.
    """
    ahora = datetime.now(timezone.utc)
    inicio = st.session_state.get("inicio_sesion")
    ultima = st.session_state.get("ultima_actividad")

    if inicio is None or ultima is None:
        # Primera vuelta de esta sesión (login recién hecho): se cuenta a
        # partir de ahora.
        st.session_state.inicio_sesion = ahora
        st.session_state.ultima_actividad = ahora
        return True

    inactiva = ahora - ultima > timedelta(minutes=config.minutos_inactividad())
    vencida = ahora - inicio > timedelta(hours=config.horas_sesion())
    if inactiva or vencida:
        cerrar_sesion()
        return False

    st.session_state.ultima_actividad = ahora
    return True


def pantalla_cambio_obligatorio(usuario: dict) -> None:
    """
    Se interpone entre el login y la navegación cuando la cuenta nace con una
    contraseña que la persona no eligió: la del primer administrador, que
    `arranque.py` generó al azar o que alguien puso a mano en
    TALLER_ADMIN_PASSWORD.

    No se puede saltar apretando atrás ni recargando: mientras
    `debe_cambiar_password` siga en 1 en la base, cada rerun de `main()`
    vuelve a caer aquí en vez de construir la navegación.
    """
    _estilo_acceso()

    with st.container():
        _encabezado_acceso(
            "Elige una contraseña para tu cuenta",
            "Esta cuenta se creó con una contraseña provisional. Antes de "
            "entrar al sistema, ponle una que solo tú conozcas.",
        )

        with st.form("cambio_obligatorio"):
            nueva = st.text_input("Contraseña nueva", type="password")
            confirmar = st.text_input("Confirmar contraseña nueva",
                                      type="password")
            guardar = st.form_submit_button("Guardar y continuar",
                                            width="stretch")

        if not guardar:
            return

        if not nueva or not confirmar:
            st.warning("Llena los dos campos.")
        elif nueva != confirmar:
            st.error("La contraseña nueva y su confirmación no coinciden.")
        elif len(nueva) < 8:
            st.error("La contraseña nueva debe tener al menos 8 caracteres.")
        else:
            with db.conectar() as conexion:
                auth.cambiar_password(conexion, usuario["id_usuario"], nueva)
                conexion.commit()
            # Se actualiza también la copia en sesión, no solo la base: la
            # siguiente interacción (la que sea) vuelve a evaluar esta
            # bandera desde `st.session_state`, y sin esto seguiría leyendo
            # la vieja y regresaría aquí en un ciclo sin salida. No se fuerza
            # un `st.rerun()` —igual que en Configuración → Mi cuenta— para
            # que el mensaje de éxito sí se alcance a ver en vez de
            # desaparecer en la misma vuelta en la que aparece.
            st.session_state.usuario["debe_cambiar_password"] = False
            st.success("Contraseña actualizada. Continúa a la aplicación.")


def barra_lateral(usuario: dict) -> None:
    """Identidad del usuario y cierre de sesión.

    El cambio de contraseña NO vive aquí: está en Configuración → Mi cuenta.
    La barra lateral es para navegar, y un formulario de credenciales metido
    entre los enlaces se pica por error y distrae de lo que se viene a hacer.
    """
    with st.sidebar:
        st.markdown("### System KCBA")
        # El monograma del taller en lugar del renglón de «Sesión de…». Quién
        # tiene la sesión abierta se sigue viendo, pero en Configuración →
        # Mi cuenta, que es donde se hace algo con ese dato.
        if RUTA_LOGO.exists():
            st.image(str(RUTA_LOGO), width=110)
        st.divider()

        if st.button("Cerrar sesión", width="stretch"):
            cerrar_sesion()
            st.rerun()


# ---------------------------------------------------------------------------

def main() -> None:
    # El tema se aplica antes de dibujar nada, para que ninguna vista alcance
    # a renderizarse con los estilos por omisión.
    styles.apply_global_theme()

    try:
        _preparar_base()
    except migraciones.MigracionManual as error:
        # El mensaje trae rutas y nombres de guiones internos: información
        # para quien administra el servidor, no para quien visita esta
        # pantalla sin haberse autenticado. Por eso va al registro y no a
        # `st.error`.
        print(f"Arranque detenido — hace falta un paso manual:\n{error}",
              file=sys.stderr)
        st.error("El sistema no está disponible en este momento. "
                 "Avisa al administrador.")
        return
    except Exception as error:
        print(f"No se pudo preparar la base de datos: {error}",
              file=sys.stderr)
        st.error("El sistema no está disponible en este momento. "
                 "Avisa al administrador.")
        return

    usuario = usuario_actual()

    if usuario is None:
        pantalla_login()
        return

    if usuario.get("debe_cambiar_password"):
        pantalla_cambio_obligatorio(usuario)
        return

    if not _sesion_vigente():
        st.info("Tu sesión venció por inactividad. Vuelve a entrar.")
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
            st.Page(diagnosticos.mostrar, title="Diagnósticos con escáner",
                    url_path="diagnosticos", icon=":material/troubleshoot:"),
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
            st.Page(aviso_confidencialidad.mostrar,
                    title="Aviso de Confidencialidad",
                    url_path="aviso-confidencialidad", icon=":material/lock:"),
        ],
    })
    navegacion.run()


main()
