#!/bin/sh
# Punto de entrada del contenedor — Servicio Bautista.
#
# Streamlit no lee $PORT directamente (a diferencia de muchos frameworks web
# tradicionales), pero SÍ lee STREAMLIT_SERVER_PORT: cada clave de
# config.toml tiene su equivalente STREAMLIT_<SECCION>_<CLAVE>, y esa
# variable de entorno gana sobre lo que diga config.toml. Render, Fly, Cloud
# Run y compañía inyectan el puerto en $PORT; aquí es donde se traduce uno
# al otro. Si nadie definió ninguno de los dos, se queda en 8501 — el mismo
# valor que trae config.toml hoy, para no sorprender a quien lo pruebe suelto.
set -e

export STREAMLIT_SERVER_PORT="${PORT:-${STREAMLIT_SERVER_PORT:-8501}}"

exec streamlit run app.py
