"""
Pantalla «Diagnósticos con escáner» — Auto Servicio Bautista.

Captura el mismo reporte que hoy se entrega en papel tras conectar el
escáner: folio, cliente y vehículo (igual que una nota), la lista de códigos
de falla (DTC) agrupados por sistema, y el resumen y las recomendaciones, que
el técnico redacta a mano después de leer los códigos — la app no interpreta
ni sugiere nada, solo captura lo que el escáner y el técnico dicen.

No maneja dinero ni catálogo, así que no comparte formulario con «Crear nota»
o «Cotizaciones» más allá del bloque de cliente y vehículo.
"""

from __future__ import annotations

from datetime import date, datetime

import pandas as pd
import streamlit as st

import db
import diagnostico_pdf
import styles
from paginas import descargas
from paginas.cliente_vehiculo import bloque_cliente, bloque_vehiculo

PREFIJO = "diag"
BORRADOR = "diag_codigos"
GUARDADA = "diag_guardada"
CONFIRMAR_BORRADO = "diag_por_eliminar"  # folio pendiente de confirmar

GRAVEDAD_ETIQUETA = {
    "ALTA": "🔴 ALTA", "MEDIA": "🟠 MEDIA", "BAJA": "🟢 BAJA", "INFO": "⚪ INFO",
}


def _borrador() -> list[dict]:
    return st.session_state.setdefault(BORRADOR, [])


# ---------------------------------------------------------------------------
# Nuevo diagnóstico
# ---------------------------------------------------------------------------

def _bloque_folio_vehiculo(id_cliente: int | None) -> tuple:
    styles.seccion("2 · Diagnóstico y vehículo")

    with db.conectar() as conexion:
        folio = db.siguiente_id_diagnostico(conexion)

    col1, col2, col3 = st.columns([1.1, 1.4, 1.4])
    col1.text_input("Folio", value=folio, disabled=True,
                    help="Se asigna al guardar el diagnóstico.",
                    key=f"{PREFIJO}_folio_preview")
    fecha = col2.date_input("Fecha *", value=date.today(), format="DD/MM/YYYY",
                            key=f"{PREFIJO}_fecha")
    tecnico = col3.text_input("Atendió (técnico)", key=f"{PREFIJO}_tecnico")

    num_modulos = st.number_input(
        "Número de módulos analizados", min_value=0, max_value=99, value=0,
        step=1, key=f"{PREFIJO}_num_modulos",
        help="Cuántos módulos electrónicos leyó el escáner en total.")

    id_vehiculo = bloque_vehiculo(PREFIJO, id_cliente)
    return folio, fecha, tecnico, num_modulos, id_vehiculo


