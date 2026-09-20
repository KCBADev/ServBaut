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

La caché sola no basta, porque se invalida con CUALQUIER escritura: basta
registrar otro cliente para que el PDF de una nota vieja haya que rehacerlo.
Por eso los PDFs se piden en dos pasos con `boton_pdf`: abrir un documento
guardado no debe costar un Chromium.
"""

from __future__ import annotations

from typing import Callable

import streamlit as st

import db
import diagnostico_pdf
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
def _pdf_diagnostico(folio: str, version: int) -> bytes:
    return diagnostico_pdf.generar(folio)


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


def pdf_diagnostico(folio: str) -> bytes:
    """Reporte de diagnóstico en PDF, reutilizado mientras la base no cambie."""
    return _pdf_diagnostico(folio, _version_datos())


def boton_pdf(clave: str, generar: Callable[[], bytes], nombre_archivo: str,
              etiqueta_descarga: str, etiqueta_preparar: str,
              ayuda: str | None = None) -> None:
    """
    Botón de PDF en dos pasos: primero «Preparar…», luego «Descargar».

    `st.download_button` evalúa su `data=` en CADA reejecución del script —al
    teclear en un buscador, al cambiar un filtro— y armar un PDF levanta un
    Chromium completo (~2 s). Con el paso previo, el navegador solo arranca
    cuando alguien pide el documento de verdad: abrir una nota guardada es
    inmediato.

    `clave` distingue el documento (normalmente su folio): así dos pantallas
    abiertas sobre documentos distintos no se pisan el estado, y cambiar de
    documento vuelve a pedir el paso de preparación.
    """
    listo = f"pdf_listo_{clave}"
    if st.session_state.get(listo):
        st.download_button(
            etiqueta_descarga, data=generar(), file_name=nombre_archivo,
            mime="application/pdf", key=f"bajar_pdf_{clave}", help=ayuda)
    elif st.button(etiqueta_preparar, key=f"preparar_pdf_{clave}", help=ayuda):
        st.session_state[listo] = True
        st.rerun()


def csv() -> bytes:
    return _csv(_version_datos())


def excel() -> bytes:
    return _excel(_version_datos())


def sql() -> bytes:
    return _sql(_version_datos())


def original() -> bytes:
    return _original(_version_datos())
