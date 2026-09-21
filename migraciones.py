"""
Versionado del esquema — Servicio Bautista.

Hasta ahora la versión del esquema era una convención de nombres de archivo en
`historico/`: para saber si una base estaba al día había que abrirla y mirar si
tal tabla existía. Eso funcionaba cuando la única base del mundo era la de una
computadora que alguien tenía enfrente. Con la app corriendo en un servidor,
alguien tiene que poder preguntar «¿en qué versión está esta base?» y obtener
una respuesta sin adivinar.

`PRAGMA user_version` es donde SQLite guarda ese número: cuatro bytes en el
encabezado del archivo, que sobreviven a `VACUUM`, no aparecen en los volcados
de `exportar.py` ni en `PRAGMA foreign_key_check`, y no requieren crear ninguna
tabla para empezar a usarlos.

Sobre las migraciones históricas (v2 a v8): NO se automatizan, a propósito.
Solo existió una base a la que pudieran aplicarse — la del taller — y ya pasó
por todas. Una base nueva nace directamente en la forma final desde
`esquema.sql`, así que jamás las necesita. Automatizar reconstrucciones de
tablas que nunca se volverán a ejecutar sería riesgo sin beneficio. Aquí se
declaran únicamente sus CENTINELAS: lo que hay que mirar en una base para
deducir hasta dónde llegó. Si alguna vez apareciera una base atrasada de
verdad, el programa se detiene y dice qué guion de `historico/` correr.

De v9 en adelante sí se automatizan, porque ahí sí puede haber varias bases
(la del taller y la del servidor) que haya que poner al día sin que nadie entre
por SSH.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import db

# Versión en la que `esquema.sql` deja una base recién creada. Subir este número
# exige agregar su `Paso` correspondiente en PASOS y su equivalente en
# `esquema.sql`, para que una base nueva y una migrada acaben idénticas.
VERSION_OBJETIVO = 9


class MigracionManual(RuntimeError):
    """La base está atrasada en un punto que no se puede resolver sola."""


@dataclass(frozen=True)
class Paso:
    """Un escalón de versión del esquema."""

    version: int
    descripcion: str
    # ¿Esta base ya tiene lo que este paso agrega?
    centinela: Callable[[sqlite3.Connection], bool]
    # Cómo aplicarlo. `None` = solo a mano, con el guion de `historico/`.
    aplicar: Callable[[sqlite3.Connection], None] | None = None
    guion: str = ""


# ---------------------------------------------------------------------------
# Centinelas
# ---------------------------------------------------------------------------

def _tabla(conexion: sqlite3.Connection, nombre: str) -> bool:
    return conexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (nombre,)).fetchone() is not None


def _indice(conexion: sqlite3.Connection, nombre: str) -> bool:
    return conexion.execute(
        "SELECT 1 FROM sqlite_master WHERE type='index' AND name=?",
        (nombre,)).fetchone() is not None


def _columna(conexion: sqlite3.Connection, tabla: str, columna: str) -> bool:
    if not _tabla(conexion, tabla):
        return False
    # `PRAGMA table_info` no acepta parámetros, pero `tabla` nunca viene de
    # fuera: son los nombres fijos escritos en PASOS, unas líneas más abajo.
    filas = conexion.execute(f"PRAGMA table_info({tabla})").fetchall()
    return any(f["name"] == columna for f in filas)


# A diferencia de v2-v8, que solo existieron para una base que ya pasó por
# todas, esta sí se automatiza: en un servidor puede haber varias bases
# (la del taller, la de pruebas, la de un despliegue nuevo) que hay que poner
# al día sin que nadie entre a mano.
_ESQUEMA_V9 = """
ALTER TABLE usuarios ADD COLUMN debe_cambiar_password INTEGER NOT NULL
    DEFAULT 0 CHECK (debe_cambiar_password IN (0, 1));