def _formulario_codigo() -> dict | None:
    """
    Formulario de un código de falla. No va dentro de `st.form`: elegir un
    sistema ya usado en este borrador debe reflejarse de inmediato en el
    campo de abajo, y dentro de un formulario los widgets no refrescan hasta
    que se manda — mismo motivo que `formulario_partida` en notas.py.

    Las llaves de los widgets llevan un número de versión (`_bloque_codigos`
    lo sube cada vez que se agrega un código). Streamlit prohíbe reasignar
    `st.session_state` de un widget que ya se instanció en el mismo run —
    picar «Agregar código» con la llave fija tronaba con
    `StreamlitWidgetAlreadyInstantiatedError` al intentar dejar seleccionado
    el sistema para el siguiente renglón. Con una llave nueva por versión,
    ese widget nunca existió antes y `index` sí se respeta; de paso, los
    campos de texto quedan en blanco para el siguiente código, que es lo que
    se espera al capturar uno tras otro.
    """
    version = st.session_state.get(f"{PREFIJO}_form_version", 0)
    clave = lambda nombre: f"{PREFIJO}_{nombre}_{version}"  # noqa: E731

    sistemas = list(dict.fromkeys(c["sistema"] for c in _borrador()))
    ultimo_sistema = st.session_state.get(f"{PREFIJO}_ultimo_sistema")

    col1, col2 = st.columns([2, 1])
    opciones_sistema = sistemas + ["+ Nuevo sistema…"]
    indice_defecto = (opciones_sistema.index(ultimo_sistema)
                      if ultimo_sistema in opciones_sistema
                      else len(opciones_sistema) - 1)
    eleccion = col1.selectbox(
        "Sistema / módulo *", opciones_sistema,
        index=indice_defecto, key=clave("sel_sistema"),
        help="Agrupa los códigos en el reporte, p. ej. «Motor y sistema de "
             "propulsión» o «Frenos ABS (antibloqueo)».")
    gravedad = col2.selectbox("Gravedad", db.GRAVEDADES, index=1,
                              key=clave("gravedad"))

    if eleccion == "+ Nuevo sistema…":
        col1, col2 = st.columns([2, 3])
        sistema = col1.text_input(
            "Nombre del sistema *", key=clave("sistema_nuevo"),
            placeholder="Ej. Motor y sistema de propulsión")
        sistema_nota = col2.text_input(
            "Nota del sistema (opcional)", key=clave("sistema_nota"),
            placeholder="Ej. esto enciende el testigo de Check Engine.")
    else:
        sistema = eleccion
        sistema_nota = ""

    col1, col2 = st.columns([1, 3])
    codigo = col1.text_input("Código *", key=clave("codigo"),
                             placeholder="P0135")
    descripcion = col2.text_input(
        "Descripción del escáner *", key=clave("descripcion"),
        placeholder="Fallo en el circuito del calentador de HO2S banco 1 sensor 1")

    significado = st.text_area(
        "Qué significa *", key=clave("significado"), height=70,
        placeholder="Explicación en español llano de lo que ese código indica.")

    if not st.button("Agregar código", type="primary",
                     key=clave("agregar_codigo")):
        return None

    if not sistema.strip():
        st.error("El sistema es obligatorio.")
        return None
    if not codigo.strip():
        st.error("El código es obligatorio.")
        return None
    if not descripcion.strip():
        st.error("La descripción del escáner es obligatoria.")
        return None
    if not significado.strip():
        st.error("Falta explicar qué significa el código.")
        return None

    return {
        "sistema": sistema.strip(),
        "sistema_nota": sistema_nota.strip() or None,
        "codigo": codigo.strip().upper(),
        "descripcion": descripcion.strip(),
        "significado": significado.strip(),
        "gravedad": gravedad,
    }


def _bloque_codigos() -> None:
    styles.seccion("3 · Códigos identificados (DTC)",
                   "uno por renglón, agrupados por sistema")

    nuevo = _formulario_codigo()
    if nuevo:
        _borrador().append(nuevo)
        # `_ultimo_sistema` y `_form_version` son variables de sesión propias,
        # no llaves de ningún widget, así que escribirlas aquí siempre es
        # válido (a diferencia de la llave del selectbox, que Streamlit ya
        # instanció en este mismo run). Subir la versión hace que el próximo
        # render use widgets con llaves nuevas: quedan en blanco y el
        # selector de sistema arranca en el mismo que se acaba de capturar —
        # lo normal es seguir con varios códigos del mismo sistema (6 del
        # motor, 18 del ABS…), no uno de cada uno.
        st.session_state[f"{PREFIJO}_ultimo_sistema"] = nuevo["sistema"]
        st.session_state[f"{PREFIJO}_form_version"] = (
            st.session_state.get(f"{PREFIJO}_form_version", 0) + 1)
        st.rerun()

    codigos = _borrador()
    if not codigos:
        st.info("Agrega al menos un código para poder guardar el diagnóstico.")
        return

    st.dataframe(
        pd.DataFrame([
            {
                "#": i,
                "Sistema": c["sistema"],
                "Código": c["codigo"],
                "Descripción del escáner": c["descripcion"],
                "Qué significa": c["significado"],
                "Gravedad": GRAVEDAD_ETIQUETA.get(c["gravedad"], c["gravedad"]),
            }
            for i, c in enumerate(codigos, start=1)
        ]),
        width="stretch", hide_index=True,
    )

    col1, col2 = st.columns([2, 1])
    # La llave incluye `len(codigos)`: al quitar un renglón la lista cambia
    # de tamaño y Streamlit trata el selector como uno nuevo, sin selección
    # heredada. Sin esto, tras renumerar, el número que quedó "elegido"
    # podía apuntar a un renglón distinto del que se acababa de quitar —
    # arriesgando un segundo borrado por error.
    quitar = col1.selectbox("Quitar renglón", range(1, len(codigos) + 1),
                            index=None, placeholder="Número de renglón…",
                            key=f"{PREFIJO}_quitar_{len(codigos)}")
    col2.write("")
    if quitar and col2.button("Quitar", key=f"{PREFIJO}_btn_quitar_{len(codigos)}"):
        codigos.pop(quitar - 1)
        st.rerun()


