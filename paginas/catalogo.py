"""
Pantalla del catálogo: búsqueda, alta, edición y activar/desactivar.

El catálogo se derivó del histórico y es independiente de él: cambiar aquí un
precio NO altera ninguna nota pasada, porque cada partida guarda su propia
copia de la descripción y del precio con que se cobró.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import styles

TIPOS = ["Producto", "Servicio"]


def _tabla(conceptos: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ID": c["id_catalogo"],
            "Descripción": c["descripcion"],
            "Tipo": c["tipo_concepto"],
            "Categoría": c["categoria"],
            "Precio actual": db.formato_pesos(c["precio_actual_centavos"]),
            "Veces usado": c["veces_usado"],
            "Activo": "Sí" if c["activo"] else "No",
        }
        for c in conceptos
    ])


def _filtros() -> tuple[str, str | None, str | None, bool]:
    # Claves explícitas: estos controles conviven con los de la pestaña de
    # productos, y Streamlit genera el ID interno a partir del tipo y los
    # parámetros — dos casillas iguales chocarían.
    col1, col2, col3, col4 = st.columns([3, 1.4, 1.8, 1.2])
    busqueda = col1.text_input("Buscar", placeholder="Descripción o categoría…",
                               key="cat_conc_busqueda")
    tipo = col2.selectbox("Tipo", [None] + TIPOS, key="cat_conc_tipo",
                          format_func=lambda v: "Todos" if v is None else v)
    categorias = db.listar_categorias()
    categoria = col3.selectbox("Categoría", [None] + categorias,
                               key="cat_conc_categoria",
                               format_func=lambda v: "Todas" if v is None else v)
    solo_activos = col4.checkbox("Solo activos", value=False,
                                 key="cat_conc_activos")
    return busqueda, tipo, categoria, solo_activos


def _pestana_consultar() -> None:
    busqueda, tipo, categoria, solo_activos = _filtros()
    conceptos = db.listar_catalogo(busqueda, tipo, categoria, solo_activos)

    if not conceptos:
        st.info("Ningún concepto coincide con los filtros.")
        return

    activos = sum(1 for c in conceptos if c["activo"])
    col1, col2, col3 = st.columns(3)
    col1.metric("Conceptos", len(conceptos))
    col2.metric("Activos", activos)
    col3.metric("Inactivos", len(conceptos) - activos)

    st.dataframe(_tabla(conceptos), width="stretch", hide_index=True)

    st.divider()
    st.subheader("Editar concepto")

    opciones = {
        f"#{c['id_catalogo']} — {c['descripcion']} ({c['tipo_concepto']})": c
        for c in conceptos
    }
    etiqueta = st.selectbox("Concepto a editar", list(opciones),
                            index=None, placeholder="Elige un concepto…")
    if etiqueta is None:
        return

    concepto = opciones[etiqueta]
    categorias = db.listar_categorias()

    if concepto["veces_usado"]:
        st.caption(
            f"Este concepto aparece en {concepto['veces_usado']} partidas del "
            "histórico. Editarlo aquí no las modifica."
        )

    with st.form("editar_concepto"):
        col1, col2 = st.columns([3, 2])
        descripcion = col1.text_input("Descripción", value=concepto["descripcion"])
        precio = col2.number_input(
            "Precio actual (pesos)", min_value=0.0, step=50.0, format="%.2f",
            value=float(db.centavos_a_pesos(concepto["precio_actual_centavos"])),
        )
        col3, col4, col5 = st.columns([1.5, 2, 1])
        tipo_concepto = col3.selectbox("Tipo", TIPOS,
                                       index=TIPOS.index(concepto["tipo_concepto"]))
        categoria_sel = col4.selectbox("Categoría", categorias,
                                       index=categorias.index(concepto["categoria"]))
        activo = col5.checkbox("Activo", value=bool(concepto["activo"]))
        guardar = st.form_submit_button("Guardar cambios")

    if guardar:
        if not descripcion.strip():
            st.error("La descripción es obligatoria.")
            return
        try:
            db.actualizar_concepto(
                concepto["id_catalogo"], descripcion, tipo_concepto,
                categoria_sel, db.pesos_a_centavos(precio), activo,
            )
        except Exception as error:  # llave única (descripción, tipo) duplicada
            st.error(f"No se pudo guardar: {error}")
        else:
            st.success(f"Concepto #{concepto['id_catalogo']} actualizado.")
            st.rerun()


def _pestana_alta() -> None:
    st.caption(
        f"La **{db.CONCEPTO_LIBRE}** no va en el catálogo: cruza varias "
        "categorías con precios muy distintos, así que se captura directamente "
        "en cada nota con su precio del momento."
    )

    categorias = db.listar_categorias()

    with st.form("alta_concepto"):
        col1, col2 = st.columns([3, 2])
        descripcion = col1.text_input("Descripción *", placeholder="Ej. Amortiguador")
        precio = col2.number_input("Precio (pesos) *", min_value=0.0, step=50.0,
                                   format="%.2f", value=0.0)
        col3, col4 = st.columns(2)
        tipo_concepto = col3.selectbox("Tipo *", TIPOS)
        categoria = col4.selectbox("Categoría *", categorias)
        agregar = st.form_submit_button("Agregar al catálogo")

    if not agregar:
        return

    if not descripcion.strip():
        st.error("La descripción es obligatoria.")
        return

    try:
        id_catalogo = db.crear_concepto(
            descripcion, tipo_concepto, categoria, db.pesos_a_centavos(precio)
        )
    except Exception as error:
        st.error(
            f"No se pudo agregar. Es probable que ya exista "
            f"**{descripcion.strip()}** como **{tipo_concepto}**.\n\n`{error}`"
        )
    else:
        st.success(
            f"**{descripcion.strip()}** agregado al catálogo con el ID #{id_catalogo}."
        )


# ---------------------------------------------------------------------------
# Productos: lo que el taller compra y vende físicamente
# ---------------------------------------------------------------------------

PRESENTACIONES = ["Aerosol", "Galón", "Botella", "Cubeta", "Lata", "Bolsa",
                  "Caja", "Pieza", "A granel"]
UNIDADES = ["ml", "L", "kg", "g", "pza", "m"]


def _tabla_productos(productos: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ID": p["id_producto"],
            "Producto": p["nombre"],
            "Categoría": p["categoria"],
            "Marca": p["marca"] or "—",
            "Presentación": " ".join(
                str(x) for x in (p["presentacion"],
                                 f"{p['contenido']:g}" if p["contenido"] else None,
                                 p["unidad"]) if x) or "—",
            "Compra": db.formato_pesos(p["precio_compra_centavos"]),
            "Venta": db.formato_pesos(p["precio_venta_centavos"]),
            "Margen": (f"{p['margen_pct']:.0f}%" if p["margen_pct"] is not None
                       else "—"),
            "Stock": f"{p['stock_actual']:g}",
            "Mínimo": f"{p['stock_min']:g}",
            "Estado": ("Bajo mínimo" if p["stock_actual"] < p["stock_min"]
                       else ("Activo" if p["activo"] else "Inactivo")),
        }
        for p in productos
    ])


def _pestana_productos() -> None:
    categorias = db.listar_categorias_producto()
    ops_cat = {f"{c['id_cat']} — {c['nombre']}": c["id_cat"] for c in categorias}

    col1, col2, col3, col4 = st.columns([2.6, 1.8, 1.1, 1.1])
    busqueda = col1.text_input("Buscar", key="prod_busqueda",
                               placeholder="Nombre, marca, categoría o ID…")
    cat = col2.selectbox("Categoría", [None] + list(ops_cat), key="prod_cat",
                         format_func=lambda v: "Todas" if v is None else v)
    solo_activos = col3.checkbox("Solo activos", value=False,
                                 key="prod_activos")
    bajo_min = col4.checkbox("Bajo mínimo", value=False, key="prod_bajo_min")

    productos = db.listar_productos(
        busqueda, ops_cat.get(cat) if cat else None, solo_activos, bajo_min)

    if not productos:
        st.info("Ningún producto coincide con los filtros.")
    else:
        sin_precio = [p for p in productos if p["precio_venta_centavos"] is None]
        alerta = [p for p in productos if p["stock_actual"] < p["stock_min"]]
        margenes = [p["margen_pct"] for p in productos
                    if p["margen_pct"] is not None]

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Productos", len(productos))
        c2.metric("Bajo mínimo", len(alerta))
        c3.metric("Sin precio", len(sin_precio))
        c4.metric("Margen promedio",
                  f"{sum(margenes) / len(margenes):.0f}%" if margenes else "—",
                  help="Sobre el precio de venta, solo de los que tienen ambos "
                       "precios capturados.")

        if sin_precio:
            st.warning(
                f"{len(sin_precio)} producto(s) sin precio de venta: "
                + ", ".join(p["id_producto"] for p in sin_precio)
                + ". No se pueden cobrar en una nota hasta que los completes."
            )
        if alerta:
            st.error(
                "Por debajo del mínimo: "
                + ", ".join(f"{p['nombre']} ({p['stock_actual']:g} de "
                            f"{p['stock_min']:g})" for p in alerta)
            )

        st.dataframe(_tabla_productos(productos), width="stretch",
                     hide_index=True)

    st.divider()
    _editar_producto(productos, ops_cat)


def _editar_producto(productos: list[dict], ops_cat: dict) -> None:
    if not productos:
        return
    st.subheader("Editar producto")

    opciones = {f"{p['id_producto']} — {p['nombre']}": p for p in productos}
    etiqueta = st.selectbox("Producto", list(opciones), index=None,
                            placeholder="Elige un producto…")
    if etiqueta is None:
        return

    p = opciones[etiqueta]
    marcas = db.listar_marcas_producto()
    etiquetas_cat = list(ops_cat)
    idx_cat = next((i for i, e in enumerate(etiquetas_cat)
                    if ops_cat[e] == p["id_cat"]), 0)

    with st.form(f"editar-producto-{p['id_producto']}"):
        col1, col2 = st.columns([3, 2])
        nombre = col1.text_input("Nombre", value=p["nombre"])
        categoria = col2.selectbox("Categoría", etiquetas_cat, index=idx_cat)

        col3, col4, col5, col6 = st.columns([1.6, 1.4, 1, 1])
        marca = col3.selectbox(
            "Marca", marcas,
            index=marcas.index(p["marca"]) if p["marca"] in marcas else None,
            placeholder="Sin marca")
        present = col4.selectbox(
            "Presentación", PRESENTACIONES,
            index=(PRESENTACIONES.index(p["presentacion"])
                   if p["presentacion"] in PRESENTACIONES else None),
            placeholder="—")
        contenido = col5.number_input("Contenido", min_value=0.0, step=0.5,
                                      value=float(p["contenido"] or 0))
        unidad = col6.selectbox(
            "Unidad", UNIDADES,
            index=UNIDADES.index(p["unidad"]) if p["unidad"] in UNIDADES else None,
            placeholder="—")

        col7, col8, col9, col10, col11 = st.columns([1.3, 1.3, 1, 1, 0.8])
        compra = col7.number_input(
            "Precio compra", min_value=0.0, step=10.0, format="%.2f",
            value=float(db.centavos_a_pesos(p["precio_compra_centavos"]) or 0))
        venta = col8.number_input(
            "Precio venta", min_value=0.0, step=10.0, format="%.2f",
            value=float(db.centavos_a_pesos(p["precio_venta_centavos"]) or 0))
        stock = col9.number_input("Existencias", min_value=0.0, step=1.0,
                                  value=float(p["stock_actual"]))
        minimo = col10.number_input("Mínimo", min_value=0.0, step=1.0,
                                    value=float(p["stock_min"]))
        col11.write("")
        activo = col11.checkbox("Activo", value=bool(p["activo"]))

        if venta > 0 and compra > 0:
            st.caption(f"Margen: **${venta - compra:,.2f}** "
                       f"({(venta - compra) / venta * 100:.0f}% sobre la venta)")

        if st.form_submit_button("Guardar producto"):
            if not nombre.strip():
                st.error("El nombre es obligatorio.")
                return
            if 0 < venta < compra:
                st.error("El precio de venta es menor que el de compra.")
                return
            try:
                db.actualizar_producto(
                    p["id_producto"], ops_cat[categoria], nombre, unidad,
                    present, contenido or None, marca,
                    db.pesos_a_centavos(compra) or None,
                    db.pesos_a_centavos(venta) or None,
                    stock, minimo, activo)
            except Exception as error:
                st.error(f"No se pudo guardar: {error}")
            else:
                st.success(f"Producto {p['id_producto']} actualizado.")
                st.rerun()


def _pestana_alta_producto() -> None:
    categorias = db.listar_categorias_producto()
    if not categorias:
        st.warning(
            "No hay categorías de producto. Corre historico/migrar_v4.py "
            "(cópialo antes a la raíz del proyecto; ver historico/LEEME.md)."
        )
        return

    ops_cat = {f"{c['id_cat']} — {c['nombre']}": c["id_cat"] for c in categorias}
    marcas = db.listar_marcas_producto()
    sugerido = db.siguiente_id_producto()

    with st.form("alta_producto"):
        col1, col2, col3 = st.columns([1.2, 3, 2])
        id_producto = col1.text_input("ID *", value=sugerido,
                                      help="Se sugiere el siguiente de la serie.")
        nombre = col2.text_input("Nombre *",
                                 placeholder="Ej. Aceite Roshfrans 5w-30")
        categoria = col3.selectbox("Categoría *", list(ops_cat), index=None,
                                   placeholder="Elige…")

        col4, col5, col6, col7 = st.columns([1.6, 1.4, 1, 1])
        marca = col4.selectbox("Marca", marcas, index=None,
                               placeholder="Sin marca")
        present = col5.selectbox("Presentación", PRESENTACIONES, index=None,
                                 placeholder="—")
        contenido = col6.number_input("Contenido", min_value=0.0, step=0.5,
                                      value=0.0)
        unidad = col7.selectbox("Unidad", UNIDADES, index=None, placeholder="—")

        col8, col9, col10, col11 = st.columns(4)
        compra = col8.number_input("Precio compra", min_value=0.0, step=10.0,
                                   format="%.2f", value=0.0)
        venta = col9.number_input("Precio venta", min_value=0.0, step=10.0,
                                  format="%.2f", value=0.0)
        stock = col10.number_input("Existencias", min_value=0.0, step=1.0,
                                   value=0.0)
        minimo = col11.number_input("Mínimo", min_value=0.0, step=1.0, value=0.0)

        if st.form_submit_button("Agregar producto"):
            if not nombre.strip() or categoria is None:
                st.error("El nombre y la categoría son obligatorios.")
                return
            if 0 < venta < compra:
                st.error("El precio de venta es menor que el de compra.")
                return
            try:
                nuevo = db.crear_producto(
                    id_producto, ops_cat[categoria], nombre, unidad, present,
                    contenido or None, marca,
                    db.pesos_a_centavos(compra) or None,
                    db.pesos_a_centavos(venta) or None, stock, minimo)
            except Exception as error:
                st.error(
                    f"No se pudo agregar. Es probable que el ID "
                    f"«{id_producto}» ya exista.\n\n`{error}`")
            else:
                st.success(f"Producto **{nombre.strip()}** agregado como {nuevo}.")

    with st.expander("¿La marca no está en la lista?"):
        nueva = st.text_input("Marca nueva", key="marca_producto_nueva")
        if st.button("Agregar marca", key="btn_marca_producto") and nueva.strip():
            db.agregar_marca_producto(nueva)
            st.success(f"Marca **{nueva.strip()}** agregada.")
            st.rerun()


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Catálogo")

    productos, alta_prod, conceptos, alta_conc = st.tabs(
        ["Productos", "Agregar producto", "Conceptos cobrables",
         "Agregar concepto"])

    with productos:
        _pestana_productos()
    with alta_prod:
        _pestana_alta_producto()
    with conceptos:
        st.caption(
            "Esto es lo que se puede cobrar en una nota, y NO es lo mismo que "
            "el catálogo de productos: aquí viven los 30 servicios "
            "(Alineación, Afinación, Rectificados, Mano de obra) que son el "
            "grueso de la facturación y no son artículos de almacén."
        )
        _pestana_consultar()
    with alta_conc:
        _pestana_alta()
