"""
Arranque autónomo — Servicio Bautista.

Hasta ahora, si la base no existía, la app se limitaba a mostrar en pantalla
el comando de PowerShell para crearla. Eso funciona cuando hay alguien frente
a la computadora del taller; en un servidor no hay nadie ahí para teclearlo.

`preparar()` es lo que llama `app.py` en cada arranque del proceso: deja la
base creada y al día (delegando en `migraciones.py`) y se asegura de que
exista un administrador, generando una contraseña provisional si hace falta.

Este módulo no importa Streamlit —igual que `db.py`, del que depende—, así
que `cargar_datos.py` y las pruebas lo pueden usar sin arrastrar la interfaz.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import auth
import config
import db
import migraciones


@dataclass(frozen=True)
class Informe:
    """Lo que pasó al preparar la base para este arranque del proceso."""

    base_creada: bool
    migraciones: list[str]
    admin_creado: str | None       # nombre del admin, o None si ya existía
    ruta_clave_inicial: Path | None  # dónde quedó la contraseña, o None

    # Deliberadamente NO hay un campo para la contraseña. `pantalla_login()`
    # la pintaría en la primera pantalla que ve cualquier visitante, se haya
    # autenticado o no.


def asegurar_admin(conexion: sqlite3.Connection) -> tuple[str, str] | None:
    """
    Crea el usuario administrador inicial si todavía no hay ninguno.

    Devuelve `(usuario, password)` si lo creó, o `None` si ya existía otro.
    La contraseña sale de `TALLER_ADMIN_PASSWORD` si está definida; si no, se
    genera al azar.

    Quién hace qué con esa contraseña lo decide quien llama: en la terminal
    de `cargar_datos.py` alguien la está mirando y es correcto imprimirla; en
    el arranque de un servidor, `preparar()` la escribe a un archivo en vez
    de dejarla pasar por ningún registro.

    El admin nace SIEMPRE con `debe_cambiar_password = 1`, incluso cuando la
    contraseña vino de una variable de entorno puesta a propósito: es un
    seguro barato —a lo más, un cambio de contraseña extra en el primer
    login— contra que esa variable haya quedado escrita en algún archivo de
    configuración que sobrevive más de lo que debería.
    """
    existen = conexion.execute("SELECT COUNT(*) AS n FROM usuarios").fetchone()["n"]
    if existen:
        return None
    usuario = config.admin_usuario()
    password = config.admin_password() or auth.generar_password()
    auth.crear_usuario(conexion, usuario, password, rol="admin",
                       debe_cambiar_password=True)
    return usuario, password


def _escribir_clave_inicial(carpeta: Path, usuario: str, password: str) -> Path:
    """
    Deja la contraseña en un archivo dentro de la carpeta de la base, con
    permisos restringidos, y devuelve su ruta.

    Es el único lugar del arranque autónomo donde la contraseña en claro
    toca algo persistente. `chmod` no existe de verdad en Windows —el intento
    se ignora ahí—, pero en el servidor Linux para el que existe esta función
    sí importa: cualquier otra cuenta del sistema no debe poder leerlo.
    """
    ruta = carpeta / "primera-clave.txt"
    ruta.write_text(
        f"usuario    : {usuario}\n"
        f"contraseña : {password}\n\n"
        f"Provisional: la app pedirá cambiarla en el primer inicio de "
        f"sesión. Este archivo se puede borrar después.\n",
        encoding="utf-8",
    )
    try:
        ruta.chmod(0o600)
    except OSError:
        pass  # Windows: no es un error, simplemente no aplica.
    return ruta


def preparar(ruta: Path | None = None) -> Informe:
    """
    Deja la base lista para atender peticiones.

    La crea o la migra si hace falta (`migraciones.preparar`) y asegura que
    exista un administrador. Es idempotente: en arranques posteriores no
    vuelve a crear nada, solo lo confirma.

    Pensada para llamarse una vez por proceso —`app.py` la envuelve en
    `st.cache_resource` con ese propósito—, pero también es segura si dos
    procesos la corren al mismo tiempo: `usuarios.usuario` es UNIQUE, así que
    el que pierde la carrera por crear al admin recibe `IntegrityError` en
    vez de un usuario duplicado, y aquí se trata como "ya lo tiene alguien
    más", no como una falla.
    """
    ruta = ruta or db.RUTA_DB
    existia = ruta.exists() and ruta.stat().st_size > 0

    hechos = migraciones.preparar(ruta)

    credenciales = None
    try:
        with db.transaccion(ruta) as conexion:
            credenciales = asegurar_admin(conexion)
    except sqlite3.IntegrityError:
        credenciales = None

    admin_creado = None
    ruta_clave = None
    if credenciales:
        admin_creado, password = credenciales
        if config.admin_password() is None:
            ruta_clave = _escribir_clave_inicial(ruta.parent, admin_creado,
                                                  password)

    return Informe(base_creada=not existia, migraciones=hechos,
                   admin_creado=admin_creado, ruta_clave_inicial=ruta_clave)