def _bloque_cierre() -> tuple[str, str]:
    styles.seccion("4 · Otros módulos y recomendaciones")

    otros_modulos = st.text_area(
        "Otros módulos revisados (opcional)", key=f"{PREFIJO}_otros_modulos",
        placeholder="Ej. Módulo de puerta (conductor) — sin códigos (OK). "
                    "Módulo electrónico trasero — 2 códigos en memoria (a revisar).",
        help="Módulos que se leyeron pero no tienen tabla propia de códigos.")

    resumen = st.text_area(
        "Resumen y recomendaciones *", key=f"{PREFIJO}_resumen", height=160,
        placeholder="En orden de prioridad, lo que se recomienda atender…\n"
                    "1. …\n2. …",
        help="Se redacta a mano después de leer los códigos; es lo que el "
             "cliente firma de enterado.")

    return otros_modulos, resumen


def _diagnostico_guardado(folio: str) -> None:
    diagnostico = db.obtener_diagnostico(folio)
    if diagnostico is None:
        return

    st.success(f"Diagnóstico **{folio}** guardado con "
               f"{len(diagnostico['codigos'])} código(s).")

    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_diagnostico(folio),
        nombre_archivo=diagnostico_pdf.nombre_archivo(folio),
        etiqueta_descarga="📄 Descargar reporte en PDF",
        etiqueta_preparar="📄 Preparar reporte en PDF",
        ayuda="El reporte que le entregas o le mandas al cliente.",
    )

    if st.button("Capturar otro diagnóstico", type="primary",
                 key=f"{PREFIJO}_otro"):
        st.session_state.pop(f"pdf_listo_{folio}", None)
        # Barre TODAS las llaves de esta pantalla (empiezan con "diag_"),
        # no una lista fija: con una lista a mano ya se quedaron fuera
        # fecha/técnico/módulos/resumen, que se quedaban con los datos del
        # diagnóstico anterior. Así no se puede volver a olvidar ninguna
        # cuando se agregue un campo nuevo a futuro.
        for clave in list(st.session_state.keys()):
            if clave.startswith(f"{PREFIJO}_"):
                del st.session_state[clave]
        st.rerun()


def _pestana_nuevo() -> None:
    guardado = st.session_state.get(GUARDADA)
    if guardado:
        _diagnostico_guardado(guardado)
        return

    styles.seccion("1 · Cliente")
    id_cliente = bloque_cliente(PREFIJO)

    st.divider()
    folio, fecha, tecnico, num_modulos, id_vehiculo = _bloque_folio_vehiculo(id_cliente)

    st.divider()
    _bloque_codigos()

    st.divider()
    otros_modulos, resumen = _bloque_cierre()

    st.divider()
    faltantes = []
    if id_cliente is None:
        faltantes.append("el cliente")
    if id_vehiculo is None:
        faltantes.append("el vehículo")
    if not _borrador():
        faltantes.append("al menos un código")
    if not resumen.strip():
        faltantes.append("el resumen y recomendaciones")

    if faltantes:
        st.caption(f"Para guardar falta: {', '.join(faltantes)}.")

    if st.button("Guardar diagnóstico", type="primary", disabled=bool(faltantes),
                 key=f"{PREFIJO}_guardar"):
        try:
            nuevo = db.crear_diagnostico(
                id_cliente=id_cliente,
                id_vehiculo=id_vehiculo,
                fecha=fecha.isoformat(),
                codigos=_borrador(),
                tecnico=tecnico,
                num_modulos=int(num_modulos) or None,
                otros_modulos=otros_modulos,
                resumen=resumen,
            )
        except Exception as error:
            st.error(f"No se pudo guardar el diagnóstico: {error}")
            return
        st.session_state[GUARDADA] = nuevo
        st.rerun()


# ---------------------------------------------------------------------------
# Consultar
# ---------------------------------------------------------------------------

