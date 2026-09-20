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


def _tras_dar_de_alta(prefijo: str, tipo: str, id_nuevo: int,
                      aviso: str) -> None:
    """
    Deja el bloque listo tras un alta (o tras reusar un registro existente).

    Antes esto era un `st.success(...)` seguido de `st.rerun()`, y esa pareja
    es justo lo que produjo los duplicados que hubo que limpiar a mano: el
    rerun tira el mensaje sin que dé tiempo a verlo, y como el radio y los
    campos conservan su valor, reaparecía el MISMO formulario lleno con el
    mismo botón. Parecía que no había pasado nada, así que el usuario volvía
    a pulsar «Registrar» y se creaba otra fila.

    Ahora: el aviso se guarda para pintarlo en la pasada siguiente, y se sube
    el número de versión de las llaves de los widgets, con lo que el bloque
    renace en la rama «ya registrado» con lo recién dado de alta seleccionado
    y los campos del alta en blanco. Se versiona en vez de escribir la llave
    del radio porque Streamlit prohíbe modificar la llave de un widget ya
    instanciado en la misma pasada.
    """
    st.session_state[f"{prefijo}_{tipo}_creado"] = id_nuevo
    st.session_state[f"{prefijo}_{tipo}_aviso"] = aviso
    clave_version = f"{prefijo}_{tipo}_version"
    st.session_state[clave_version] = st.session_state.get(clave_version, 0) + 1
    st.rerun()


def bloque_cliente(prefijo: str) -> int | None:
    """Elige un cliente existente o da de alta uno nuevo. Devuelve su id."""
    clave_creado = f"{prefijo}_cliente_creado"
    version = st.session_state.get(f"{prefijo}_cliente_version", 0)
    clave = lambda nombre: f"{prefijo}_{nombre}_{version}"  # noqa: E731

    aviso = st.session_state.pop(f"{prefijo}_cliente_aviso", None)
    if aviso:
        st.success(aviso)

    clientes = db.listar_clientes()
    modo = st.radio(
        "Origen del cliente", ["Ya es cliente", "Cliente nuevo"],
        horizontal=True, label_visibility="collapsed",
        key=clave("modo_cliente"))

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
            key=clave("sel_cliente"))
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
                    key=clave("id_preview"),
                    help="Se asigna solo: es el consecutivo de llegada al taller.")
    nombre = col2.text_input("Nombre *", key=clave("cliente_nombre"),
                             placeholder="Nombre completo")
    telefono = col3.text_input("Teléfono", key=clave("cliente_tel"),
                               placeholder="10 dígitos (opcional)")

    # Mismo nombre Y mismo teléfono es la misma persona: se bloquea el alta y
    # se ofrece usar la ficha que ya existe. Mismo nombre con otro teléfono
    # solo se advierte: dos personas pueden llamarse igual.
    repetido = None
    if nombre.strip():
        try:
            repetido = db.buscar_cliente_igual(nombre, telefono)
        except ValueError:
            repetido = None  # teléfono a medio teclear; se avisa al registrar

        if repetido:
            st.error(
                f"**{repetido['nombre']}** ya está registrado como el cliente "
                f"#{repetido['id_cliente']}"
                + (f" con ese mismo teléfono ({repetido['telefono']})."
                   if repetido["telefono"] else " (sin teléfono).")
            )
            if st.button("Usar ese cliente", type="primary",
                         key=clave("usar_cliente")):
                _tras_dar_de_alta(
                    prefijo, "cliente", repetido["id_cliente"],
                    f"Se usará el cliente #{repetido['id_cliente']} — "
                    f"{repetido['nombre']}, ya seleccionado abajo.")
        else:
            parecidos = db.buscar_nombres_parecidos(nombre)
            if parecidos:
                st.warning(
                    "Ya existe un cliente con ese nombre: "
                    + ", ".join(f"#{p['id_cliente']} {p['nombre']}"
                                for p in parecidos)
                    + ". Puedes registrarlo igual si es otra persona."
                )

    if st.button("Registrar cliente", key=clave("btn_cliente"),
                 disabled=bool(repetido)):
        if not nombre.strip():
            st.error("El nombre es obligatorio.")
            return None
        try:
            nuevo = db.crear_cliente(nombre, telefono)
        except ValueError as error:
            st.error(str(error))
            return None
        _tras_dar_de_alta(prefijo, "cliente", nuevo,
                          f"Cliente **{nombre.strip()}** registrado como "
                          f"#{nuevo} y ya seleccionado abajo.")

    return st.session_state.get(clave_creado)


