"""
Pantalla de vehículos: ficha del carro y su historial de servicios.

Antes los datos del vehículo vivían dentro de cada nota, repetidos, así que la
pregunta que más se hace en un taller —"¿qué le hemos hecho a este carro?"— no
se podía responder, y los errores de captura quedaban invisibles: la misma
camioneta aparecía con años distintos en dos notas.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import db
import styles

CONFIRMAR_BORRADO = "vehiculo_por_eliminar"  # id pendiente de confirmar


def etiqueta(v: dict) -> str:
    """El carro se identifica por sí mismo; el dueño solo desempata."""
    partes = [v["marca"], v.get("modelo") or "", str(v.get("anio") or "")]
    texto = " ".join(p for p in partes if p)
    if v.get("placas"):
        texto += f" · {v['placas']}"
    if v.get("cliente"):
        texto += f" — {v['cliente']}"
    return texto


def _tabla(vehiculos: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "ID": v["id_vehiculo"],
            "Marca": v["marca"],
            "Tipo": v["modelo"] or "—",
            "Año": v["anio"] or "—",
            "Color": v["color"] or "—",
            "Placas": v["placas"] or "—",
            "Dueño": v["cliente"] or "—",
            # Quién lo trajo la última vez sale de las notas, no de la ficha:
            # un carro puede cambiar de manos.
            "Último en traerlo": v["ultimo_cliente"] or "—",
            "Servicios": v["num_notas"],
            "Facturado": db.formato_pesos(v["total_centavos"]),
            "Último": v["ultimo_servicio"] or "—",
            "Activo": "Sí" if v["activo"] else "No",
        }
        for v in vehiculos
    ])


def _ficha(id_vehiculo: int) -> None:
    """Historial completo de un vehículo."""
    v = db.obtener_vehiculo(id_vehiculo)
    if v is None:
        st.error("El vehículo ya no existe.")
        return

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Vehículo", f"{v['marca']} {v['modelo'] or ''}".strip())
    col2.metric("Año", v["anio"] or "—")
    col3.metric("Servicios", len(v["historial"]))
    col4.metric("Facturado",
                db.formato_pesos(sum(h["total_centavos"] for h in v["historial"])))

    st.markdown(
        f"**Dueño:** {v['cliente']}"
        + (f" · 📞 {v['telefono']}" if v["telefono"] else "")
        + (f" · **Placas:** {v['placas']}" if v["placas"] else "")
    )
    st.caption(
        "Quién trajo el carro a cada servicio está en el historial: la nota "
        "guarda cliente y vehículo por separado, así que un cambio de dueño "
        "no borra lo que ya pasó."
    )
    if v["observaciones"]:
        st.caption(v["observaciones"])

    if not v["historial"]:
        st.info("Este vehículo todavía no tiene servicios registrados.")
        return

    st.markdown("##### Historial de servicios")
    st.dataframe(
        pd.DataFrame([
            {
                "Folio": h["id_nota"],
                "Fecha": db.formato_fecha(h["fecha"]),
                "Lo trajo": h["cliente"],
                "Estado": h["estado"],
                "Partidas": h["num_partidas"],
                "Total": db.formato_pesos(h["total_centavos"]),
                "Saldo": db.formato_pesos(
                    h["total_centavos"] - h["pagado_centavos"]),
            }
            for h in v["historial"]
        ]),
        width="stretch", hide_index=True,
    )

    st.markdown("##### En qué se ha gastado")
    st.dataframe(
        pd.DataFrame([
            {
                "Categoría": c["categoria"],
                "Partidas": c["veces"],
                "Importe": db.formato_pesos(c["importe_centavos"]),
            }
            for c in v["por_categoria"]
        ]),
        width="stretch", hide_index=True,
    )


def _pestana_consultar() -> None:
    eliminado = st.session_state.pop("vehiculo_eliminado", None)
    if eliminado:
        st.success(f"El vehículo {eliminado} fue eliminado.")
    actualizado = st.session_state.pop("vehiculo_actualizado", None)
    if actualizado:
        st.success(f"Ficha del vehículo #{actualizado} actualizada.")

    col1, col2 = st.columns([3, 1.2])
    busqueda = col1.text_input(
        "Buscar", placeholder="Marca, tipo, placas, año o dueño…")
    solo_activos = col2.checkbox("Solo activos", value=False)

    vehiculos = db.listar_vehiculos(busqueda, solo_activos=solo_activos)
    if not vehiculos:
        st.info("Ningún vehículo coincide con la búsqueda.")
        return

    sin_servicio = sum(1 for v in vehiculos if not v["num_notas"])
    recurrentes = sum(1 for v in vehiculos if v["num_notas"] > 1)
    col1, col2, col3 = st.columns(3)
    col1.metric("Vehículos", len(vehiculos))
    col2.metric("Con más de un servicio", recurrentes)
    col3.metric("Sin servicios", sin_servicio)

    st.dataframe(_tabla(vehiculos), width="stretch", hide_index=True)

    st.divider()
    opciones = {f"#{v['id_vehiculo']} — {etiqueta(v)}": v["id_vehiculo"]
                for v in vehiculos}
    elegido = st.selectbox("Abrir ficha", list(opciones), index=None,
                           placeholder="Elige un vehículo…")
    if elegido:
        _ficha(opciones[elegido])
        st.divider()
        _editar(opciones[elegido])


def _editar(id_vehiculo: int) -> None:
    v = db.obtener_vehiculo(id_vehiculo)
    if v is None:
        return

    st.markdown("##### Corregir la ficha")
    st.caption(
        "Los datos del carro no son historia: si dos notas no coinciden es un "
        "error de captura. Corregirlo aquí se refleja en todas sus notas."
    )

    clientes = db.listar_clientes()
    ops_cliente = {f"#{c['id_cliente']} — {c['nombre']}": c["id_cliente"]
                   for c in clientes}
    etiquetas = list(ops_cliente)
    idx_cliente = next((i for i, e in enumerate(etiquetas)
                        if ops_cliente[e] == v["id_cliente"]), None)
    marcas = db.listar_marcas()

    with st.form(f"editar-vehiculo-{id_vehiculo}"):
        col1, col2 = st.columns([2, 2])
        dueno = col1.selectbox("Dueño *", etiquetas, index=idx_cliente,
                               placeholder="Elige el dueño…")
        marca = col2.selectbox(
            "Marca", marcas,
            index=marcas.index(v["marca"]) if v["marca"] in marcas else 0)

        col3, col4, col5 = st.columns([2, 1, 1.5])
        modelo = col3.text_input(
            "Tipo", value=v["modelo"] or "",
            help="Qué carro o camioneta es, específicamente, de esa marca.")
        anio = col4.number_input(
            "Año", min_value=1900, max_value=2100, step=1,
            value=int(v["anio"]) if v["anio"] else None, placeholder="—")
        color = col5.text_input("Color", value=v["color"] or "")

        col6, col7, col8 = st.columns([1.5, 2, 1])
        placas = col6.text_input("Placas", value=v["placas"] or "")
        vin = col7.text_input("VIN / número de serie", value=v["vin"] or "")
        activo = col8.checkbox("Activo", value=bool(v["activo"]))

        observaciones = st.text_area(
            "Observaciones", value=v["observaciones"] or "",
            placeholder="Detalles del carro que convenga recordar…")

        if st.form_submit_button("Guardar cambios"):
            if dueno is None:
                st.error("El vehículo necesita un dueño.")
                return
            try:
                db.actualizar_vehiculo(
                    id_vehiculo, ops_cliente[dueno], marca, modelo,
                    int(anio) if anio else None, color, placas, vin,
                    observaciones, activo)
            except Exception as error:
                st.error(f"No se pudo guardar: {error}")
            else:
                st.session_state["vehiculo_actualizado"] = id_vehiculo
                st.rerun()

    _eliminar(v)


def _eliminar(v: dict) -> None:
    """
    Borrar un vehículo, con confirmación — mismo patrón que `notas.py`.

    Un carro con historial no se borra: se perdería de qué carro era cada
    nota. Para ese caso está el checkbox «Activo» de arriba, que lo saca de
    las listas de captura sin tocar lo ya facturado.
    """
    id_vehiculo = v["id_vehiculo"]
    pendiente = st.session_state.get(CONFIRMAR_BORRADO)

    if pendiente != id_vehiculo:
        if st.button("🗑️ Eliminar vehículo", key=f"pedir-borrar-{id_vehiculo}"):
            st.session_state[CONFIRMAR_BORRADO] = id_vehiculo
            st.rerun()
        return

    dependientes = db.contar_dependientes_vehiculo(id_vehiculo)
    retenido = {k: n for k, n in dependientes.items() if n}
    if retenido:
        st.error(
            f"No se puede eliminar este vehículo: tiene "
            + ", ".join(f"{n} {k}" for k, n in retenido.items())
            + ". Si ya no viene al taller, desmarca **Activo** arriba: deja "
              "de aparecer al capturar, y su historial se conserva."
        )
        if st.button("Entendido", key=f"cancelar-borrar-{id_vehiculo}"):
            del st.session_state[CONFIRMAR_BORRADO]
            st.rerun()
        return

    st.warning(
        f"Vas a eliminar el vehículo **#{id_vehiculo} — "
        f"{db.descripcion_vehiculo(v)}**. No tiene documentos asociados, así "
        f"que no se pierde historial, pero esto no se puede deshacer."
    )
    izq, der = st.columns(2)
    if izq.button("Sí, eliminar definitivamente", type="primary",
                  key=f"confirmar-borrar-{id_vehiculo}"):
        try:
            db.eliminar_vehiculo(id_vehiculo)
        except ValueError as error:
            st.error(str(error))
            return
        del st.session_state[CONFIRMAR_BORRADO]
        st.session_state["vehiculo_eliminado"] = db.descripcion_vehiculo(v)
        st.rerun()
    if der.button("Cancelar", key=f"cancelar-borrar-{id_vehiculo}"):
        del st.session_state[CONFIRMAR_BORRADO]
        st.rerun()


def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Vehículos")

    # No hay alta suelta a propósito: un carro siempre llega con dueño, y se
    # registra al capturar su primera nota, en «Crear nota».
    st.caption(
        "El padrón de vehículos del taller. Los carros se dan de alta al "
        "capturar su nota en **Crear nota**, junto con su dueño."
    )
    _pestana_consultar()
