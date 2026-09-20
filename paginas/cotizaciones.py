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

from datetime import date, datetime

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
CONFIRMAR_BORRADO = "cotizar_por_eliminar"  # folio pendiente de confirmar


def _borrador() -> list[dict]:
    return st.session_state.setdefault(BORRADOR, [])


# ---------------------------------------------------------------------------
# Nueva cotización
# ---------------------------------------------------------------------------

def _bloque_partidas() -> int:
    styles.seccion("3 · Servicios y productos")

    # Mismo motivo que en crear_nota.py: una `clave` fija dejaba el
    # producto/cantidad/precio del renglón anterior puestos al capturar el
    # siguiente. Versionar la llave hace que cada renglón use widgets
    # nuevos, en blanco.
    version = st.session_state.get(f"{PREFIJO}_partida_version", 0)
    formulario = formulario_partida(f"{PREFIJO}-{version}")
    if formulario:
        _borrador().append(formulario)
        st.session_state[f"{PREFIJO}_partida_version"] = version + 1
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
                            key=f"{PREFIJO}_quitar_{len(partidas)}")
    col2.write("")
    if quitar and col2.button("Quitar", key=f"{PREFIJO}_btn_quitar_{len(partidas)}"):
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

    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_cotizacion(folio),
        nombre_archivo=nota_pdf.nombre_archivo_cotizacion(folio),
        etiqueta_descarga="📄 Descargar cotización en PDF",
        etiqueta_preparar="📄 Preparar cotización en PDF",
        ayuda="Documento imprimible para mostrarle al cliente.",
    )

    if st.button("Capturar otra cotización", type="primary",
                 key=f"{PREFIJO}_otra"):
        for clave in (GUARDADA, f"{PREFIJO}_cliente_creado",
                     f"{PREFIJO}_vehiculo_creado", BORRADOR,
                     f"pdf_listo_{folio}"):
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

def _detalle(cotizacion: dict) -> None:
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

    folio = cotizacion["id_cotizacion"]
    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_cotizacion(folio),
        nombre_archivo=nota_pdf.nombre_archivo_cotizacion(folio),
        etiqueta_descarga="📄 Descargar cotización en PDF",
        etiqueta_preparar="📄 Preparar cotización en PDF",
        ayuda="Documento imprimible para mostrarle al cliente.",
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


# ---------------------------------------------------------------------------
# Edición de una cotización — solo si sigue Pendiente: una ya Convertida es
# historial de que ese presupuesto se aceptó (su nota ya tiene su propia
# cabecera, independiente) y una Rechazada ya se cerró.
# ---------------------------------------------------------------------------

def _etiqueta_vehiculo(v: dict) -> str:
    return f"{db.descripcion_vehiculo(v)} — {v['cliente']}"


def _estado_cotizacion(cotizacion: dict) -> None:
    st.markdown("##### Estado")
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

    with col3:
        _pedir_borrado(cotizacion["id_cotizacion"])

    if st.session_state.get(CONFIRMAR_BORRADO) == cotizacion["id_cotizacion"]:
        _confirmar_borrado(cotizacion)


def _editar_cabecera_cotizacion(cotizacion: dict) -> None:
    st.markdown("##### Cliente y vehículo")

    clientes = db.listar_clientes()
    ops_cliente = {f"#{c['id_cliente']} — {c['nombre']}": c["id_cliente"]
                   for c in clientes}
    etiquetas_cliente = list(ops_cliente)
    actual_cliente = next(
        (i for i, e in enumerate(etiquetas_cliente)
         if ops_cliente[e] == cotizacion["id_cliente"]), 0
    )

    vehiculos = db.listar_vehiculos()
    ops_veh = {_etiqueta_vehiculo(v): v["id_vehiculo"] for v in vehiculos}
    etiquetas_veh = list(ops_veh)
    actual_veh = next(
        (i for i, e in enumerate(etiquetas_veh)
         if ops_veh[e] == cotizacion["id_vehiculo"]), None
    )

    with st.form(f"cabecera-cot-{cotizacion['id_cotizacion']}"):
        col1, col2 = st.columns([3, 1.5])
        etiqueta = col1.selectbox("Cliente", etiquetas_cliente, index=actual_cliente)
        fecha = col2.date_input(
            "Fecha",
            value=datetime.strptime(cotizacion["fecha"], "%Y-%m-%d").date(),
            format="DD/MM/YYYY",
        )
        etiqueta_veh = st.selectbox(
            "Vehículo", etiquetas_veh, index=actual_veh,
            placeholder="Elige un vehículo…",
            help="Se administran en la pantalla de Vehículos.",
        )

        if st.form_submit_button("Guardar cliente y vehículo"):
            if etiqueta_veh is None:
                st.error("La cotización necesita un vehículo.")
                return
            try:
                db.actualizar_cotizacion(
                    cotizacion["id_cotizacion"], ops_cliente[etiqueta],
                    fecha.isoformat(), ops_veh[etiqueta_veh],
                )
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Cabecera actualizada.")
                st.rerun()


