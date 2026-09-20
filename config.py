"""
Configuración por entorno — Servicio Bautista.

Único lugar donde el programa averigua *dónde* están las cosas y *cómo* debe
comportarse en la máquina donde le tocó correr. Todo sale de variables de
entorno con un valor por omisión razonable, para que nadie tenga que editar
código para mover la base de datos o cambiar un límite.

Por qué variables de entorno y no `st.secrets`:
`db.py` no puede importar Streamlit (la capa de datos es independiente de la
interfaz, y de eso dependen `cargar_datos.py`, `restablecer_clave.py`, los
guiones de `historico/` y los de `analisis/`, que corren desde la terminal).
`os.environ` es lo único que funciona igual dentro y fuera de Streamlit. Si
algún día la app corre en un servicio que solo sabe de `secrets.toml`, ese
archivo se usaría para *inyectar* estas variables, no para reemplazarlas.

Este módulo solo usa la biblioteca estándar, a propósito: lo importa `db.py`,
que es lo primero que carga todo lo demás.
"""

from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent

# La ruta con la que nació el proyecto, cuando era una sola computadora con
# Windows. La base se puso en D: porque C: se quedó sin espacio y una escritura
# falló a media nota.
#
# Se conserva como penúltimo recurso para que esa computadora siga arrancando
# exactamente igual que siempre, sin definir una sola variable de entorno: si
# la carpeta existe, se usa. En cualquier otra máquina ni siquiera se consulta.
RUTA_HEREDADA = Path(r"D:\TallerBautista\taller.db")

# Carpeta por omisión cuando no hay nada configurado y tampoco existe la ruta
# heredada: dentro del proyecto, que siempre existe. No es lo ideal (mezcla
# datos con código), pero es un último recurso que arranca en vez de fallar.
RUTA_ULTIMO_RECURSO = RAIZ / "datos" / "taller.db"


# ---------------------------------------------------------------------------
# Lectura de variables de entorno
# ---------------------------------------------------------------------------
# Los tres ayudantes tratan la cadena vacía igual que la ausencia de la
# variable. Es deliberado: en Docker y en los servicios de despliegue es muy
# común acabar con `TALLER_DB=` sin valor, y tomar eso como una ruta vacía
# daría un error incomprensible muy lejos de aquí.

def texto(nombre: str, omision: str = "") -> str:
    """Devuelve la variable como texto ya recortado, o `omision` si no está."""
    valor = os.environ.get(nombre, "").strip()
    return valor or omision


def entero(nombre: str, omision: int) -> int:
    """
    Devuelve la variable como entero, o `omision` si no está o no es un número.

    Un valor mal escrito cae al valor por omisión en vez de tumbar el arranque:
    que alguien teclee `TALLER_MAX_INTENTOS=cinco` no debe dejar al taller sin
    sistema, y el valor por omisión siempre es seguro.
    """
    valor = texto(nombre)
    if not valor:
        return omision
    try:
        return int(valor)
    except ValueError:
        return omision


def booleano(nombre: str, omision: bool) -> bool:
    """Interpreta la variable como sí/no. Acepta español e inglés."""
    valor = texto(nombre).lower()
    if not valor:
        return omision
    if valor in ("1", "si", "sí", "true", "yes", "on"):
        return True
    if valor in ("0", "no", "false", "off"):
        return False
    return omision


# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------

def ruta_db() -> Path:
    """
    Dónde vive `taller.db`, en orden de preferencia:

      1. `TALLER_DB` — ruta completa al archivo. Es la que usa el contenedor.
      2. `TALLER_DATOS` — carpeta; el archivo se llama `taller.db` dentro.
      3. La ruta heredada de D:, **solo en Windows y solo si su carpeta ya
         existe**. Esto es lo que hace que la computadora del taller siga
         funcionando sin configurar nada.
      4. `datos/taller.db` dentro del proyecto.

    El paso 3 se limita a Windows por una razón que muerde en silencio: en
    Linux, `Path(r"D:\\TallerBautista\\taller.db")` no es una ruta absoluta con
    letra de unidad sino un nombre de archivo suelto con barras invertidas
    dentro, y su `.parent` es el directorio actual — que siempre existe. Sin la
    comprobación de sistema operativo, el servidor escogería la ruta heredada
    creyendo que la encontró.
    """
    explicita = texto("TALLER_DB")
    if explicita:
        return Path(explicita).expanduser()

    carpeta = texto("TALLER_DATOS")
    if carpeta:
        return Path(carpeta).expanduser() / "taller.db"

    if os.name == "nt" and RUTA_HEREDADA.parent.is_dir():
        return RUTA_HEREDADA

    return RUTA_ULTIMO_RECURSO


def ruta_respaldos() -> Path:
    """
    Carpeta donde se dejan los respaldos automáticos.

    Por omisión, `respaldos/` junto a la base. Van al mismo disco a propósito:
    esta carpeta es la copia *local* y de acceso rápido. La copia que de verdad
    protege contra que se pierda la máquina entera es la que `respaldos.py`
    sube fuera del servidor.
    """
    carpeta = texto("TALLER_RESPALDOS")
    if carpeta:
        return Path(carpeta).expanduser()
    return ruta_db().parent / "respaldos"


def ruta_temporal() -> Path | None:
    """
    Carpeta para archivos temporales, o `None` para usar la del sistema.

    `None` es lo correcto en casi todos lados. La variable existe porque una
    base SQLite temporal necesita espacio real, y en alguna máquina el disco
    del sistema puede andar más justo que el disco de datos.
    """
    carpeta = texto("TALLER_TMP")
    return Path(carpeta).expanduser() if carpeta else None


# ---------------------------------------------------------------------------
# Sesión y acceso
# ---------------------------------------------------------------------------

def minutos_inactividad() -> int:
    """Minutos sin tocar nada antes de cerrar la sesión sola."""
    return entero("TALLER_MINUTOS_INACTIVIDAD", 60)


def horas_sesion() -> int:
    """
    Duración máxima de una sesión aunque se esté usando.

    Existe para que una tablet que se queda encendida en el taller no siga
    autenticada indefinidamente.
    """
    return entero("TALLER_HORAS_SESION", 12)


def max_intentos() -> int:
    """Intentos fallidos antes de que empiece la espera entre intentos."""
    return entero("TALLER_MAX_INTENTOS", 5)


# ---------------------------------------------------------------------------
# Primer arranque
# ---------------------------------------------------------------------------

def admin_usuario() -> str:
    """Nombre del administrador que se crea si la base no tiene ninguno."""
    return texto("TALLER_ADMIN_USUARIO", "admin")


def admin_password() -> str | None:
    """
    Contraseña inicial del administrador, o `None` si no se proporcionó.

    Cuando es `None`, `arranque.py` genera una al azar y la escribe en un
    archivo con permisos restringidos, porque en un servidor no hay nadie
    mirando la terminal para copiarla.
    """
    return texto("TALLER_ADMIN_PASSWORD") or None
