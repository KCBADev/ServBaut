"""
Archivos descargables, generados una sola vez — Auto Servicio Bautista.

`st.download_button` evalúa su contenido en CADA reejecución del script, se
haga clic en él o no. Sin cuidado eso sale caro: la orden en PDF levanta un
Chromium completo (~2 s) y cada exportación vuelca la base entera. En una
pantalla con varios botones esa cuenta se paga otra vez con cada interacción,
aunque nadie descargue nada.

Aquí se cachea el resultado. La llave incluye la fecha de última escritura de
la base: en cuanto se guarda, edita o borra algo, lo cacheado se invalida solo,
así que un PDF nunca sale con datos viejos.
"""

from __future__ import annotations

import streamlit as st

import db
import exportar
import nota_pdf


def _version_datos() -> int:
    """
    Cambia con cada escritura en la base y sirve de llave de invalidación.

    Es un `stat` del archivo, no una consulta: cuesta microsegundos y basta,
    porque cualquier INSERT, UPDATE o DELETE mueve la fecha de escritura.
    """
    return db.RUTA_DB.stat().st_mtime_ns


@st.cache_data(show_spinner=False)
def _pdf_nota(folio: str, version: int) -> bytes:
    return nota_pdf.generar(folio)


@st.cache_data(show_spinner=False)
def _pdf_cotizacion(folio: str, version: int) -> bytes:
    return nota_pdf.generar_cotizacion(folio)


@st.cache_data(show_spinner=False)
def _csv(version: int) -> bytes:
    return exportar.paquete_csv()


@st.cache_data(show_spinner=False)
def _excel(version: int) -> bytes:
    return exportar.libro_excel()


@st.cache_data(show_spinner=False)
def _sql(version: int) -> bytes:
    return exportar.volcado_sql()


@st.cache_data(show_spinner=False)
def _original(version: int) -> bytes:
    return exportar.libro_original()


def pdf_nota(folio: str) -> bytes:
    """Orden de trabajo en PDF, reutilizada mientras la base no cambie."""
    return _pdf_nota(folio, _version_datos())


def pdf_cotizacion(folio: str) -> bytes:
    """Cotización en PDF, reutilizada mientras la base no cambie."""
    return _pdf_cotizacion(folio, _version_datos())


def csv() -> bytes:
    return _csv(_version_datos())


def excel() -> bytes:
    return _excel(_version_datos())


def sql() -> bytes:
    return _sql(_version_datos())


def original() -> bytes:
    return _original(_version_datos())
