"""
Autenticación — Servicio Bautista.

Las contraseñas se guardan como PBKDF2-HMAC-SHA256 con un salt único por
usuario. Nunca en texto plano y nunca reversibles.

Se usa `hashlib.pbkdf2_hmac` de la librería estándar en lugar de bcrypt: no
requiere compilar nada en Windows y, con un número de iteraciones alto, es
igual de sólido para este caso.
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3

# Recomendación vigente de OWASP para PBKDF2-HMAC-SHA256. Se guarda por fila
# en la base para poder subirlo en el futuro sin invalidar las contraseñas ya
# creadas: cada una se verifica con las iteraciones con las que se generó.
ITERACIONES = 600_000
ALGORITMO = "sha256"


def _derivar(password: str, salt: bytes, iteraciones: int) -> str:
    """Deriva la contraseña y devuelve el resultado en hexadecimal."""
    return hashlib.pbkdf2_hmac(
        ALGORITMO, password.encode("utf-8"), salt, iteraciones
    ).hex()


def hashear_password(password: str) -> tuple[str, str, int]:
    """
    Genera (hash, salt, iteraciones) para una contraseña nueva.

    El salt es aleatorio y distinto para cada usuario: impide que dos usuarios
    con la misma contraseña tengan el mismo hash.
    """
    salt = secrets.token_bytes(16)
    return _derivar(password, salt, ITERACIONES), salt.hex(), ITERACIONES


def verificar_password(password: str, hash_guardado: str, salt_hex: str,
                       iteraciones: int) -> bool:
    """Comprueba una contraseña contra el hash guardado."""
    calculado = _derivar(password, bytes.fromhex(salt_hex), iteraciones)
    # Comparación en tiempo constante: no filtra información por el tiempo
    # que tarda en fallar.
    return secrets.compare_digest(calculado, hash_guardado)


def generar_password(longitud: int = 14) -> str:
    """Genera una contraseña aleatoria legible para el administrador inicial."""
    # Sin caracteres ambiguos (l/1/I, O/0) para que se pueda teclear sin dudas.
    alfabeto = "abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alfabeto) for _ in range(longitud))


def crear_usuario(conexion: sqlite3.Connection, usuario: str, password: str,
                  rol: str = "operador") -> int:
    """Inserta un usuario nuevo y devuelve su id."""
    hash_password, salt, iteraciones = hashear_password(password)
    cursor = conexion.execute(
        """
        INSERT INTO usuarios (usuario, hash_password, salt, iteraciones, rol)
        VALUES (?, ?, ?, ?, ?)
        """,
        (usuario.strip(), hash_password, salt, iteraciones, rol),
    )
    return int(cursor.lastrowid)


def autenticar(conexion: sqlite3.Connection, usuario: str,
               password: str) -> dict | None:
    """
    Valida las credenciales. Devuelve los datos del usuario o None.

    No distingue entre "usuario no existe" y "contraseña incorrecta": el
    mensaje de error de la app debe ser el mismo en ambos casos para no
    revelar qué usuarios existen.
    """
    fila = conexion.execute(
        """
        SELECT id_usuario, usuario, hash_password, salt, iteraciones, rol, activo
          FROM usuarios
         WHERE usuario = ?
        """,
        (usuario.strip(),),
    ).fetchone()

    if fila is None or not fila["activo"]:
        return None
    if not verificar_password(password, fila["hash_password"],
                              fila["salt"], fila["iteraciones"]):
        return None

    conexion.execute(
        "UPDATE usuarios SET ultimo_acceso = datetime('now') WHERE id_usuario = ?",
        (fila["id_usuario"],),
    )
    conexion.commit()

    return {
        "id_usuario": fila["id_usuario"],
        "usuario": fila["usuario"],
        "rol": fila["rol"],
    }


def cambiar_password(conexion: sqlite3.Connection, id_usuario: int,
                     password_nueva: str) -> None:
    """Reemplaza la contraseña de un usuario (genera salt nuevo)."""
    hash_password, salt, iteraciones = hashear_password(password_nueva)
    conexion.execute(
        """
        UPDATE usuarios
           SET hash_password = ?, salt = ?, iteraciones = ?
         WHERE id_usuario = ?
        """,
        (hash_password, salt, iteraciones, id_usuario),
    )
