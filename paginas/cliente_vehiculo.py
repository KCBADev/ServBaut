"""
Selección o alta de cliente y vehículo — compartido por «Crear nota» y
«Cotizaciones».

Las dos pantallas necesitan exactamente el mismo flujo (elegir un cliente
existente o dar de alta uno nuevo, y lo mismo con el vehículo). Duplicarlo
garantizaría que un día se corrija un detalle en una pantalla y se olvide en
la otra.

`prefijo` distingue las claves de sesión entre pantallas: `st.session_state`
es un solo espacio de nombres compartido por toda la app, así que si las dos
pantallas usaran la misma clave, cambiar de «Crear nota» a «Cotizaciones»
arrastraría lo que se estaba tecleando en la otra.
"""

from __future__ import annotations

import streamlit as st

import db


def bloque_cliente(prefijo: str) -> int | None:
    """Elige un cliente existente o da de alta uno nuevo. Devuelve su id."""
    clave_creado = f"{prefijo}_cliente_creado"
    clientes = db.listar_clientes()
    modo = st.radio(
        "Origen del cliente", ["Ya es cliente", "Cliente nuevo"],
        horizontal=True, label_visibility="collapsed",
        key=f"{prefijo}_modo_cliente")

    if modo == "Ya es cliente":
        if not clientes:
            st.info("Todavía no hay clientes. Cambia a «Cliente nuevo».")
            return None
        opciones = {f"#{c['id_cliente']} — {c['nombre']}"
                    + (f" · {c['telefono']}" if c["telefono"] else ""): c
                    for c in clientes}
        # Si acaba de crearse un cliente aquí mismo, queda preseleccionado.
        recien = st.session_state.pop(clave_creado, None)
        indice = next((i for i, e in enumerate(opciones)
                       if opciones[e]["id_cliente"] == recien),
                      None) if recien else None
        etiqueta = st.selectbox(
            "Cliente *", list(opciones), index=indice,
            placeholder="Busca por nombre o teléfono…",
            help="La búsqueda ignora acentos y mayúsculas.",
            key=f"{prefijo}_sel_cliente")
        if etiqueta is None:
            return None
        cliente = opciones[etiqueta]
        col1, col2, col3 = st.columns([1, 2.4, 1.6])
        col1.metric("ID_Cliente", cliente["id_cliente"])
        col2.metric("Nombre", cliente["nombre"])
        col3.metric("Teléfono", cliente["telefono"] or "—")
        return cliente["id_cliente"]

    # --- Cliente nuevo ---
    siguiente = max((c["id_cliente"] for c in clientes), default=0) + 1
    col1, col2, col3 = st.columns([0.9, 2.6, 1.5])
    col1.text_input("ID_Cliente", value=str(siguiente), disabled=True,
                    key=f"{prefijo}_id_preview",
                    help="Se asigna solo: es el consecutivo de llegada al taller.")
    nombre = col2.text_input("Nombre *", key=f"{prefijo}_cliente_nombre",
                             placeholder="Nombre completo")
    telefono = col3.text_input("Teléfono", key=f"{prefijo}_cliente_tel",
                               placeholder="10 dígitos (opcional)")

    if nombre.strip():
        parecidos = db.buscar_nombres_parecidos(nombre)
        if parecidos:
            st.warning(
                "Ya existe un cliente con ese nombre: "
                + ", ".join(f"#{p['id_cliente']} {p['nombre']}"
                            for p in parecidos)
                + ". Puedes registrarlo igual si es otra persona."
            )

    if st.button("Registrar cliente", key=f"{prefijo}_btn_cliente"):
        if not nombre.strip():
            st.error("El nombre es obligatorio.")
            return None
        try:
            nuevo = db.crear_cliente(nombre, telefono)
        except ValueError as error:
            st.error(str(error))
            return None
        st.session_state[clave_creado] = nuevo
        st.success(f"Cliente **{nombre.strip()}** registrado como #{nuevo}.")
        st.rerun()

    return st.session_state.get(clave_creado)


