# Servicio Bautista — imagen de producción.
#
# Base: la imagen oficial de Playwright con Python, que ya trae Chromium y
# TODAS sus librerías de sistema (libnss3, libatk-bridge2.0-0, libdrm2, ...)
# preinstaladas. El paso que se rompe en una imagen `python:3.12-slim` normal
# es justo `playwright install --with-deps`: mete ~400 MB de apt y falla
# distinto según la semana, sobre todo en ARM64. Aquí no hace falta ese paso.
#
# El tag fija la MISMA versión de Playwright que `requirements.txt`
# (1.62.0): si algún día se sube una, hay que subir la otra a la vez, o
# `playwright install` (que este Dockerfile no corre) y el navegador ya
# instalado en la imagen quedarían desalineados.
FROM mcr.microsoft.com/playwright/python:v1.62.0-noble

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Las dependencias en su propia capa: cambiar una línea del código de la app
# no debe forzar a reinstalar pandas/streamlit/playwright, que son la parte
# lenta del build.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Se asegura el permiso de ejecución sin importar cómo haya llegado el
# archivo al contexto de build (un checkout en Windows no preserva el bit
# ejecutable de POSIX de forma confiable, tenga o no la marca correcta en
# git). Sin esto, `ENTRYPOINT` fallaría con "permission denied" al arrancar.
RUN chmod +x docker/entrada.sh

# Dónde vive todo lo que no es código: la base, sus respaldos locales, y —si
# hiciera falta generarla— la contraseña del primer arranque. Aparte del
# árbol de la aplicación, para poder reconstruir la imagen sin arrastrar
# datos y para que el volumen sobreviva a reconstruirla.
ENV TALLER_DB=/datos/taller.db \
    TALLER_RESPALDOS=/datos/respaldos

# La imagen de Playwright ya trae un usuario sin privilegios (`pwuser`): se
# reutiliza en vez de crear uno propio. Solo hace falta darle la carpeta de
# datos, que por ahora no existe.
RUN mkdir -p /datos && chown -R pwuser:pwuser /datos /app
USER pwuser

EXPOSE 8501

# `/_stcore/health` es el endpoint que el propio Streamlit expone para esto;
# `docker/healthcheck.py` solo lo consulta. `start-period` generoso porque el
# primer arranque además prepara la base (`arranque.py`) antes de poder
# responder — crear el esquema y sellar la versión toma un instante, pero
# conviene no fallar el healthcheck por eso en un disco lento.
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "/app/docker/healthcheck.py"]

# Traduce $PORT (lo que inyectan Render, Fly, Cloud Run...) a la variable
# que Streamlit sí entiende, y de ahí arranca la app. Ver docker/entrada.sh.
# Ruta absoluta, no relativa a WORKDIR: así sigue resolviendo bien aunque
# algún día cambie dónde vive el código dentro de la imagen.
ENTRYPOINT ["/app/docker/entrada.sh"]
