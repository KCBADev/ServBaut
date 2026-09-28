"""
Pantalla de notas de servicio: consulta, edición, impresión y captura.

El total de la nota nunca se teclea: sale de la suma de sus partidas, y en la
base lo mantienen los triggers. Eso vale igual al capturar que al editar —
quitar o cambiar un renglón reajusta el total solo.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import db
import nota_pdf
import styles
from paginas import descargas

TIPOS = ["Producto", "Servicio"]
POSICIONES = ["Anterior", "Posterior"]
LADOS = ["Derecho", "Izquierdo", "Par", "Centro"]

# Claves de sesión.
BORRADOR = "partidas_borrador"          # partidas de una nota en captura
CONFIRMAR_BORRADO = "nota_por_eliminar"  # folio pendiente de confirmar


# ---------------------------------------------------------------------------
# Formulario de partida, compartido por captura y edición
# ---------------------------------------------------------------------------

def _indice(opciones: list, valor, por_omision: int | None = 0) -> int | None:
    """
    Índice de `valor` dentro de `opciones`, para precargar un selectbox.

    `por_omision` cubre dos casos a la vez: no se está editando nada
    (`valor` llega en `None` a propósito), o sí se está editando pero ese
    valor ya no aparece en la lista (una categoría que se borró del
    catálogo desde que se capturó el renglón) — en ambos, mejor caer a un
    valor seguro que tronar. Se usa `list.index()` y no una comparación
    manual porque algunas listas (`[None] + POSICIONES`) sí tienen `None`
    como opción legítima en el índice 0, y ese caso debe resolver igual.
    """
    try:
        return opciones.index(valor)
    except ValueError:
        return por_omision


def _indice_por_id(opciones: dict, campo_id: str, valor_id,
                   por_omision: int | None = None) -> int | None:
    """
    Igual que `_indice`, pero para un selectbox cuyas opciones son un
    diccionario `{etiqueta_visible: fila}` — el caso de "Producto" y
    "Concepto", donde no se puede comparar `valor_id` contra la etiqueta.
    """
    if valor_id is None:
        return por_omision
    return next((i for i, e in enumerate(opciones)
                if opciones[e][campo_id] == valor_id), por_omision)


def formulario_partida(
    clave: str, *, inicial: dict | None = None,
    texto_boton: str = "Agregar partida",
) -> dict | None:
    """
    Muestra el formulario de una partida y la devuelve al confirmar.

    Es público porque lo reusa la pantalla de «Crear nota»: es el mismo
    renglón, y duplicarlo garantizaría que las dos versiones se separaran.

    No va dentro de un `st.form` a propósito: al elegir un concepto del
    catálogo hay que refrescar el tipo, la categoría y el precio sugerido, y
    dentro de un formulario los widgets no disparan ese refresco.

    `clave` distingue los widgets entre la pantalla de captura y la de edición,
    que pueden estar vivas a la vez. Al EDITAR, además, `clave` debe ser una
    que nunca se haya usado antes (por ejemplo, que incluya el `id_item` o el
    índice del renglón): los `value=`/`index=` de Streamlit solo se toman en
    cuenta la primera vez que existe esa llave, así que reusar una ya vista
    dejaría la precarga sin efecto.

    `inicial` precarga el formulario con los datos de un renglón YA
    guardado, para corregirlo en vez de partir de uno en blanco. El precio
    (y, si el origen es un producto de almacén, el costo) parten de lo que
    el renglón YA tenía — no del precio/costo actual del catálogo: pudieron
    negociarse distinto en su momento, y editar debe mostrar lo que de
    verdad se cobró, no refrescarlo en silencio con el valor de hoy.

    Si el producto o concepto original ya no está disponible (se desactivó
    o se borró del catálogo desde que se capturó el renglón), el selectbox
    correspondiente se queda sin preseleccionar y se avisa en pantalla —
    mejor eso que bloquear la edición; quien edite puede elegir otro origen
    o dejarlo en «libre».
    """
    indice_origen = 0
    if inicial is not None:
        if inicial.get("id_producto"):
            indice_origen = 0
        elif inicial.get("id_catalogo"):
            indice_origen = 1
        else:
            indice_origen = 2

    origen = st.radio(
        "Origen del concepto",
        ["Producto de almacén", "Concepto cobrable",
         f"{db.CONCEPTO_LIBRE} / libre"],
        index=indice_origen,
        horizontal=True, label_visibility="collapsed", key=f"origen-{clave}",
    )
    del_catalogo = origen == "Concepto cobrable"
    de_almacen = origen == "Producto de almacén"

    categorias = db.listar_categorias()
    acciones = db.listar_acciones()
    id_producto = None
    costo_centavos = None

    if de_almacen:
        # Solo productos con precio de venta: sin él no se puede cobrar.
        disponibles = [p for p in db.listar_productos(solo_activos=True)
                       if p["precio_venta_centavos"]]
        if not disponibles:
            st.warning(
                "No hay productos con precio de venta capturado. "
                "Complétalos en **Catálogo → Productos**."
            )
            return None
        ops = {
            f"{p['id_producto']} · {p['nombre']}"
            + (f" · {p['marca']}" if p["marca"] else "")
            + f" · {db.formato_pesos(p['precio_venta_centavos'])}"
            + (f"  (quedan {p['stock_actual']:g})" if p["stock_actual"] else "")
            : p
            for p in disponibles
        }
        indice_prod = None
        if inicial is not None:
            indice_prod = _indice_por_id(ops, "id_producto",
                                         inicial.get("id_producto"))
            if inicial.get("id_producto") and indice_prod is None:
                st.caption(
                    "⚠️ El producto original ya no está disponible en el "
                    "almacén — elige otro o cambia el origen del concepto."
                )
        etiqueta = st.selectbox("Producto", list(ops), index=indice_prod,
                                placeholder="Busca y elige un producto…",
                                key=f"producto-{clave}")
        if etiqueta is None:
            return None
        prod = ops[etiqueta]
        descripcion = prod["nombre"]
        tipo_concepto = "Producto"
        id_catalogo = None
        id_producto = prod["id_producto"]
        # Se guarda el costo DEL MOMENTO: recalcular el margen del año pasado
        # con el costo de hoy daría un número falso. Al editar, se conserva
        # el costo que ya tenía el renglón por la misma razón — el de hoy
        # puede haber cambiado desde que se capturó.
        costo_centavos = prod["precio_compra_centavos"]
        if inicial is not None and inicial.get("costo_unitario_centavos") is not None:
            costo_centavos = inicial["costo_unitario_centavos"]
        precio_sugerido = float(db.centavos_a_pesos(prod["precio_venta_centavos"]))
        # El producto trae su categoría de almacén; la de la partida es la del
        # sistema del carro, que es otro eje y hay que elegirla.
        categoria = st.selectbox(
            "Categoría del servicio", categorias,
            index=_indice(categorias, inicial.get("categoria") if inicial else None),
            key=f"catsis-{clave}",
            help="En qué sistema del carro se usó. Es distinta de la categoría "
                 "de almacén del producto.")
        if prod["stock_actual"] <= 0:
            st.warning("Este producto está en cero en el almacén.")

    elif del_catalogo:
        conceptos = db.listar_catalogo(solo_activos=True)
        clave_creado = f"concepto_creado-{clave}"

        if not conceptos:
            st.warning(
                "No hay conceptos activos en el catálogo. Da de alta el "
                "primero abajo."
            )
        opciones = {
            f"{c['descripcion']} · {c['tipo_concepto']} · {c['categoria']} "
            f"({db.formato_pesos(c['precio_actual_centavos'])})": c
            for c in conceptos
        }
        # Si acaba de crearse un concepto aquí mismo, queda preseleccionado
        # -por encima de lo que traiga `inicial`, porque refleja la acción
        # más reciente de quien está capturando-.
        recien = st.session_state.pop(clave_creado, None)
        if recien:
            indice = _indice_por_id(opciones, "id_catalogo", recien)
        elif inicial is not None:
            indice = _indice_por_id(opciones, "id_catalogo",
                                    inicial.get("id_catalogo"))
            if inicial.get("id_catalogo") and indice is None:
                st.caption(
                    "⚠️ El concepto original ya no está activo en el "
                    "catálogo — elige otro o cambia el origen del concepto."
                )
        else:
            indice = None

        etiqueta = st.selectbox("Concepto", list(opciones), index=indice,
                                placeholder="Busca y elige un concepto…",
                                key=f"concepto-{clave}", disabled=not opciones)

        with st.expander("➕ El concepto no está en el catálogo"):
            col1, col2 = st.columns([3, 2])
            nueva_desc = col1.text_input(
                "Descripción *", key=f"nuevo_concepto_desc-{clave}",
                placeholder="Ej. Balatas delanteras")
            nuevo_precio = col2.number_input(
                "Precio (pesos) *", min_value=0.0, step=50.0, format="%.2f",
                value=0.0, key=f"nuevo_concepto_precio-{clave}")
            col3, col4 = st.columns(2)
            nuevo_tipo = col3.selectbox("Tipo *", TIPOS,
                                        key=f"nuevo_concepto_tipo-{clave}")
            nueva_cat = col4.selectbox("Categoría *", categorias,
                                       key=f"nuevo_concepto_cat-{clave}")
            if st.button("Agregar al catálogo", key=f"nuevo_concepto_btn-{clave}"):
                if not nueva_desc.strip():
                    st.error("La descripción es obligatoria.")
                elif nuevo_precio <= 0:
                    st.error("El precio debe ser mayor que cero.")
                else:
                    try:
                        nuevo_id = db.crear_concepto(
                            nueva_desc, nuevo_tipo, nueva_cat,
                            db.pesos_a_centavos(nuevo_precio))
                    except Exception as error:
                        st.error(
                            f"No se pudo agregar. Es probable que ya exista "
                            f"«{nueva_desc.strip()}» como {nuevo_tipo}.\n\n"
                            f"`{error}`")
                    else:
                        st.session_state[clave_creado] = nuevo_id
                        st.success(f"«{nueva_desc.strip()}» agregado. "
                                  f"Ya está elegido abajo.")
                        st.rerun()

        if etiqueta is None:
            return None
        concepto = opciones[etiqueta]
        descripcion = concepto["descripcion"]
        tipo_concepto = concepto["tipo_concepto"]
        categoria = concepto["categoria"]
        precio_sugerido = float(db.centavos_a_pesos(concepto["precio_actual_centavos"]))
        id_catalogo = concepto["id_catalogo"]
        st.caption(f"Del catálogo: **{tipo_concepto}** · {categoria}")
    else:
        id_catalogo = None
        col1, col2 = st.columns([3, 2])
        descripcion = col1.text_input(
            "Descripción",
            value=(inicial["descripcion"] if inicial else db.CONCEPTO_LIBRE),
            key=f"desc-{clave}")
        categoria = col2.selectbox(
            "Categoría", categorias,
            index=_indice(categorias, inicial.get("categoria") if inicial else None),
            key=f"cat-{clave}")
        # Al capturar, el origen libre siempre es mano de obra (un servicio,
        # que siempre lleva acción — la regla que el CHECK de la base hace
        # cumplir). Al EDITAR un renglón que ya traía su propio tipo —por
        # ejemplo un producto del Excel histórico, importado sin ligar al
        # catálogo— se conserva ese tipo: convertirlo a Servicio en
        # silencio le cambiaría de qué trata el renglón sin que nadie lo
        # pidiera.
        tipo_concepto = inicial["tipo_concepto"] if inicial else "Servicio"
        precio_sugerido = 0.0

    # El precio guardado gana sobre el precio sugerido del origen elegido:
    # lo que ya se cobró pudo negociarse distinto al de catálogo, y editar
    # debe mostrar eso, no refrescarlo en silencio al precio de hoy.
    if inicial is not None:
        precio_sugerido = float(db.centavos_a_pesos(inicial["precio_unitario_centavos"]))

    col1, col2, col3 = st.columns([1, 2, 2])
    cantidad = col1.number_input(
        "Cantidad", min_value=1, max_value=99,
        value=inicial["cantidad"] if inicial else 1,
        step=1, key=f"cant-{clave}")
    precio = col2.number_input("Precio unitario (pesos)", min_value=0.0, step=50.0,
                               format="%.2f", value=precio_sugerido,
                               key=f"precio-{clave}")

    if tipo_concepto == "Servicio":
        accion = col3.selectbox(
            "Acción *", acciones,
            index=_indice(acciones, inicial.get("accion") if inicial else None),
            key=f"accion-{clave}")
    else:
        accion = None
        col3.caption("Los productos no llevan acción.")

    col4, col5 = st.columns(2)
    opciones_posicion = [None] + POSICIONES
    opciones_lado = [None] + LADOS
    posicion = col4.selectbox(
        "Posición", opciones_posicion,
        index=_indice(opciones_posicion,
                     inicial.get("posicion") if inicial else None),
        key=f"pos-{clave}",
        format_func=lambda v: "No aplica" if v is None else v)
    lado = col5.selectbox(
        "Lado", opciones_lado,
        index=_indice(opciones_lado, inicial.get("lado") if inicial else None),
        key=f"lado-{clave}",
        format_func=lambda v: "No aplica" if v is None else v)

    observacion = st.text_input(
        "Nota del renglón (opcional)",
        value=(inicial.get("notas") or "") if inicial else "",
        key=f"obs-{clave}",
        placeholder="Ej. Reparar puente, pieza pedida al proveedor…",
        help="Es la columna «Notas» de la hoja original.")

    importe = db.pesos_a_centavos(precio) * cantidad
    st.caption(f"Importe de esta partida: **{db.formato_pesos(importe)}**")

    if not st.button(texto_boton, type="primary", key=f"agregar-{clave}"):
        return None

    if not descripcion.strip():
        st.error("La descripción es obligatoria.")
        return None
    if precio <= 0:
        st.error("El precio unitario debe ser mayor que cero.")
        return None

    return {
        "id_catalogo": id_catalogo,
        "id_producto": id_producto,
        "costo_unitario_centavos": costo_centavos,
        "tipo_concepto": tipo_concepto,
        "categoria": categoria,
        "accion": accion,
        "descripcion": descripcion.strip(),
        "posicion": posicion,
        "lado": lado,
        "cantidad": int(cantidad),
        "precio_unitario_centavos": db.pesos_a_centavos(precio),
        "notas": observacion,
    }


def _tabla_partidas(partidas: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "#": p["linea"],
            "Tipo": p["tipo_concepto"],
            "Categoría": p["categoria"],
            "Acción": p["accion"] or "—",
            "Descripción": p["descripcion"],
            "Pos.": p["posicion"] or "—",
            "Lado": p["lado"] or "—",
            "Cant.": p["cantidad"],
            "P. unitario": db.formato_pesos(p["precio_unitario_centavos"]),
            "Importe": db.formato_pesos(p["total_centavos"]),
        }
        for p in partidas
    ])


# ---------------------------------------------------------------------------
# Detalle de una nota
# ---------------------------------------------------------------------------

def _detalle(nota: dict) -> None:
    col1, col2, col3, col4, col5 = st.columns([1, 1.2, 1.4, 1.4, 1.2])
    col1.metric("Folio", nota["id_nota"])
    col2.metric("Fecha", db.formato_fecha(nota["fecha"]))
    col3.metric("Total", db.formato_pesos(nota["total_centavos"]))
    col4.metric("Saldo", db.formato_pesos(nota["saldo_centavos"]),
                help="Total menos lo que ya pagó el cliente.")
    col5.metric("Estado", nota["estado"])

    st.markdown(
        f"**Cliente:** {nota['cliente']} (#{nota['id_cliente']})"
        + (f" · 📞 {nota['telefono']}" if nota["telefono"] else "")
    )
    if nota["id_vehiculo"]:
        st.markdown(
            f"**Vehículo:** {nota['marca']} {nota['modelo'] or ''} "
            f"{nota['anio'] or ''} · {nota['color'] or 'sin color'}"
            + (f" · placas {nota['placas']}" if nota.get("placas") else "")
        )
    else:
        st.warning("Esta nota no tiene vehículo asignado.")

    folio = nota["id_nota"]
    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_nota(folio),
        nombre_archivo=nota_pdf.nombre_archivo(folio),
        etiqueta_descarga="📄 Descargar nota en PDF",
        etiqueta_preparar="📄 Preparar nota en PDF",
        ayuda="Documento imprimible, listo para entregar o mandar al cliente.",
    )

    st.dataframe(_tabla_partidas(nota["partidas"]), width="stretch",
                 hide_index=True)

    # Comprobación visible del invariante que exige la especificación.
    suma = sum(p["total_centavos"] for p in nota["partidas"])
    if suma == nota["total_centavos"]:
        st.caption(f"✓ El total cuadra con la suma de las partidas "
                   f"({db.formato_pesos(suma)}).")
    else:
        st.error(
            f"El total de la nota ({db.formato_pesos(nota['total_centavos'])}) "
            f"no cuadra con sus partidas ({db.formato_pesos(suma)})."
        )


# ---------------------------------------------------------------------------
# Edición de una nota
# ---------------------------------------------------------------------------

def _etiqueta_vehiculo(v: dict) -> str:
    partes = [v["marca"], v.get("modelo") or "", str(v.get("anio") or "")]
    texto = " ".join(p for p in partes if p)
    if v.get("placas"):
        texto += f" · {v['placas']}"
    return f"{texto} — {v['cliente']}"


def _editar_cabecera(nota: dict) -> None:
    st.markdown("##### Cliente y vehículo")

    clientes = db.listar_clientes()
    opciones = {f"#{c['id_cliente']} — {c['nombre']}": c["id_cliente"]
                for c in clientes}
    etiquetas = list(opciones)
    actual = next(
        (i for i, e in enumerate(etiquetas)
         if opciones[e] == nota["id_cliente"]), 0
    )

    # Los datos del vehículo ya no se teclean en la nota: se elige una ficha
    # existente. Corregir el año de un carro se hace una vez, en Vehículos, y
    # se refleja en todas sus notas.
    vehiculos = db.listar_vehiculos()
    ops_veh = {_etiqueta_vehiculo(v): v["id_vehiculo"] for v in vehiculos}
    etiquetas_veh = list(ops_veh)
    actual_veh = next(
        (i for i, e in enumerate(etiquetas_veh)
         if ops_veh[e] == nota["id_vehiculo"]), None
    )

    with st.form(f"cabecera-{nota['id_nota']}"):
        col1, col2 = st.columns([3, 1.5])
        etiqueta = col1.selectbox("Cliente", etiquetas, index=actual)
        fecha = col2.date_input(
            "Fecha", value=datetime.strptime(nota["fecha"], "%Y-%m-%d").date(),
            format="DD/MM/YYYY",
        )
        etiqueta_veh = st.selectbox(
            "Vehículo", etiquetas_veh, index=actual_veh,
            placeholder="Elige un vehículo…",
            help="Se administran en la pantalla de Vehículos.",
        )

        if st.form_submit_button("Guardar cliente y vehículo"):
            try:
                db.actualizar_nota(
                    nota["id_nota"], opciones[etiqueta], fecha.isoformat(),
                    ops_veh.get(etiqueta_veh),
                )
            except Exception as error:
                st.error(f"No se pudo guardar: {error}")
            else:
                st.success("Cabecera actualizada.")
                st.rerun()


def _estado_y_pago(nota: dict) -> None:
    """Flujo del trabajo y cobranza: acciones distintas de corregir la ficha."""
    st.markdown("##### Estado y pago")

    col1, col2 = st.columns(2)

    with col1:
        estado = st.selectbox(
            "Estado del trabajo", db.ESTADOS,
            index=db.ESTADOS.index(nota["estado"]),
            key=f"estado-{nota['id_nota']}",
        )
        if estado != nota["estado"] and st.button(
                "Cambiar estado", key=f"btn-estado-{nota['id_nota']}"):
            db.cambiar_estado(nota["id_nota"], estado)
            mensaje = f"La nota pasó a «{estado}»."
            # Al entregar, `cambiar_estado` ya la marcó como pagada por
            # completo; se avisa para que no extrañe ver saltar el campo
            # «Pagado» sin haberlo tocado.
            if estado == "Entregado" and nota["pagado_centavos"] < nota["total_centavos"]:
                mensaje += " Se marcó como pagada por completo."
            st.success(mensaje)
            st.rerun()

    with col2:
        pagado = st.number_input(
            "Pagado (pesos)", min_value=0.0, step=100.0, format="%.2f",
            value=float(db.centavos_a_pesos(nota["pagado_centavos"])),
            key=f"pagado-{nota['id_nota']}",
        )
        saldo = nota["total_centavos"] - db.pesos_a_centavos(pagado)
        st.caption(
            f"Total {db.formato_pesos(nota['total_centavos'])} · "
            f"saldo quedaría en **{db.formato_pesos(max(saldo, 0))}**"
        )
        if st.button("Registrar pago", key=f"btn-pago-{nota['id_nota']}"):
            try:
                db.registrar_pago(nota["id_nota"], db.pesos_a_centavos(pagado))
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Pago actualizado.")
                st.rerun()


def _editar_partidas(nota: dict) -> None:
    st.markdown("##### Partidas")
    st.caption(
        "Puedes cambiar la cantidad y el precio unitario directamente en la "
        "tabla. El importe y el total se recalculan al guardar."
    )

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
        for p in nota["partidas"]
    ])

    editado = st.data_editor(
        original,
        key=f"editor-{nota['id_nota']}",
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

    if st.button("Guardar cambios de las partidas", type="primary",
                 key=f"guardar-partidas-{nota['id_nota']}"):
        cambios = 0
        for partida, (_, fila) in zip(nota["partidas"], editado.iterrows()):
            cantidad = int(fila["Cantidad"])
            precio = db.pesos_a_centavos(fila["Precio"])
            if (cantidad != partida["cantidad"]
                    or precio != partida["precio_unitario_centavos"]):
                db.actualizar_partida(partida["id_partida"], cantidad, precio)
                cambios += 1
        if cambios:
            st.success(f"{cambios} partida(s) actualizada(s).")
            st.rerun()
        else:
            st.info("No hubo cambios que guardar.")

    # --- Quitar una partida ---
    st.divider()
    col1, col2 = st.columns([3, 1])
    lineas = {
        f"{p['linea']} — {p['descripcion']} "
        f"({db.formato_pesos(p['total_centavos'])})": p["id_partida"]
        for p in nota["partidas"]
    }
    # La llave incluye el número de partidas: al quitar una, la lista
    # cambia de tamaño y el selector arranca sin selección heredada, en vez
    # de quedar apuntando —tras la renumeración— a una partida distinta de
    # la que se acababa de quitar.
    elegida = col1.selectbox("Quitar una partida", list(lineas), index=None,
                             placeholder="Elige el renglón a quitar…",
                             key=f"quitar-{nota['id_nota']}-{len(lineas)}")
    col2.write("")
    if elegida and col2.button("Quitar", key=f"btn-quitar-{nota['id_nota']}"):
        try:
            db.eliminar_partida(lineas[elegida])
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Partida quitada; los renglones se renumeraron.")
            st.rerun()

    # --- Editar una partida ---
    # Antes, corregir cualquier campo que no fuera cantidad/precio (tipo,
    # categoría, acción, descripción, posición, lado) obligaba a quitar el
    # renglón entero y volver a capturarlo desde cero. Este bloque precarga
    # `formulario_partida` con lo que ya tenía el renglón y lo reemplaza con
    # un solo UPDATE (`actualizar_partida_completa`), conservando su lugar
    # en la lista.
    st.divider()
    clave_editando = f"notas_editando-{nota['id_nota']}"
    editando = st.session_state.get(clave_editando)

    if editando is None:
        col1, col2 = st.columns([3, 1])
        elegida_editar = col1.selectbox(
            "Editar una partida", list(lineas), index=None,
            placeholder="Elige el renglón a corregir…",
            key=f"editar-{nota['id_nota']}-{len(lineas)}")
        col2.write("")
        if elegida_editar and col2.button(
                "Editar", key=f"btn-editar-{nota['id_nota']}"):
            st.session_state[clave_editando] = lineas[elegida_editar]
            st.rerun()
    else:
        renglon = next((p for p in nota["partidas"]
                        if p["id_partida"] == editando), None)
        if renglon is None:
            # Alguien más lo quitó mientras tanto (otra pestaña, otra
            # sesión): no hay nada que editar, se cierra el modo edición en
            # silencio en vez de mostrar un formulario sobre un renglón que
            # ya no existe.
            del st.session_state[clave_editando]
        else:
            st.markdown(f"##### Editando el renglón {renglon['linea']}")
            actualizado = formulario_partida(
                f"notas_editar-{editando}", inicial=renglon,
                texto_boton="Guardar cambios de este renglón")
            if actualizado:
                db.actualizar_partida_completa(editando, actualizado)
                del st.session_state[clave_editando]
                st.success("Renglón actualizado.")
                st.rerun()
            if st.button("Cancelar edición",
                         key=f"cancelar-editar-{nota['id_nota']}"):
                del st.session_state[clave_editando]
                st.rerun()

    # --- Agregar una partida ---
    # Oculto mientras se edita un renglón: nunca dos formularios de captura
    # vivos a la vez, que confundiría cuál botón agrega y cuál guarda.
    if editando is None:
        st.divider()
        st.markdown("##### Agregar una partida a esta nota")
        # Mismo motivo que en crear_nota.py/cotizaciones.py: una `clave` fija
        # dejaba el producto/cantidad/precio del renglón anterior puestos al
        # agregar el siguiente. Versionar la llave por nota da widgets en
        # blanco en cada renglón nuevo.
        version = st.session_state.get(f"partida_version-{nota['id_nota']}", 0)
        nueva = formulario_partida(f"edicion-{nota['id_nota']}-{version}")
        if nueva:
            db.agregar_partida(nota["id_nota"], nueva)
            st.session_state[f"partida_version-{nota['id_nota']}"] = version + 1
            st.success("Partida agregada.")
            st.rerun()


def _eliminar_nota(nota: dict) -> None:
    st.markdown("##### Eliminar la nota")
    st.caption(
        "Borra la nota y todas sus partidas. No se puede deshacer."
    )

    pendiente = st.session_state.get(CONFIRMAR_BORRADO)

    if pendiente != nota["id_nota"]:
        if st.button("Eliminar esta nota", key=f"pedir-borrar-{nota['id_nota']}"):
            st.session_state[CONFIRMAR_BORRADO] = nota["id_nota"]
            st.rerun()
        return

    st.warning(
        f"Vas a eliminar la nota **{nota['id_nota']}** de "
        f"**{nota['cliente']}**, con {len(nota['partidas'])} partidas por "
        f"{db.formato_pesos(nota['total_centavos'])}. Esto no se puede deshacer."
    )
    col1, col2 = st.columns(2)
    if col1.button("Sí, eliminar definitivamente", type="primary",
                   key=f"confirmar-{nota['id_nota']}"):
        db.eliminar_nota(nota["id_nota"])
        del st.session_state[CONFIRMAR_BORRADO]
        st.session_state["nota_eliminada"] = nota["id_nota"]
        st.rerun()
    if col2.button("Cancelar", key=f"cancelar-{nota['id_nota']}"):
        del st.session_state[CONFIRMAR_BORRADO]
        st.rerun()


def _panel_nota(id_nota: str) -> None:
    """Detalle y edición de una nota, en pestañas."""
    nota = db.obtener_nota(id_nota)
    if nota is None:
        st.error("La nota ya no existe.")
        return

    detalle, edicion = st.tabs(["Detalle", "Editar"])
    with detalle:
        _detalle(nota)
    with edicion:
        _estado_y_pago(nota)
        st.divider()
        _editar_cabecera(nota)
        st.divider()
        _editar_partidas(nota)
        st.divider()
        _eliminar_nota(nota)


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------

def _pestana_consultar() -> None:
    eliminada = st.session_state.pop("nota_eliminada", None)
    if eliminada:
        st.success(f"La nota {eliminada} fue eliminada.")

    col1, col2, col3, col4 = st.columns([2.6, 1.4, 1.2, 1.2])
    busqueda = col1.text_input("Buscar", placeholder="Folio, cliente, marca o modelo…")
    filtro_estado = col2.selectbox(
        "Estado", [None, "Pendientes de entregar", *db.ESTADOS],
        format_func=lambda v: "Todos" if v is None else v,
    )
    desde = col3.date_input("Desde", value=None, format="DD/MM/YYYY")
    hasta = col4.date_input("Hasta", value=None, format="DD/MM/YYYY")

    notas = db.listar_notas(
        busqueda,
        desde.isoformat() if desde else None,
        hasta.isoformat() if hasta else None,
    )

    if filtro_estado == "Pendientes de entregar":
        notas = [n for n in notas if n["estado"] != "Entregado"]
    elif filtro_estado:
        notas = [n for n in notas if n["estado"] == filtro_estado]

    if not notas:
        st.info("Ninguna nota coincide con los filtros.")
        return

    total = sum(n["total_centavos"] for n in notas)
    por_cobrar = sum(n["saldo_centavos"] for n in notas)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Notas", len(notas))
    col2.metric("Facturado", db.formato_pesos(total))
    col3.metric("Por cobrar", db.formato_pesos(por_cobrar))
    col4.metric("Ticket promedio", db.formato_pesos(total // len(notas)))

    tabla = pd.DataFrame([
        {
            "Folio": n["id_nota"],
            "Fecha": db.formato_fecha(n["fecha"]),
            "Estado": n["estado"],
            "Cliente": n["cliente"],
            "Vehículo": f"{n['marca'] or ''} {n['modelo'] or ''}".strip() or "—",
            "Año": n["anio"] or "—",
            "Partidas": n["num_partidas"],
            "Total": db.formato_pesos(n["total_centavos"]),
            "Saldo": db.formato_pesos(n["saldo_centavos"]),
        }
        for n in notas
    ])
    st.dataframe(tabla, width="stretch", hide_index=True)

    st.divider()
    folios = [n["id_nota"] for n in notas]
    # «Crear nota» manda aquí con el folio recién guardado como query param,
    # para no duplicar el panel de edición en dos pantallas.
    preseleccion = st.query_params.get("folio")
    indice = folios.index(preseleccion) if preseleccion in folios else None
    folio = st.selectbox(
        "Abrir una nota", folios, index=indice, placeholder="Elige un folio…",
    )
    if folio:
        _panel_nota(folio)


def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Notas de servicio")

    # La captura vive en su propia pantalla, «Crear nota»: aquí solo se
    # consultan, editan e imprimen las que ya existen.
    st.caption("Para capturar una nota nueva usa **Crear nota**.")
    _pestana_consultar()