def bloque_vehiculo(prefijo: str, id_cliente: int | None) -> int | None:
    """
    Elige un vehículo del cliente o da de alta uno nuevo. Devuelve su id.

    Solo ofrece los carros del cliente elegido en `bloque_cliente`: un
    vehículo siempre pertenece a alguien, así que el alta queda amarrada a él.
    """
    clave_creado = f"{prefijo}_vehiculo_creado"

    if id_cliente is None:
        st.info("Elige o registra primero el cliente para capturar su vehículo.")
        return None

    suyos = db.listar_vehiculos(id_cliente=id_cliente, solo_activos=True)
    modo = st.radio(
        "Origen del vehículo",
        ["Vehículo registrado", "Vehículo nuevo"],
        index=0 if suyos else 1,
        horizontal=True, label_visibility="collapsed",
        key=f"{prefijo}_modo_vehiculo")

    if modo == "Vehículo registrado":
        if not suyos:
            st.info("Este cliente no tiene vehículos. Cambia a «Vehículo nuevo».")
            return None
        opciones = {
            " ".join(str(x) for x in (v["marca"], v["modelo"], v["anio"]) if x)
            + (f" · {v['placas']}" if v["placas"] else ""): v
            for v in suyos
        }
        recien = st.session_state.pop(clave_creado, None)
        indice = next((i for i, e in enumerate(opciones)
                       if opciones[e]["id_vehiculo"] == recien),
                      None) if recien else None
        etiqueta = st.selectbox("Vehículo *", list(opciones), index=indice,
                                placeholder="Elige el carro que trajo…",
                                key=f"{prefijo}_sel_vehiculo")
        if etiqueta is None:
            return None
        v = opciones[etiqueta]
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Marca", v["marca"])
        col2.metric("Tipo", v["modelo"] or "—")
        col3.metric("Año", v["anio"] or "—")
        col4.metric("Color", v["color"] or "—")
        return v["id_vehiculo"]

    # --- Vehículo nuevo ---
    marcas = db.listar_marcas()
    col1, col2, col3 = st.columns([1.6, 1.8, 1])
    marca = col1.selectbox("Marca *", marcas, index=None, placeholder="Elige…",
                           key=f"{prefijo}_veh_marca")
    modelo = col2.text_input("Tipo", key=f"{prefijo}_veh_modelo",
                             placeholder="Ej. Patriot, Malibú, Mazda-3",
                             help="Qué carro o camioneta es, específicamente, "
                                  "de esa marca.")
    anio = col3.number_input("Año", min_value=1900, max_value=2100, value=None,
                             step=1, placeholder="—", key=f"{prefijo}_veh_anio")

    col4, col5, col6 = st.columns([1.2, 1.4, 1])
    color = col4.text_input("Color", key=f"{prefijo}_veh_color")
    placas = col5.text_input("Placas", key=f"{prefijo}_veh_placas")
    col6.write("")
    if col6.button("Registrar vehículo", key=f"{prefijo}_btn_veh"):
        if not marca:
            st.error("La marca es obligatoria.")
        else:
            nuevo = db.crear_vehiculo(
                id_cliente, marca, modelo, int(anio) if anio else None,
                color, placas)
            st.session_state[clave_creado] = nuevo
            st.success(f"Vehículo registrado como #{nuevo}.")
            st.rerun()

    with st.expander("¿La marca no está en la lista?"):
        nueva = st.text_input("Marca nueva", key=f"{prefijo}_marca_nueva")
        if (st.button("Agregar marca", key=f"{prefijo}_btn_marca")
                and nueva.strip()):
            db.agregar_marca(nueva)
            st.success(f"Marca **{nueva.strip()}** agregada.")
            st.rerun()

    return st.session_state.get(clave_creado)