def bloque_vehiculo(prefijo: str, id_cliente: int | None) -> int | None:
    """
    Elige un vehículo del cliente o da de alta uno nuevo. Devuelve su id.

    Solo ofrece los carros del cliente elegido en `bloque_cliente`: un
    vehículo siempre pertenece a alguien, así que el alta queda amarrada a él.
    """
    clave_creado = f"{prefijo}_vehiculo_creado"
    version = st.session_state.get(f"{prefijo}_vehiculo_version", 0)
    clave = lambda nombre: f"{prefijo}_{nombre}_{version}"  # noqa: E731

    if id_cliente is None:
        st.info("Elige o registra primero el cliente para capturar su vehículo.")
        return None

    aviso = st.session_state.pop(f"{prefijo}_vehiculo_aviso", None)
    if aviso:
        st.success(aviso)

    suyos = db.listar_vehiculos(id_cliente=id_cliente, solo_activos=True)
    modo = st.radio(
        "Origen del vehículo",
        ["Vehículo registrado", "Vehículo nuevo"],
        index=0 if suyos else 1,
        horizontal=True, label_visibility="collapsed",
        key=clave("modo_vehiculo"))

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
                                key=clave("sel_vehiculo"))
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
                           key=clave("veh_marca"))
    modelo = col2.text_input("Tipo", key=clave("veh_modelo"),
                             placeholder="Ej. Patriot, Malibú, Mazda-3",
                             help="Qué carro o camioneta es, específicamente, "
                                  "de esa marca.")
    anio = col3.number_input("Año", min_value=1900, max_value=2100, value=None,
                             step=1, placeholder="—", key=clave("veh_anio"))

    col4, col5, col6 = st.columns([1.2, 1.4, 1])
    color = col4.text_input("Color", key=clave("veh_color"))
    placas = col5.text_input(
        "Placas", key=clave("veh_placas"),
        help="Es lo que distingue dos carros iguales. Si el carro no la trae, "
             "déjala en blanco.")

    # Con placa manda la placa; sin placa, el mismo carro del mismo dueño ya
    # registrado cuenta como repetido. En los dos casos se ofrece usar el que
    # existe en vez de crear otro — que es como aparecieron seis Camaro
    # idénticos del mismo cliente.
    repetido = db.buscar_vehiculo_igual(
        id_cliente, marca, modelo, int(anio) if anio else None, color,
        placas) if marca else None

    if repetido:
        st.error(
            f"Ese vehículo ya está registrado como #{repetido['id_vehiculo']}: "
            f"{db.descripcion_vehiculo(repetido)} "
            f"(dueño: {repetido['cliente']})."
            + ("" if repetido["placas"] else
               " Si de verdad son dos carros distintos, captura su placa.")
        )
        if st.button("Usar ese vehículo", type="primary",
                     key=clave("usar_veh")):
            _tras_dar_de_alta(
                prefijo, "vehiculo", repetido["id_vehiculo"],
                f"Se usará el vehículo #{repetido['id_vehiculo']} — "
                f"{db.descripcion_vehiculo(repetido)}, ya seleccionado arriba.")

    col6.write("")
    if col6.button("Registrar vehículo", key=clave("btn_veh"),
                   disabled=bool(repetido)):
        if not marca:
            st.error("La marca es obligatoria.")
        else:
            try:
                nuevo = db.crear_vehiculo(
                    id_cliente, marca, modelo, int(anio) if anio else None,
                    color, placas)
            except ValueError as error:
                st.error(str(error))
            else:
                _tras_dar_de_alta(
                    prefijo, "vehiculo", nuevo,
                    f"Vehículo registrado como #{nuevo} y ya seleccionado "
                    f"arriba.")

    with st.expander("¿La marca no está en la lista?"):
        nueva = st.text_input("Marca nueva", key=clave("marca_nueva"))
        if (st.button("Agregar marca", key=clave("btn_marca"))
                and nueva.strip()):
            db.agregar_marca(nueva)
            st.success(f"Marca **{nueva.strip()}** agregada.")
            st.rerun()

    return st.session_state.get(clave_creado)
