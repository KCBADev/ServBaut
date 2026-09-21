"""
Chequeo de salud para el `HEALTHCHECK` de Docker — Servicio Bautista.

Streamlit expone `/_stcore/health` y responde `ok` cuando está listo para
atender peticiones. Se hace con un script de Python en vez de `curl`/`wget`
porque esta imagen garantiza Python (es lo que la hace ser esta imagen);
no garantiza ningún cliente HTTP de línea de comandos en particular.
"""

import os
import sys
import urllib.request

# Mismo orden que docker/entrada.sh: PORT (lo que inyecta el hosting) antes
# que STREAMLIT_SERVER_PORT. Es deliberado y no un descuido: `entrada.sh`
# calcula el puerto final y lo exporta solo dentro de SU propio árbol de
# procesos (el que hereda `exec streamlit run app.py`), y ese cálculo nunca
# llega al entorno que ve `HEALTHCHECK` —que Docker arranca aparte, como un
# `docker exec`, con el entorno del CONTENEDOR, no el de ese proceso en
# particular—. Repetir aquí la misma prioridad, leyendo PORT directo, es lo
# que hace que ambos acuerden el mismo puerto sin depender de ese cálculo.
puerto = os.environ.get("PORT") or os.environ.get("STREAMLIT_SERVER_PORT", "8501")
url = f"http://127.0.0.1:{puerto}/_stcore/health"

try:
    with urllib.request.urlopen(url, timeout=4) as respuesta:
        sys.exit(0 if respuesta.read() == b"ok" else 1)
except Exception:
    # Cualquier tropiezo (el servidor no responde, se cayó la conexión,
    # timeout) cuenta como "no saludable": es justo lo que Docker necesita
    # saber, no el detalle de por qué.
    sys.exit(1)