def _detalle(diagnostico: dict) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric("Folio", diagnostico["id_diagnostico"])
    col2.metric("Fecha", db.formato_fecha(diagnostico["fecha"]))
    col3.metric("Códigos", len(diagnostico["codigos"]))

    st.markdown(
        f"**Cliente:** {diagnostico['cliente']}"
        + (f" · 📞 {diagnostico['telefono']}" if diagnostico["telefono"] else "")
    )
    st.markdown(
        f"**Vehículo:** {diagnostico['marca']} {diagnostico['modelo'] or ''} "
        f"{diagnostico['anio'] or ''} · {diagnostico['color'] or 'sin color'}"
    )
    if diagnostico["tecnico"]:
        st.markdown(f"**Atendió:** {diagnostico['tecnico']}")

    folio = diagnostico["id_diagnostico"]
    descargas.boton_pdf(
        folio,
        generar=lambda: descargas.pdf_diagnostico(folio),
        nombre_archivo=diagnostico_pdf.nombre_archivo(folio),
        etiqueta_descarga="📄 Descargar reporte en PDF",
        etiqueta_preparar="📄 Preparar reporte en PDF",
    )

    st.dataframe(
        pd.DataFrame([
            {
                "Sistema": c["sistema"],
                "Código": c["codigo"],
                "Descripción del escáner": c["descripcion"],
                "Qué significa": c["significado"],
                "Gravedad": GRAVEDAD_ETIQUETA.get(c["gravedad"], c["gravedad"]),
            }
            for c in diagnostico["codigos"]
        ]),
        width="stretch", hide_index=True,
    )

    if diagnostico["otros_modulos"]:
        st.markdown(f"**Otros módulos:** {diagnostico['otros_modulos']}")
    if diagnostico["resumen"]:
        st.markdown("**Resumen y recomendaciones:**")
        st.markdown(diagnostico["resumen"])


# ---------------------------------------------------------------------------
# Edición de un diagnóstico
# ---------------------------------------------------------------------------

def _etiqueta_vehiculo(v: dict) -> str:
    return f"{db.descripcion_vehiculo(v)} — {v['cliente']}"


def _editar_cabecera_diagnostico(diagnostico: dict) -> None:
    st.markdown("##### Cliente, vehículo y datos generales")

    clientes = db.listar_clientes()
    ops_cliente = {f"#{c['id_cliente']} — {c['nombre']}": c["id_cliente"]
                   for c in clientes}
    etiquetas_cliente = list(ops_cliente)
    actual_cliente = next(
        (i for i, e in enumerate(etiquetas_cliente)
         if ops_cliente[e] == diagnostico["id_cliente"]), 0
    )

    vehiculos = db.listar_vehiculos()
    ops_veh = {_etiqueta_vehiculo(v): v["id_vehiculo"] for v in vehiculos}
    etiquetas_veh = list(ops_veh)
    actual_veh = next(
        (i for i, e in enumerate(etiquetas_veh)
         if ops_veh[e] == diagnostico["id_vehiculo"]), None
    )

    folio = diagnostico["id_diagnostico"]
    with st.form(f"cabecera-diag-{folio}"):
        col1, col2 = st.columns([3, 1.5])
        etiqueta = col1.selectbox("Cliente", etiquetas_cliente, index=actual_cliente)
        fecha = col2.date_input(
            "Fecha", value=datetime.strptime(diagnostico["fecha"], "%Y-%m-%d").date(),
            format="DD/MM/YYYY",
        )
        etiqueta_veh = st.selectbox(
            "Vehículo", etiquetas_veh, index=actual_veh,
            placeholder="Elige un vehículo…",
            help="Se administran en la pantalla de Vehículos.",
        )

        col3, col4 = st.columns([2, 1])
        tecnico = col3.text_input("Atendió (técnico)",
                                  value=diagnostico["tecnico"] or "")
        num_modulos = col4.number_input(
            "Módulos analizados", min_value=0, max_value=99, step=1,
            value=diagnostico["num_modulos"] or 0)

        otros_modulos = st.text_area("Otros módulos revisados (opcional)",
                                     value=diagnostico["otros_modulos"] or "")
        resumen = st.text_area("Resumen y recomendaciones",
                               value=diagnostico["resumen"] or "", height=160)

        if st.form_submit_button("Guardar cambios"):
            if etiqueta_veh is None:
                st.error("El diagnóstico necesita un vehículo.")
                return
            db.actualizar_diagnostico(
                folio, ops_cliente[etiqueta], ops_veh[etiqueta_veh],
                fecha.isoformat(), tecnico=tecnico, num_modulos=int(num_modulos) or None,
                otros_modulos=otros_modulos, resumen=resumen,
            )
            st.success("Diagnóstico actualizado.")
            st.rerun()