CREATE TABLE IF NOT EXISTS intentos_acceso (
    usuario         TEXT PRIMARY KEY,
    fallidos        INTEGER NOT NULL DEFAULT 0,
    ultimo_intento  TEXT NOT NULL,
    bloqueado_hasta TEXT
);
"""


def _aplicar_v9(conexion: sqlite3.Connection) -> None:
    conexion.executescript(_ESQUEMA_V9)


PASOS: tuple[Paso, ...] = (
    Paso(1, "Esquema original: clientes, notas y partidas",
         lambda c: _tabla(c, "notas")),
    Paso(2, "El vehículo sale de la nota a su propia tabla, y tabla `taller`",
         lambda c: _tabla(c, "vehiculos") and _tabla(c, "taller"),
         guion="migrar.py"),
    Paso(3, "Dueño opcional del vehículo y notas por partida",
         lambda c: _columna(c, "partidas", "notas"),
         guion="migrar_v3.py"),
    Paso(4, "Catálogo de productos",
         lambda c: _tabla(c, "productos"),
         guion="migrar_v4.py"),
    Paso(5, "IVA desglosado y membrete del taller",
         lambda c: _columna(c, "notas", "tasa_iva"),
         guion="migrar_v5.py"),
    Paso(6, "Cotizaciones",
         lambda c: _tabla(c, "cotizaciones"),
         guion="migrar_v6.py"),
    Paso(7, "Diagnósticos con escáner",
         lambda c: _tabla(c, "diagnosticos"),
         guion="migrar_v7.py"),
    Paso(8, "Candados contra clientes y vehículos duplicados",
         lambda c: _indice(c, "idx_clientes_unico"),
         guion="migrar_v8.py"),
    Paso(9, "Cambio de contraseña obligatorio y límite de acceso persistido",
         lambda c: _columna(c, "usuarios", "debe_cambiar_password"),
         aplicar=_aplicar_v9),
)


# ---------------------------------------------------------------------------
# Lectura y escritura de la versión
# ---------------------------------------------------------------------------

def version_actual(conexion: sqlite3.Connection) -> int:
    """Lo que dice `PRAGMA user_version`. Cero = nunca se selló."""
    return int(conexion.execute("PRAGMA user_version").fetchone()[0])


def version_detectada(conexion: sqlite3.Connection) -> int:
    """
    Deduce la versión mirando la forma de la base, para las que nunca se
    sellaron (todas las anteriores a este módulo).

    Se avanza mientras cada centinela diga que sí y se para en el primero que
    falle: una base a la que le falta el paso 5 está en la versión 4, aunque
    por lo que sea ya tenga algo del 6.
    """
    version = 0
    for paso in PASOS:
        if not paso.centinela(conexion):
            break
        version = paso.version
    return version


def sellar(conexion: sqlite3.Connection, version: int) -> None:
    """
    Escribe la versión en el encabezado del archivo.

    `PRAGMA user_version = ?` no admite parámetros —es de las pocas sentencias
    de SQLite que no—, así que este es el único SQL del proyecto armado con
    f-string. Por eso el valor se fuerza a entero justo antes: no es un dato de
    usuario, pero la regla de no concatenar SQL merece una excepción explicada
    en vez de una excepción silenciosa.
    """
    conexion.execute(f"PRAGMA user_version = {int(version)}")


def pendientes(conexion: sqlite3.Connection) -> list[Paso]:
    """Pasos que le faltan a esta base para llegar a VERSION_OBJETIVO."""
    desde = version_actual(conexion) or version_detectada(conexion)
    return [p for p in PASOS if desde < p.version <= VERSION_OBJETIVO]


# ---------------------------------------------------------------------------
# Puesta al día
# ---------------------------------------------------------------------------

def preparar(ruta: Path | None = None) -> list[str]:
    """
    Deja la base lista para usarse y devuelve lo que hizo, en texto.

    Cubre los tres casos que se dan en la vida real:

      * No existe todavía —un servidor recién levantado—: se crea desde
        `esquema.sql`, que ya produce la forma final, y se sella en
        VERSION_OBJETIVO sin correr ninguna migración.
      * Existe y está al día pero nunca se selló —la base del taller—: se le
        escribe la versión que se deduce de su forma y no se toca nada más.
      * Existe y está atrasada: se aplican los pasos que falten, o se aborta
        con instrucciones si alguno es de los que solo se corren a mano.

    Es idempotente: llamarla dos veces seguidas no hace nada la segunda vez.
    """
    ruta = ruta or db.RUTA_DB
    hechos: list[str] = []

    nueva = not ruta.exists() or ruta.stat().st_size == 0
    if nueva:
        db.inicializar_esquema(ruta)
        with db.conectar(ruta) as conexion:
            sellar(conexion, VERSION_OBJETIVO)
            conexion.commit()
        return [f"Base creada desde esquema.sql en la versión {VERSION_OBJETIVO}"]

    with db.conectar(ruta) as conexion:
        # Una base que existe pero está vacía por dentro cuenta como nueva:
        # pasa cuando algo la creó y murió antes de escribir el esquema.
        if not _tabla(conexion, "notas"):
            db.inicializar_esquema(ruta)
            sellar(conexion, VERSION_OBJETIVO)
            conexion.commit()
            return [f"Base vacía completada en la versión {VERSION_OBJETIVO}"]

        sellada = version_actual(conexion)
        if sellada == 0:
            sellada = version_detectada(conexion)
            sellar(conexion, sellada)
            conexion.commit()
            hechos.append(f"Versión deducida de la forma de la base: {sellada}")

        faltan = [p for p in PASOS if sellada < p.version <= VERSION_OBJETIVO]
        if not faltan:
            return hechos

        manuales = [p for p in faltan if p.aplicar is None]
        if manuales:
            detalle = "\n".join(
                f"  v{p.version}: {p.descripcion} → historico/{p.guion}"
                for p in manuales)
            raise MigracionManual(
                f"La base está en la versión {sellada} y le faltan pasos que no "
                f"se aplican solos:\n{detalle}\n"
                f"Corre esos guiones a mano (mira historico/LEEME.md) y vuelve "
                f"a arrancar.")

        for paso in faltan:
            # `BEGIN IMMEDIATE` toma el candado de escritura desde el principio:
            # si dos procesos arrancan a la vez, el segundo espera en vez de
            # descubrir a la mitad que otro ya está migrando.
            conexion.execute("BEGIN IMMEDIATE")
            try:
                if not paso.centinela(conexion):
                    paso.aplicar(conexion)  # type: ignore[misc]
                sellar(conexion, paso.version)
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
            hechos.append(f"Aplicado v{paso.version}: {paso.descripcion}")

    return hechos
