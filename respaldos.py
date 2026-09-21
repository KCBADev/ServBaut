"""
Respaldos automáticos de la base — Servicio Bautista.

El respaldo manual de la pantalla de Configuración depende de que alguien se
acuerde de darle clic, y se queda en el mismo disco que la base: si falla la
máquina, se pierden los dos. Este script es la otra mitad: pensado para
correr por su cuenta —un cron, un systemd timer, una tarea programada—, NUNCA
desde un hilo dentro del proceso de Streamlit, porque los reruns y reinicios
de Streamlit lo volverían impredecible.

Lo que SÍ hace: crea un respaldo comprimido con marca de tiempo, lo verifica
abriéndolo de verdad (íntegro y con los totales cuadrados — un respaldo que
nunca se restauró es una hipótesis, no un respaldo), y rota los viejos.

Lo que NO hace: sacarlo de esta máquina. Eso es trabajo de una herramienta
aparte (`rclone` a Drive/OneDrive/B2 es la sugerida) que se corre después,
sobre la carpeta que este script deja lista — normalmente en la misma tarea
programada, como un segundo paso.

Uso:
    .venv\\Scripts\\python.exe respaldos.py
    .venv\\Scripts\\python.exe respaldos.py --carpeta D:\\Respaldos --diarios 7 --semanales 4
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import config
import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# El nombre codifica la fecha: `rotar()` la lee de ahí en vez de fiarse de la
# fecha de modificación del archivo, que no sobrevive una copia con
# cualquier herramienta que no la preserve a propósito.
PATRON_NOMBRE = "taller-%Y%m%d-%H%M%S.db.gz"


def crear(carpeta: Path | None = None, ruta: Path | None = None) -> Path:
    """
    Crea un respaldo comprimido con marca de tiempo y devuelve su ruta.

    Pasa por un archivo temporal sin comprimir —lo que produce
    `db.respaldar()`, una copia consistente vía `Connection.backup()`— y lo
    comprime después: gzip no sabe escribir directo desde ahí.
    """
    carpeta = carpeta or config.ruta_respaldos()
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / datetime.now().strftime(PATRON_NOMBRE)

    with tempfile.TemporaryDirectory() as temporal:
        sin_comprimir = Path(temporal) / "taller.db"
        db.respaldar(sin_comprimir, ruta)
        with open(sin_comprimir, "rb") as origen, \
             gzip.open(destino, "wb") as salida:
            shutil.copyfileobj(origen, salida)

    return destino


def verificar(respaldo: Path) -> bool:
    """
    Descomprime un respaldo a un temporal y comprueba que sea de fiar: que
    SQLite lo lea sin corrupción y que los totales de notas y partidas
    cuadren, igual que se exige de la base en vivo.

    Cualquier tropiezo al descomprimir o leer el archivo —un gzip corrupto,
    algo que en realidad no es un respaldo— cuenta como "no confiable" y da
    `False`, en vez de tronar: la respuesta de esta función es siempre una de
    dos, nunca una excepción a medio camino.
    """
    try:
        with tempfile.TemporaryDirectory() as temporal:
            descomprimido = Path(temporal) / "taller.db"
            with gzip.open(respaldo, "rb") as origen, \
                 open(descomprimido, "wb") as salida:
                shutil.copyfileobj(origen, salida)

            conexion = sqlite3.connect(descomprimido)
            try:
                integro = conexion.execute(
                    "PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                conexion.close()

            cuadre = db.verificar_cuadre(descomprimido)

        return (integro and cuadre["coinciden"]
                and not cuadre["notas_descuadradas"])
    except Exception:
        return False


def _fecha_de_nombre(ruta: Path) -> datetime | None:
    """La fecha codificada en el nombre, o None si no sigue el patrón
    esperado (un archivo que alguien dejó ahí a mano, por ejemplo)."""
    try:
        return datetime.strptime(ruta.name, PATRON_NOMBRE)
    except ValueError:
        return None


def rotar(carpeta: Path, diarios: int = 7, semanales: int = 4) -> list[Path]:
    """
    Conserva los `diarios` respaldos más recientes completos, y de los más
    viejos que esos, uno por semana calendario hasta `semanales`. Borra el
    resto y devuelve lo que borró.

    Un esquema "abuelo" sencillo: cobertura fina de los últimos días y
    cobertura gruesa de las últimas semanas, sin acumular para siempre.
    Los archivos que no siguen el patrón de nombre esperado no se tocan.
    """
    todos = sorted(carpeta.glob("taller-*.db.gz"), reverse=True)
    respaldos = [r for r in todos if _fecha_de_nombre(r) is not None]

    conservar = set(respaldos[:diarios])

    semanas_vistas: set[tuple[int, int]] = set()
    for r in respaldos[diarios:]:
        semana = _fecha_de_nombre(r).isocalendar()[:2]  # (año ISO, semana ISO)
        if semana not in semanas_vistas and len(semanas_vistas) < semanales:
            semanas_vistas.add(semana)
            conservar.add(r)

    borrados = [r for r in respaldos if r not in conservar]
    for r in borrados:
        r.unlink()
    return borrados


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Crea, verifica y rota respaldos comprimidos de la base.")
    parser.add_argument(
        "--carpeta", type=Path, default=None,
        help="Dónde guardar los respaldos (por omisión, la carpeta de "
             "TALLER_RESPALDOS o la que resuelva config.ruta_respaldos()).")
    parser.add_argument("--diarios", type=int, default=7)
    parser.add_argument("--semanales", type=int, default=4)
    parser.add_argument(
        "--sin-verificar", action="store_true",
        help="No abre el respaldo recién creado para comprobarlo. Más "
             "rápido, pero se pierde la única garantía real de que sirve.")
    args = parser.parse_args()

    carpeta = args.carpeta or config.ruta_respaldos()

    print("=" * 66)
    print("RESPALDO — Servicio Bautista")
    print("=" * 66)

    respaldo = crear(carpeta)
    print(f"\nCreado: {respaldo.name} "
          f"({respaldo.stat().st_size / 1024:,.0f} KB)")

    if not args.sin_verificar:
        print("Verificando...")
        integro = verificar(respaldo)
        print("  íntegro y cuadra" if integro else "  [!!] NO PASÓ LA VERIFICACIÓN")
        if not integro:
            print("\nEl respaldo quedó escrito pero no es de fiar. No se "
                  "rota nada: revísalo antes de confiar en cualquier otro.")
            sys.exit(1)

    borrados = rotar(carpeta, args.diarios, args.semanales)
    if borrados:
        print(f"\nRotación: se borraron {len(borrados)} respaldo(s) antiguos.")
    vivos = sorted(carpeta.glob("taller-*.db.gz"))
    print(f"Quedan {len(vivos)} respaldo(s) en {carpeta}.")
    print("=" * 66)


if __name__ == "__main__":
    main()