def _editar_codigos_diagnostico(diagnostico: dict) -> None:
    st.markdown("##### Códigos identificados")
    st.caption(
        "Puedes cambiar cualquier dato directamente en la tabla, incluida la "
        "gravedad. Los cambios se guardan al pulsar el botón de abajo."
    )

    folio = diagnostico["id_diagnostico"]
    original = pd.DataFrame([
        {
            "#": c["linea"],
            "Sistema": c["sistema"],
            "Código": c["codigo"],
            "Descripción del escáner": c["descripcion"],
            "Qué significa": c["significado"],
            "Gravedad": c["gravedad"],
        }
        for c in diagnostico["codigos"]
    ])

    editado = st.data_editor(
        original,
        key=f"editor-diag-{folio}",
        width="stretch",
        hide_index=True,
        num_rows="fixed",
        disabled=["#"],
        column_config={
            "Gravedad": st.column_config.SelectboxColumn(options=db.GRAVEDADES),
        },
    )

    if st.button("Guardar cambios de los códigos", type="primary",
                 key=f"guardar-codigos-{folio}"):
        cambios = 0
        for codigo, (_, fila) in zip(diagnostico["codigos"], editado.iterrows()):
            nuevos = (fila["Sistema"], fila["Código"],
                     fila["Descripción del escáner"], fila["Qué significa"],
                     fila["Gravedad"])
            actuales = (codigo["sistema"], codigo["codigo"], codigo["descripcion"],
                       codigo["significado"], codigo["gravedad"])
            if nuevos != actuales:
                db.actualizar_diagnostico_codigo(
                    codigo["id_item"], fila["Código"],
                    fila["Descripción del escáner"], fila["Qué significa"],
                    fila["Gravedad"], sistema=fila["Sistema"])
                cambios += 1
        if cambios:
            st.success(f"{cambios} código(s) actualizado(s).")
            st.rerun()
        else:
            st.info("No hubo cambios que guardar.")

    st.divider()
    col1, col2 = st.columns([3, 1])
    lineas = {
        f"{c['linea']} — {c['codigo']} ({c['sistema']})": c["id_item"]
        for c in diagnostico["codigos"]
    }
    elegida = col1.selectbox("Quitar un código", list(lineas), index=None,
                             placeholder="Elige el código a quitar…",
                             key=f"quitar-diag-{folio}-{len(lineas)}")
    col2.write("")
    if elegida and col2.button("Quitar", key=f"btn-quitar-diag-{folio}"):
        try:
            db.eliminar_diagnostico_codigo(lineas[elegida])
        except ValueError as error:
            st.error(str(error))
        else:
            st.success("Código quitado; se renumeraron los demás.")
            st.rerun()

    st.divider()
    st.markdown("##### Agregar un código")
    version = st.session_state.get(f"codigo_version-{folio}", 0)
    clave = lambda nombre: f"agregar-{folio}-{nombre}-{version}"  # noqa: E731

    sistemas = list(dict.fromkeys(c["sistema"] for c in diagnostico["codigos"]))
    opciones_sistema = sistemas + ["+ Nuevo sistema…"]
    eleccion = st.selectbox("Sistema / módulo *", opciones_sistema,
                            index=len(opciones_sistema) - 1,
                            key=clave("sel_sistema"))
    if eleccion == "+ Nuevo sistema…":
        sistema_nuevo = st.text_input("Nombre del sistema *", key=clave("sistema"))
    else:
        sistema_nuevo = eleccion

    col1, col2 = st.columns([1, 3])
    codigo_nuevo = col1.text_input("Código *", key=clave("codigo"))
    descripcion_nueva = col2.text_input("Descripción del escáner *",
                                        key=clave("descripcion"))
    significado_nuevo = st.text_area("Qué significa *", key=clave("significado"),
                                     height=70)
    gravedad_nueva = st.selectbox("Gravedad", db.GRAVEDADES, index=1,
                                  key=clave("gravedad"))

    if st.button("Agregar código", type="primary", key=clave("agregar")):
        if not (sistema_nuevo.strip() and codigo_nuevo.strip()
                and descripcion_nueva.strip() and significado_nuevo.strip()):
            st.error("Completa sistema, código, descripción y qué significa.")
        else:
            db.agregar_diagnostico_codigo(folio, {
                "sistema": sistema_nuevo, "codigo": codigo_nuevo,
                "descripcion": descripcion_nueva, "significado": significado_nuevo,
                "gravedad": gravedad_nueva,
            })
            st.session_state[f"codigo_version-{folio}"] = version + 1
            st.success("Código agregado.")
            st.rerun()


