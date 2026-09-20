"""
Pantalla «Crear nota» — Auto Servicio Bautista.

Sigue el mismo orden de las columnas de la hoja de Excel del taller, que es el
orden en que se piensa el trabajo:

  Bloque 1  columnas A–C   ID_Cliente · Nombre · Teléfono
  Bloque 2  columnas E–L   ID_N · Fecha · Marca · Año · Tipo · Color
  Bloque 3  hoja TSA       ID_SA (1..n de la nota) · concepto · precio…
  Bloque 4                 subtotal · IVA · total

Nomenclatura del vehículo, consistente con la base de datos: Marca (Chevrolet),
Año (2016) y Tipo — el modelo específico de esa marca (Malibú). El bloque de
cliente y vehículo vive en `paginas/cliente_vehiculo.py`, compartido con
«Cotizaciones».

El cliente y el vehículo se dan de alta AQUÍ, sin salir de la captura: tener
que abandonar la nota a medias para registrar a alguien que está parado
enfrente es donde se pierde el trabajo capturado.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import db
import nota_pdf
import styles
from paginas import descargas, notas
from paginas.cliente_vehiculo import bloque_cliente, bloque_vehiculo
from paginas.notas import formulario_partida

# Claves de sesión propias, para no pisarse con la pantalla de edición.
PREFIJO = "crear"
BORRADOR = "crear_partidas"
GUARDADA = "crear_nota_guardada"


def _borrador() -> list[dict]:
    return st.session_state.setdefault(BORRADOR, [])


# ---------------------------------------------------------------------------
# Bloque 2 — Folio, fecha, estado y vehículo (columnas E a L)
# ---------------------------------------------------------------------------

def _bloque_nota_vehiculo(id_cliente: int | None) -> tuple:
    styles.seccion("2 · Nota y vehículo", "columnas E–L de la hoja")

    with db.conectar() as conexion:
        folio = db.siguiente_id_nota(conexion)

    col1, col2, col3 = st.columns([1.1, 1.4, 1.4])
    col1.text_input("ID_N", value=folio, disabled=True,
                    help="Folio consecutivo de la nota. Se asigna al guardar.")
    fecha = col2.date_input("Fecha *", value=date.today(), format="DD/MM/YYYY")
    estado = col3.selectbox("Estado", db.ESTADOS, index=0)

    id_vehiculo = bloque_vehiculo(PREFIJO, id_cliente)
    return folio, fecha, estado, id_vehiculo


# ---------------------------------------------------------------------------
# Bloque 3 — Partidas (hoja TSA)
# ---------------------------------------------------------------------------

def _bloque_partidas() -> int:
    styles.seccion("3 · Servicios y productos", "hoja TSA · ID_SA va 1, 2, 3…")

    # `formulario_partida` arma las llaves de sus widgets con la `clave` que
    # se le pasa; una `clave` fija dejaba el producto/cantidad/precio del
    # renglón anterior puestos al capturar el siguiente. Con un número de
    # versión que sube en cada «Agregar», cada renglón usa widgets nuevos
    # que nunca existieron, así que siempre arrancan en blanco.
    version = st.session_state.get("crear_partida_version", 0)
    formulario = formulario_partida(f"crear-{version}")
    if formulario:
        _borrador().append(formulario)
        st.session_state["crear_partida_version"] = version + 1
        st.rerun()

    partidas = _borrador()
    if not partidas:
        st.info("Agrega al menos un renglón para poder guardar la nota.")
        return 0

    st.dataframe(
        pd.DataFrame([
            {
                "ID_SA": i,
                "Tipo": p["tipo_concepto"],
                "Categoría": p["categoria"],
                "Acción": p["accion"] or "—",
                "Descripción": p["descripcion"],
                "Pos.": p["posicion"] or "—",
                "Lado": p["lado"] or "—",
                "Cant.": p["cantidad"],
                "P. unitario": db.formato_pesos(p["precio_unitario_centavos"]),
                "Total": db.formato_pesos(
                    p["cantidad"] * p["precio_unitario_centavos"]),
                "Notas": p.get("notas") or "—",
            }
            for i, p in enumerate(partidas, start=1)
        ]),
        width="stretch", hide_index=True,
    )

    col1, col2 = st.columns([2, 1])
    # La llave incluye `len(partidas)`: al quitar un renglón la lista cambia
    # de tamaño y el selector arranca sin selección heredada, en vez de
    # quedar apuntando —tras la renumeración— a un renglón distinto del que
    # se acababa de quitar.
    quitar = col1.selectbox("Quitar renglón", range(1, len(partidas) + 1),
                            index=None, placeholder="Número de ID_SA…",
                            key=f"crear_quitar_{len(partidas)}")
    col2.write("")
    if quitar and col2.button("Quitar", key=f"crear_btn_quitar_{len(partidas)}"):
        partidas.pop(quitar - 1)
        st.rerun()

    return sum(p["cantidad"] * p["precio_unitario_centavos"] for p in partidas)


# ---------------------------------------------------------------------------
# Bloque 4 — Cierre
# ---------------------------------------------------------------------------

def _bloque_cierre(subtotal: int) -> tuple[float, int]:
    styles.seccion("4 · Totales")

    col1, col2 = st.columns([1, 2])
    aplica = col1.checkbox("Aplicar IVA", value=False, key="crear_iva")
    tasa = 0.0
    if aplica:
        porcentaje = col2.number_input(
            "Tasa (%)", min_value=0.0, max_value=100.0,
            value=db.TASA_IVA * 100, step=1.0, key="crear_tasa")
        tasa = porcentaje / 100

    iva = round(subtotal * tasa)
    total = subtotal + iva

    col1, col2, col3 = st.columns(3)
    col1.metric("Subtotal", db.formato_pesos(subtotal))
    col2.metric("IVA", db.formato_pesos(iva))
    col3.metric("Total", db.formato_pesos(total))

    anticipo = st.number_input(
        "Anticipo recibido (pesos)", min_value=0.0,
        max_value=float(db.centavos_a_pesos(total) or 0) if total else 0.0,
        step=100.0, format="%.2f", value=0.0, key="crear_anticipo")

    return tasa, db.pesos_a_centavos(anticipo)


# ---------------------------------------------------------------------------

def _nota_guardada(folio: str) -> None:
    """Confirmación de la nota, con su orden de trabajo."""
    nota = db.obtener_nota(folio)
    if nota is None:
        return

    st.success(f"Nota **{folio}** guardada por "
               f"{db.formato_pesos(nota['total_centavos'])}.")

    # La orden se arma solo cuando se pide: construirla de entrada levantaba un
    # Chromium (~2 s) en CADA reejecución de esta pantalla, se descargara o no.
    # El mecanismo vive en `descargas.boton_pdf`, compartido con las demás
    # pantallas que exportan documentos.
    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_nota(folio),
        nombre_archivo=nota_pdf.nombre_archivo(folio),
        etiqueta_descarga="📄 Descargar orden de trabajo",
        etiqueta_preparar="📄 Preparar orden de trabajo (PDF)",
        ayuda="El documento que le entregas o le mandas al cliente.")

    st.caption("Los exportes de la base completa (CSV, Excel, SQL y el "
               "formato de tu hoja de siempre) están en "
               "**Configuración**.")

    # Atajo a la nota recién guardada: no se duplica el panel de edición
    # aquí, se manda a «Notas de servicio» —que ya lo tiene completo— con
    # el folio preseleccionado, vía query param.
    col1, col2 = st.columns(2)
    if col1.button("✏️ Editar esta nota", key="guardada_editar"):
        st.switch_page(st.Page(notas.mostrar, url_path="notas"),
                       query_params={"folio": folio})
    if col2.button("🗑️ Eliminar esta nota", key="guardada_eliminar"):
        st.switch_page(st.Page(notas.mostrar, url_path="notas"),
                       query_params={"folio": folio})

    if st.button("Capturar otra nota", type="primary", key="guardada_otra"):
        for clave in (GUARDADA, f"{PREFIJO}_cliente_creado",
                     f"{PREFIJO}_vehiculo_creado", BORRADOR,
                     f"pdf_listo_{folio}"):
            st.session_state.pop(clave, None)
        st.rerun()


def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Crear nota")

    guardada = st.session_state.get(GUARDADA)
    if guardada:
        _nota_guardada(guardada)
        return

    styles.seccion("1 · Cliente", "columnas A–C de la hoja")
    id_cliente = bloque_cliente(PREFIJO)
    st.divider()
    folio, fecha, estado, id_vehiculo = _bloque_nota_vehiculo(id_cliente)
    st.divider()
    subtotal = _bloque_partidas()
    st.divider()
    tasa, anticipo = _bloque_cierre(subtotal)

    st.divider()
    faltantes = []
    if id_cliente is None:
        faltantes.append("el cliente")
    if id_vehiculo is None:
        faltantes.append("el vehículo")
    if not _borrador():
        faltantes.append("al menos un renglón")

    if faltantes:
        st.caption(f"Para guardar falta: {', '.join(faltantes)}.")

    if st.button("Guardar nota", type="primary", disabled=bool(faltantes),
                 key="crear_guardar"):
        try:
            nuevo = db.crear_nota(
                id_cliente=id_cliente,
                fecha=fecha.isoformat(),
                id_vehiculo=id_vehiculo,
                partidas=_borrador(),
                estado=estado,
                pagado_centavos=anticipo,
                tasa_iva=tasa,
            )
        except Exception as error:
            st.error(f"No se pudo guardar la nota: {error}")
            return
        st.session_state[GUARDADA] = nuevo
        st.rerun()