def _editar_partidas_cotizacion(cotizacion: dict) -> None:
    st.markdown("##### Renglones")
    st.caption(
        "Puedes cambiar la cantidad y el precio unitario directamente en la "
        "tabla. El importe y el total se recalculan al guardar."
    )

    id_cotizacion = cotizacion["id_cotizacion"]
    original = pd.DataFrame([
        {
            "#": p["linea"],
            "Descripción": p["descripcion"],
            "Detalle": " · ".join(
                x for x in (p["accion"], p["posicion"], p["lado"]) if x
            ) or "—",
            "Cantidad": p["cantidad"],
            "Precio": float(db.centavos_a_pesos(p["precio_unitario_centavos"])),
            "Importe": db.formato_pesos(p["total_centavos"]),
        }
        for p in cotizacion["partidas"]
    ])

    editado = st.data_editor(
        original,
        key=f"editor-cot-{id_cotizacion}",
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=["#", "Descripción", "Detalle", "Importe"],
        column_config={
            "Cantidad": st.column_config.NumberColumn(min_value=1, max_value=99,
                                                      step=1),
            "Precio": st.column_config.NumberColumn(min_value=0.0, step=50.0,
                                                    format="$%.2f"),
        },
    )

    if st.button("Guardar cambios de los renglones", type="primary",
                 key=f"guardar-partidas-cot-{id_cotizacion}"):
        cambios = 0
        for partida, (_, fila) in zip(cotizacion["partidas"], editado.iterrows()):
            cantidad = int(fila["Cantidad"])
            precio = db.pesos_a_centavos(fila["Precio"])
            if (cantidad != partida["cantidad"]
                    or precio != partida["precio_unitario_centavos"]):
                db.actualizar_cotizacion_partida(partida["id_item"], cantidad,
                                                 precio)
                cambios += 1
        if cambios:
            st.success(f"{cambios} renglón(es) actualizado(s).")
            st.rerun()
        else:
            st.info("No hubo cambios que guardar.")

    st.divider()
    col1, col2 = st.columns([3, 1])
    lineas = {
        f"{p['linea']} — {p['descripcion']} "
        f"({db.formato_pesos(p['total_centavos'])})": p["id_item"]
        for p in cotizacion["partidas"]
    }
    elegida = col1.selectbox("Quitar un renglón", list(lineas), index=None,
                             placeholder="Elige el renglón a quitar…",
                             key=f"quitar-cot-{id_cotizacion}-{len(lineas)}")
    col2.write("")
    if elegida and col2.button("Quitar", key=f"btn-quitar-cot-{id_cotizacion}"):
        try:
            db.eliminar_cotizacion_partida(lineas[elegida])
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Renglón quitado; se renumeraron los demás.")
            st.rerun()

    st.divider()
    st.markdown("##### Agregar un renglón")
    version = st.session_state.get(f"partida_version-cot-{id_cotizacion}", 0)
    nueva = formulario_partida(f"edicion-cot-{id_cotizacion}-{version}")
    if nueva:
        try:
            db.agregar_cotizacion_partida(id_cotizacion, nueva)
        except ValueError as error:
            st.error(str(error))
        else:
            st.session_state[f"partida_version-cot-{id_cotizacion}"] = version + 1
            st.success("Renglón agregado.")
            st.rerun()


def _panel_cotizacion(id_cotizacion: str) -> None:
    """Detalle y edición de una cotización, en pestañas."""
    # Se vuelve a pedir completa: la fila que arma `listar_cotizaciones` es un
    # resumen para la tabla (sin teléfono, placas ni renglones) y no alcanza.
    cotizacion = db.obtener_cotizacion(id_cotizacion)
    if cotizacion is None:
        st.error("La cotización ya no existe.")
        return

    if cotizacion["estado"] != "Pendiente":
        # Historial cerrado: solo se consulta, no se edita.
        _detalle(cotizacion)
        return

    detalle, edicion = st.tabs(["Detalle", "Editar"])
    with detalle:
        _detalle(cotizacion)
    with edicion:
        _estado_cotizacion(cotizacion)
        st.divider()
        _editar_cabecera_cotizacion(cotizacion)
        st.divider()
        _editar_partidas_cotizacion(cotizacion)


def _pedir_borrado(id_cotizacion: str) -> None:
    if st.button("🗑️ Eliminar", key=f"eliminar-{id_cotizacion}"):
        st.session_state[CONFIRMAR_BORRADO] = id_cotizacion
        st.rerun()


def _confirmar_borrado(cotizacion: dict) -> None:
    """Pide confirmar antes de borrar, igual que `notas.py::_eliminar_nota`."""
    folio = cotizacion["id_cotizacion"]
    st.warning(
        f"Vas a eliminar la cotización **{folio}** de "
        f"**{cotizacion['cliente']}** por "
        f"{db.formato_pesos(cotizacion['total_centavos'])}. "
        f"Esto no se puede deshacer."
    )
    col1, col2 = st.columns(2)
    if col1.button("Sí, eliminar definitivamente", type="primary",
                   key=f"confirmar-borrar-{folio}"):
        db.eliminar_cotizacion(folio)
        del st.session_state[CONFIRMAR_BORRADO]
        st.session_state[f"{PREFIJO}_eliminada"] = folio
        st.rerun()
    if col2.button("Cancelar", key=f"cancelar-borrar-{folio}"):
        del st.session_state[CONFIRMAR_BORRADO]
        st.rerun()


def _pestana_consultar() -> None:
    eliminada = st.session_state.pop(f"{PREFIJO}_eliminada", None)
    if eliminada:
        st.success(f"La cotización {eliminada} fue eliminada.")

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
        _panel_cotizacion(folio)


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Cotizaciones")

    nueva, consultar = st.tabs(["Nueva cotización", "Consultar"])
    with nueva:
        _pestana_nueva()
    with consultar:
        _pestana_consultar()