def _panel_diagnostico(id_diagnostico: str) -> None:
    """Detalle y edición de un diagnóstico, en pestañas."""
    diagnostico = db.obtener_diagnostico(id_diagnostico)
    if diagnostico is None:
        st.error("El diagnóstico ya no existe.")
        return

    detalle, edicion = st.tabs(["Detalle", "Editar"])
    with detalle:
        _detalle(diagnostico)
    with edicion:
        _editar_cabecera_diagnostico(diagnostico)
        st.divider()
        _editar_codigos_diagnostico(diagnostico)
        st.divider()
        _eliminar_diagnostico(diagnostico)


def _eliminar_diagnostico(diagnostico: dict) -> None:
    """Pide confirmar antes de borrar, igual que `notas.py::_eliminar_nota`."""
    folio = diagnostico["id_diagnostico"]
    pendiente = st.session_state.get(CONFIRMAR_BORRADO)

    if pendiente != folio:
        if st.button("🗑️ Eliminar diagnóstico", key=f"pedir-borrar-{folio}"):
            st.session_state[CONFIRMAR_BORRADO] = folio
            st.rerun()
        return

    st.warning(
        f"Vas a eliminar el diagnóstico **{folio}** de "
        f"**{diagnostico['cliente']}**, con {len(diagnostico['codigos'])} "
        f"código(s). Esto no se puede deshacer."
    )
    col1, col2 = st.columns(2)
    if col1.button("Sí, eliminar definitivamente", type="primary",
                   key=f"confirmar-borrar-{folio}"):
        db.eliminar_diagnostico(folio)
        del st.session_state[CONFIRMAR_BORRADO]
        st.session_state["diag_eliminado"] = folio
        st.rerun()
    if col2.button("Cancelar", key=f"cancelar-borrar-{folio}"):
        del st.session_state[CONFIRMAR_BORRADO]
        st.rerun()


def _pestana_consultar() -> None:
    eliminado = st.session_state.pop("diag_eliminado", None)
    if eliminado:
        st.success(f"El diagnóstico {eliminado} fue eliminado.")

    busqueda = st.text_input(
        "Buscar", placeholder="Folio, cliente, marca o técnico…",
        key=f"{PREFIJO}_busqueda")

    diagnosticos = db.listar_diagnosticos(busqueda)
    if not diagnosticos:
        st.info("Ningún diagnóstico coincide con la búsqueda.")
        return

    st.metric("Diagnósticos", len(diagnosticos))

    st.dataframe(
        pd.DataFrame([
            {
                "Folio": d["id_diagnostico"],
                "Fecha": db.formato_fecha(d["fecha"]),
                "Cliente": d["cliente"],
                "Vehículo": f"{d['marca'] or ''} {d['modelo'] or ''}".strip()
                           or "—",
                "Códigos": d["num_codigos"],
                "Técnico": d["tecnico"] or "—",
            }
            for d in diagnosticos
        ]),
        width="stretch", hide_index=True,
    )

    st.divider()
    folio = st.selectbox(
        "Abrir un diagnóstico", [d["id_diagnostico"] for d in diagnosticos],
        index=None, placeholder="Elige un folio…", key=f"{PREFIJO}_abrir")
    if folio:
        _panel_diagnostico(folio)


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Diagnósticos con escáner")

    nuevo, consultar = st.tabs(["Nuevo diagnóstico", "Consultar"])
    with nuevo:
        _pestana_nuevo()
    with consultar:
        _pestana_consultar()
