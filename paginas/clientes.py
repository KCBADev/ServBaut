"""
Pantalla de clientes: búsqueda, alta y edición.

Reglas de la especificación que se aplican aquí:
  * El nombre es obligatorio.
  * El teléfono es opcional (16 clientes del histórico no tienen) y se guarda
    como texto.
  * Al dar de alta se advierte si el nombre ya existe, pero no se impide:
    dos personas pueden llamarse igual.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import styles

CONFIRMAR_BORRADO = "cliente_por_eliminar"  # id pendiente de confirmar


def _tabla(clientes: list[dict]) -> pd.DataFrame:
    """Arma la tabla que se muestra en pantalla, con el dinero ya formateado."""
    return pd.DataFrame([
        {
            "ID": c["id_cliente"],
            "Nombre": c["nombre"],
            "Teléfono": c["telefono"] or "—",
            "Notas": c["num_notas"],
            "Facturado": db.formato_pesos(c["total_facturado_centavos"]),
            "Última visita": c["ultima_visita"] or "—",
        }
        for c in clientes
    ])


def _pestana_buscar() -> None:
    eliminado = st.session_state.pop("cliente_eliminado", None)
    if eliminado:
        st.success(f"El cliente {eliminado} fue eliminado.")
    actualizado = st.session_state.pop("cliente_actualizado", None)
    if actualizado:
        st.success(f"Cliente #{actualizado} actualizado.")

    busqueda = st.text_input(
        "Buscar", placeholder="Nombre, teléfono o ID…",
        help="No distingue mayúsculas ni acentos: 'martin' encuentra 'Martín'.",
    )

    clientes = db.listar_clientes(busqueda)

    if not clientes:
        st.info("Ningún cliente coincide con la búsqueda.")
        return

    total = sum(c["total_facturado_centavos"] for c in clientes)
    izq, der = st.columns(2)
    izq.metric("Clientes encontrados", len(clientes))
    der.metric("Facturación acumulada", db.formato_pesos(total))

    st.dataframe(_tabla(clientes), width="stretch", hide_index=True)

    st.divider()
    st.subheader("Editar o eliminar un cliente")

    opciones = {f"#{c['id_cliente']} — {c['nombre']}": c for c in clientes}
    etiqueta = st.selectbox("Cliente a editar", list(opciones),
                            index=None, placeholder="Elige un cliente…")
    if etiqueta is None:
        return

    cliente = opciones[etiqueta]

    with st.form(f"editar_cliente_{cliente['id_cliente']}"):
        nombre = st.text_input("Nombre", value=cliente["nombre"])
        telefono = st.text_input(
            "Teléfono", value=cliente["telefono"] or "",
            placeholder="10 dígitos (opcional)",
        )
        guardar = st.form_submit_button("Guardar cambios")

    _eliminar(cliente)

    if not guardar:
        return

    if not nombre.strip():
        st.error("El nombre es obligatorio.")
        return

    parecidos = db.buscar_nombres_parecidos(nombre, excluir_id=cliente["id_cliente"])
    if parecidos:
        nombres = ", ".join(f"#{p['id_cliente']} {p['nombre']}" for p in parecidos)
        st.warning(f"Ojo: ya existe otro cliente con ese nombre ({nombres}).")

    try:
        db.actualizar_cliente(cliente["id_cliente"], nombre, telefono)
    except ValueError as error:
        st.error(str(error))
    else:
        st.session_state["cliente_actualizado"] = cliente["id_cliente"]
        st.rerun()


def _eliminar(cliente: dict) -> None:
    """
    Borrar un cliente, con confirmación — mismo patrón que `notas.py`.

    Un cliente con historial NO se borra: `db.eliminar_cliente` lo rechaza con
    un mensaje que dice qué lo está reteniendo. Esto es solo para fichas
    creadas por error, que es de donde vienen los duplicados.
    """
    pendiente = st.session_state.get(CONFIRMAR_BORRADO)
    id_cliente = cliente["id_cliente"]

    if pendiente != id_cliente:
        if st.button("🗑️ Eliminar cliente", key=f"pedir-borrar-{id_cliente}"):
            st.session_state[CONFIRMAR_BORRADO] = id_cliente
            st.rerun()
        return

    dependientes = db.contar_dependientes_cliente(id_cliente)
    retenido = {k: v for k, v in dependientes.items() if v}
    if retenido:
        st.error(
            f"No se puede eliminar a **{cliente['nombre']}**: todavía tiene "
            + ", ".join(f"{v} {k}" for k, v in retenido.items())
            + ". Los registros con historial no se borran; corrige la ficha "
              "si hay un dato mal."
        )
        if st.button("Entendido", key=f"cancelar-borrar-{id_cliente}"):
            del st.session_state[CONFIRMAR_BORRADO]
            st.rerun()
        return

    st.warning(
        f"Vas a eliminar al cliente **#{id_cliente} — {cliente['nombre']}**. "
        f"No tiene vehículos ni documentos, así que no se pierde historial, "
        f"pero esto no se puede deshacer."
    )
    izq, der = st.columns(2)
    if izq.button("Sí, eliminar definitivamente", type="primary",
                  key=f"confirmar-borrar-{id_cliente}"):
        try:
            db.eliminar_cliente(id_cliente)
        except ValueError as error:
            st.error(str(error))
            return
        del st.session_state[CONFIRMAR_BORRADO]
        st.session_state["cliente_eliminado"] = cliente["nombre"]
        st.rerun()
    if der.button("Cancelar", key=f"cancelar-borrar-{id_cliente}"):
        del st.session_state[CONFIRMAR_BORRADO]
        st.rerun()


def _pestana_alta() -> None:
    st.caption(
        "El ID se asigna solo: es el consecutivo de llegada al taller."
    )

    with st.form("alta_cliente"):
        nombre = st.text_input("Nombre *", placeholder="Nombre completo")
        telefono = st.text_input(
            "Teléfono", placeholder="10 dígitos (opcional)",
            help="Se aceptan espacios y guiones; se guardan solo los dígitos.",
        )
        registrar = st.form_submit_button("Registrar cliente")

    # El aviso de duplicado no bloquea: se pide confirmar y se guarda igual.
    pendiente = st.session_state.get("cliente_pendiente")

    if registrar:
        if not nombre.strip():
            st.error("El nombre es obligatorio.")
            return
        try:
            db.normalizar_telefono(telefono)
        except ValueError as error:
            st.error(str(error))
            return

        # Mismo nombre Y mismo teléfono es la misma persona: eso no se
        # confirma, se impide. La confirmación de abajo queda solo para el
        # homónimo con otro teléfono, que sí puede ser alguien distinto.
        repetido = db.buscar_cliente_igual(nombre, telefono)
        if repetido:
            st.session_state.pop("cliente_pendiente", None)
            st.error(
                f"**{repetido['nombre']}** ya está registrado con el ID "
                f"#{repetido['id_cliente']}"
                + (f" y ese mismo teléfono ({repetido['telefono']})."
                   if repetido["telefono"] else " (sin teléfono).")
                + " Búscalo en «Buscar y editar» en vez de registrarlo otra vez."
            )
            return

        parecidos = db.buscar_nombres_parecidos(nombre)
        if parecidos:
            st.session_state.cliente_pendiente = {
                "nombre": nombre, "telefono": telefono,
            }
            st.rerun()
        else:
            _guardar(nombre, telefono)
        return

    if pendiente:
        parecidos = db.buscar_nombres_parecidos(pendiente["nombre"])
        nombres = ", ".join(
            f"#{p['id_cliente']} {p['nombre']}"
            + (f" ({p['telefono']})" if p["telefono"] else "")
            for p in parecidos
        )
        st.warning(
            f"Ya hay un cliente registrado con el nombre "
            f"**{pendiente['nombre']}**: {nombres}.\n\n"
            "¿Es una persona distinta?"
        )
        izq, der = st.columns(2)
        if izq.button("Sí, registrar de todos modos", width="stretch"):
            _guardar(pendiente["nombre"], pendiente["telefono"])
        if der.button("Cancelar", width="stretch"):
            del st.session_state.cliente_pendiente
            st.rerun()


def _guardar(nombre: str, telefono: str) -> None:
    try:
        id_cliente = db.crear_cliente(nombre, telefono)
    except ValueError as error:
        st.error(str(error))
        return
    st.session_state.pop("cliente_pendiente", None)
    st.success(f"Cliente **{nombre.strip()}** registrado con el ID #{id_cliente}.")


def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Clientes")

    buscar, alta = st.tabs(["Buscar y editar", "Registrar nuevo"])
    with buscar:
        _pestana_buscar()
    with alta:
        _pestana_alta()
