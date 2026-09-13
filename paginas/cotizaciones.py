"""
Pantalla «Cotizaciones» — Auto Servicio Bautista.

Mismo formulario que «Crear nota» (cliente, vehículo, renglones, IVA), pero sin
folio de servicio: es un presupuesto, no un trabajo realizado, así que no
aparece en el dashboard ni en los reportes de facturación.

El cliente y el vehículo SÍ se guardan de forma normal en sus tablas si son
nuevos. Es justo lo que permite que, cuando el cliente diga que sí, «Crear
nota» ya los tenga en sus listas — o, más directo, que esta misma pantalla
convierta la cotización en nota con un clic, sin volver a teclear nada.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import db
import nota_pdf
import styles
from paginas import descargas
from paginas.cliente_vehiculo import bloque_cliente, bloque_vehiculo
from paginas.notas import formulario_partida

PREFIJO = "cotizar"
BORRADOR = "cotizar_partidas"
GUARDADA = "cotizar_guardada"


def _borrador() -> list[dict]:
    return st.session_state.setdefault(BORRADOR, [])


# ---------------------------------------------------------------------------
# Nueva cotización
# ---------------------------------------------------------------------------

def _bloque_partidas() -> int:
    styles.seccion("3 · Servicios y productos")

    formulario = formulario_partida(PREFIJO)
    if formulario:
        _borrador().append(formulario)
        st.rerun()

    partidas = _borrador()
    if not partidas:
        st.info("Agrega al menos un renglón para poder guardar la cotización.")
        return 0

    st.dataframe(
        pd.DataFrame([
            {
                "#": i,
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
            }
            for i, p in enumerate(partidas, start=1)
        ]),
        width="stretch", hide_index=True,
    )

    col1, col2 = st.columns([2, 1])
    quitar = col1.selectbox("Quitar renglón", range(1, len(partidas) + 1),
                            index=None, placeholder="Número de renglón…",
                            key=f"{PREFIJO}_quitar")
    col2.write("")
    if quitar and col2.button("Quitar", key=f"{PREFIJO}_btn_quitar"):
        partidas.pop(quitar - 1)
        st.rerun()

    return sum(p["cantidad"] * p["precio_unitario_centavos"] for p in partidas)


def _bloque_cierre(subtotal: int) -> float:
    styles.seccion("4 · Totales")

    col1, col2 = st.columns([1, 2])
    aplica = col1.checkbox("Aplicar IVA", value=False, key=f"{PREFIJO}_iva")
    tasa = 0.0
    if aplica:
        porcentaje = col2.number_input(
            "Tasa (%)", min_value=0.0, max_value=100.0,
            value=db.TASA_IVA * 100, step=1.0, key=f"{PREFIJO}_tasa")
        tasa = porcentaje / 100

    iva = round(subtotal * tasa)
    total = subtotal + iva

    col1, col2, col3 = st.columns(3)
    col1.metric("Subtotal", db.formato_pesos(subtotal))
    col2.metric("IVA", db.formato_pesos(iva))
    col3.metric("Total", db.formato_pesos(total))

    return tasa


def _cotizacion_guardada(folio: str) -> None:
    cotizacion = db.obtener_cotizacion(folio)
    if cotizacion is None:
        return

    st.success(f"Cotización **{folio}** guardada por "
               f"{db.formato_pesos(cotizacion['total_centavos'])}.")
    st.caption(
        "El cliente y el vehículo ya quedaron registrados. Si el cliente "
        "acepta, conviértela en nota desde la pestaña **Consultar** — no hará "
        "falta volver a capturar nada."
    )

    st.download_button(
        "📄 Descargar cotización en PDF",
        data=descargas.pdf_cotizacion(folio),
        file_name=nota_pdf.nombre_archivo_cotizacion(folio),
        mime="application/pdf",
        help="Documento imprimible para mostrarle al cliente.",
        key=f"{PREFIJO}_pdf_guardada",
    )

    if st.button("Capturar otra cotización", type="primary",
                 key=f"{PREFIJO}_otra"):
        for clave in (GUARDADA, f"{PREFIJO}_cliente_creado",
                     f"{PREFIJO}_vehiculo_creado", BORRADOR):
            st.session_state.pop(clave, None)
        st.rerun()


def _pestana_nueva() -> None:
    guardada = st.session_state.get(GUARDADA)
    if guardada:
        _cotizacion_guardada(guardada)
        return

    styles.seccion("1 · Cliente")
    id_cliente = bloque_cliente(PREFIJO)

    st.divider()
    styles.seccion("2 · Vehículo")
    fecha = st.date_input("Fecha *", value=date.today(), format="DD/MM/YYYY",
                          key=f"{PREFIJO}_fecha")
    id_vehiculo = bloque_vehiculo(PREFIJO, id_cliente)

    st.divider()
    subtotal = _bloque_partidas()
    st.divider()
    tasa = _bloque_cierre(subtotal)

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

    if st.button("Guardar cotización", type="primary", disabled=bool(faltantes),
                 key=f"{PREFIJO}_guardar"):
        try:
            nuevo = db.crear_cotizacion(
                id_cliente=id_cliente,
                id_vehiculo=id_vehiculo,
                fecha=fecha.isoformat(),
                partidas=_borrador(),
                tasa_iva=tasa,
            )
        except Exception as error:
            st.error(f"No se pudo guardar la cotización: {error}")
            return
        st.session_state[GUARDADA] = nuevo
        st.rerun()


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------

def _detalle(id_cotizacion: str) -> None:
    # Se vuelve a pedir completa: la fila que arma `listar_cotizaciones` es un
    # resumen para la tabla (sin teléfono, placas ni renglones) y no alcanza
    # para este detalle.
    cotizacion = db.obtener_cotizacion(id_cotizacion)
    if cotizacion is None:
        st.error("La cotización ya no existe.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Folio", cotizacion["id_cotizacion"])
    col2.metric("Fecha", db.formato_fecha(cotizacion["fecha"]))
    col3.metric("Total", db.formato_pesos(cotizacion["total_centavos"]))
    col4.metric("Estado", cotizacion["estado"])

    st.markdown(
        f"**Cliente:** {cotizacion['cliente']}"
        + (f" · 📞 {cotizacion['telefono']}" if cotizacion["telefono"] else "")
    )
    st.markdown(
        f"**Vehículo:** {cotizacion['marca']} {cotizacion['modelo'] or ''} "
        f"{cotizacion['anio'] or ''} · {cotizacion['color'] or 'sin color'}"
    )
    if cotizacion["estado"] == "Convertida":
        st.info(f"Convertida en la nota **{cotizacion['id_nota_generada']}**.")

    st.download_button(
        "📄 Descargar cotización en PDF",
        data=descargas.pdf_cotizacion(cotizacion["id_cotizacion"]),
        file_name=nota_pdf.nombre_archivo_cotizacion(cotizacion["id_cotizacion"]),
        mime="application/pdf",
        help="Documento imprimible para mostrarle al cliente.",
        key=f"pdf-{cotizacion['id_cotizacion']}",
    )

    st.dataframe(
        pd.DataFrame([
            {
                "#": p["linea"],
                "Descripción": p["descripcion"],
                "Cant.": p["cantidad"],
                "P. unitario": db.formato_pesos(p["precio_unitario_centavos"]),
                "Importe": db.formato_pesos(p["total_centavos"]),
            }
            for p in cotizacion["partidas"]
        ]),
        width="stretch", hide_index=True,
    )

    if cotizacion["estado"] != "Pendiente":
        return

    st.divider()
    col1, col2, col3 = st.columns(3)
    if col1.button("✅ Convertir en nota", type="primary",
                   key=f"convertir-{cotizacion['id_cotizacion']}"):
        try:
            folio = db.convertir_cotizacion_a_nota(cotizacion["id_cotizacion"])
        except ValueError as error:
            st.error(str(error))
        else:
            st.success(f"Se creó la nota **{folio}**. Ábrela desde "
                       f"**Notas de servicio** para imprimirla o editarla.")
            st.rerun()

    if col2.button("Rechazar", key=f"rechazar-{cotizacion['id_cotizacion']}"):
        db.rechazar_cotizacion(cotizacion["id_cotizacion"])
        st.info("Cotización marcada como rechazada.")
        st.rerun()

    if col3.button("🗑️ Eliminar", key=f"eliminar-{cotizacion['id_cotizacion']}"):
        db.eliminar_cotizacion(cotizacion["id_cotizacion"])
        st.info("Cotización eliminada.")
        st.rerun()


def _pestana_consultar() -> None:
    col1, col2 = st.columns([3, 1.4])
    busqueda = col1.text_input(
        "Buscar", placeholder="Folio, cliente, marca o modelo…",
        key=f"{PREFIJO}_busqueda")
    estado = col2.selectbox(
        "Estado", [None] + db.ESTADOS_COTIZACION,
        format_func=lambda v: "Todas" if v is None else v,
        key=f"{PREFIJO}_filtro_estado")

    cotizaciones = db.listar_cotizaciones(busqueda, estado)
    if not cotizaciones:
        st.info("Ninguna cotización coincide con los filtros.")
        return

    pendientes = sum(1 for c in cotizaciones if c["estado"] == "Pendiente")
    convertidas = sum(1 for c in cotizaciones if c["estado"] == "Convertida")
    col1, col2, col3 = st.columns(3)
    col1.metric("Cotizaciones", len(cotizaciones))
    col2.metric("Pendientes", pendientes)
    col3.metric("Convertidas", convertidas)

    st.dataframe(
        pd.DataFrame([
            {
                "Folio": c["id_cotizacion"],
                "Fecha": db.formato_fecha(c["fecha"]),
                "Cliente": c["cliente"],
                "Vehículo": f"{c['marca'] or ''} {c['modelo'] or ''}".strip()
                           or "—",
                "Renglones": c["num_partidas"],
                "Total": db.formato_pesos(c["total_centavos"]),
                "Estado": c["estado"],
            }
            for c in cotizaciones
        ]),
        width="stretch", hide_index=True,
    )

    st.divider()
    folio = st.selectbox(
        "Abrir una cotización", [c["id_cotizacion"] for c in cotizaciones],
        index=None, placeholder="Elige un folio…", key=f"{PREFIJO}_abrir")
    if folio:
        _detalle(folio)


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Cotizaciones")

    nueva, consultar = st.tabs(["Nueva cotización", "Consultar"])
    with nueva:
        _pestana_nueva()
    with consultar:
        _pestana_consultar()
