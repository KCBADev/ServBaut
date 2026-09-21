"""
Pantalla de configuración: datos del taller, catálogos de referencia,
usuarios del equipo y respaldo de la base.

Solo los administradores pueden entrar. Hasta ahora el rol existía en la base
pero no restringía nada; aquí empieza a servir para algo.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import streamlit as st

import auth
import db
import exportar
import styles
from paginas import descargas

ROLES = ["admin", "operador"]


def _mi_cuenta() -> None:
    """
    Cambio de la propia contraseña.

    Vive aquí y no en la barra lateral: ahí quedaba entre los enlaces de
    navegación, donde se pica por error. Y se muestra a CUALQUIER usuario,
    aunque el resto de esta pantalla sea solo para administradores — mandar
    sobre la propia clave no es administrar la aplicación.
    """
    usuario = st.session_state.get("usuario") or {}
    if not usuario:
        return

    st.markdown(f"Sesión de **{usuario['usuario']}** · {usuario['rol']}")
    st.caption("Cambia tu contraseña. Te pide la actual aunque ya tengas la "
               "sesión abierta.")

    with st.form("cambiar_password"):
        actual = st.text_input("Contraseña actual", type="password")
        nueva = st.text_input("Contraseña nueva", type="password")
        confirmar = st.text_input("Confirmar contraseña nueva", type="password")
        guardar = st.form_submit_button("Cambiar contraseña")

    if not guardar:
        return

    if not all((actual, nueva, confirmar)):
        st.warning("Llena los tres campos.")
    elif nueva != confirmar:
        st.error("La contraseña nueva y su confirmación no coinciden.")
    elif len(nueva) < 8:
        st.error("La contraseña nueva debe tener al menos 8 caracteres.")
    else:
        with db.conectar() as conexion:
            # Se revalida la contraseña actual: tener la sesión abierta no basta
            # para poder cambiarla.
            if auth.autenticar(conexion, usuario["usuario"], actual) is None:
                st.error("La contraseña actual no es correcta.")
                return
            auth.cambiar_password(conexion, usuario["id_usuario"], nueva)
            conexion.commit()
        st.success("Contraseña actualizada.")


def _es_admin() -> bool:
    usuario = st.session_state.get("usuario") or {}
    return usuario.get("rol") == "admin"


# ---------------------------------------------------------------------------

def _datos_taller() -> None:
    st.caption(
        "Estos datos salen impresos en la nota que se le entrega al cliente."
    )
    taller = db.obtener_taller()

    with st.form("datos_taller"):
        col1, col2 = st.columns(2)
        nombre = col1.text_input("Nombre del taller *", value=taller["nombre"])
        subtitulo = col2.text_input(
            "Subtítulo del documento", value=taller.get("subtitulo") or "",
            placeholder="Ej. Nota de servicio")

        direccion = st.text_input(
            "Dirección", value=taller.get("direccion") or "",
            placeholder="Calle, número, colonia, ciudad")

        col3, col4, col5 = st.columns(3)
        telefono = col3.text_input("Teléfono", value=taller.get("telefono") or "")
        correo = col4.text_input("Correo", value=taller.get("correo") or "")
        rfc = col5.text_input("RFC", value=taller.get("rfc") or "")

        pie = st.text_input(
            "Pie de la nota", value=taller.get("pie_nota") or "",
            placeholder="Ej. Gracias por su preferencia.")

        if st.form_submit_button("Guardar datos del taller"):
            try:
                db.actualizar_taller(nombre, subtitulo, direccion, telefono,
                                     correo, rfc, pie)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success("Datos actualizados. Ya salen en las notas nuevas.")
                st.rerun()


def _catalogos() -> None:
    st.caption(
        "Marcas, categorías y acciones son conjuntos cerrados: al ser llaves "
        "foráneas impiden que un error de dedo cree «Suspención» y parta las "
        "gráficas en dos."
    )

    col1, col2, col3 = st.columns(3)

    with col1:
        marcas = db.listar_marcas()
        st.markdown(f"**Marcas** ({len(marcas)})")
        st.dataframe(pd.DataFrame({"Marca": marcas}), width="stretch",
                     hide_index=True, height=260)
        nueva = st.text_input("Agregar marca", key="cfg_marca")
        if st.button("Agregar", key="cfg_btn_marca") and nueva.strip():
            db.agregar_marca(nueva)
            st.success(f"Marca «{nueva.strip()}» agregada.")
            st.rerun()

    with col2:
        categorias = db.listar_categorias()
        st.markdown(f"**Categorías** ({len(categorias)})")
        st.dataframe(pd.DataFrame({"Categoría": categorias}), width="stretch",
                     hide_index=True, height=260)

    with col3:
        acciones = db.listar_acciones()
        st.markdown(f"**Acciones** ({len(acciones)})")
        st.dataframe(pd.DataFrame({"Acción": acciones}), width="stretch",
                     hide_index=True, height=260)

    st.info(
        "Las categorías y las acciones no se agregan desde aquí a propósito: "
        "cambiarlas altera cómo se agrupan todos los reportes históricos. "
        "Si necesitas una nueva, conviene decidirlo con calma."
    )


def _usuarios() -> None:
    usuarios = db.listar_usuarios()

    st.dataframe(
        pd.DataFrame([
            {
                "ID": u["id_usuario"],
                "Usuario": u["usuario"],
                "Rol": u["rol"],
                "Activo": "Sí" if u["activo"] else "No",
                "Creado": (u["creado_en"] or "")[:10],
                "Último acceso": u["ultimo_acceso"] or "nunca",
            }
            for u in usuarios
        ]),
        width="stretch", hide_index=True,
    )

    st.divider()
    st.markdown("##### Dar de alta a alguien del equipo")

    with st.form("alta_usuario"):
        col1, col2, col3 = st.columns([2, 2, 1.2])
        nombre = col1.text_input("Usuario *", placeholder="Sin espacios")
        clave = col2.text_input("Contraseña *", type="password",
                                placeholder="Mínimo 8 caracteres")
        rol = col3.selectbox("Rol *", ROLES, index=1)

        if st.form_submit_button("Crear usuario"):
            if not nombre.strip() or not clave:
                st.error("El usuario y la contraseña son obligatorios.")
            elif len(clave) < 8:
                st.error("La contraseña debe tener al menos 8 caracteres.")
            elif any(u["usuario"] == nombre.strip() for u in usuarios):
                st.error(f"Ya existe un usuario llamado «{nombre.strip()}».")
            else:
                with db.transaccion() as conexion:
                    auth.crear_usuario(conexion, nombre, clave, rol)
                st.success(f"Usuario «{nombre.strip()}» creado como {rol}.")
                st.rerun()

    st.divider()
    st.markdown("##### Cambiar rol o desactivar")
    st.caption(
        "Un usuario desactivado no puede entrar, pero se conserva para no "
        "perder el rastro de quién hizo qué."
    )

    opciones = {f"#{u['id_usuario']} — {u['usuario']} ({u['rol']})": u
                for u in usuarios}
    elegido = st.selectbox("Usuario", list(opciones), index=None,
                           placeholder="Elige un usuario…")
    if elegido is None:
        return

    u = opciones[elegido]
    col1, col2 = st.columns(2)

    with col1:
        nuevo_rol = st.selectbox("Rol", ROLES, index=ROLES.index(u["rol"]),
                                 key=f"rol-{u['id_usuario']}")
        if nuevo_rol != u["rol"] and st.button("Cambiar rol",
                                               key=f"btn-rol-{u['id_usuario']}"):
            try:
                db.cambiar_rol_usuario(u["id_usuario"], nuevo_rol)
            except ValueError as error:
                st.error(str(error))
            else:
                st.success(f"«{u['usuario']}» ahora es {nuevo_rol}.")
                st.rerun()

    with col2:
        etiqueta = "Desactivar" if u["activo"] else "Reactivar"
        if st.button(etiqueta, key=f"btn-activo-{u['id_usuario']}"):
            try:
                db.cambiar_estado_usuario(u["id_usuario"], not u["activo"])
            except ValueError as error:
                st.error(str(error))
            else:
                st.success(f"«{u['usuario']}» {etiqueta.lower()}do.")
                st.rerun()


def _exportar() -> None:
    st.caption(
        "Saca los datos para analizarlos fuera de la aplicación. "
        "La tabla de usuarios queda fuera a propósito: guarda hashes de "
        "contraseñas y no tiene nada que hacer en un reporte."
    )

    st.dataframe(exportar.resumen(), width="stretch", hide_index=True)

    st.warning(
        "**Power BI no abre archivos `.sql`.** Un volcado SQL es un guion de "
        "instrucciones, no una fuente de datos: hay que ejecutarlo primero en "
        "un servidor MySQL y luego conectar Power BI a ese servidor. "
        "Si lo que quieres es analizar y ya, baja el **CSV** o el **Excel**: "
        "Power BI los importa directo."
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.markdown("**CSV (recomendado)**")
        st.caption("Un archivo por tabla en un ZIP, con instrucciones y las "
                   "relaciones sugeridas. Power BI: Obtener datos → Carpeta.")
        st.download_button(
            "Descargar CSV", data=descargas.csv(),
            file_name=exportar.nombre_archivo("zip"), mime="application/zip",
            key="exp_csv")

    with col2:
        st.markdown("**Excel**")
        st.caption("Un libro con una hoja por tabla. Cómodo para revisar los "
                   "datos a ojo antes de cargarlos.")
        st.download_button(
            "Descargar Excel", data=descargas.excel(),
            file_name=exportar.nombre_archivo("xlsx"),
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="exp_xlsx")

    with col3:
        st.markdown("**SQL (MySQL)**")
        st.caption("Estructura y datos para levantar la base en un servidor. "
                   "Es el camino si la quieres viva y consultable.")
        st.download_button(
            "Descargar SQL", data=descargas.sql(),
            file_name=exportar.nombre_archivo("sql"), mime="text/plain",
            key="exp_sql")

    with col4:
        st.markdown("**Como tu hoja de siempre**")
        st.caption("La misma estructura de tu Excel: clientes y notas lado a "
                   "lado en una hoja, y los servicios desglosados en otra.")
        st.download_button(
            "Descargar en formato Excel del taller",
            data=descargas.original(),
            file_name=exportar.nombre_archivo("xlsx", "hoja"),
            mime="application/vnd.openxmlformats-officedocument."
                 "spreadsheetml.sheet",
            key="exp_original")

    with st.expander("Cómo quedan los importes"):
        st.markdown(
            "Los montos se guardan en **centavos como entero**, para que las "
            "sumas sean exactas — es lo que permite que el histórico cuadre "
            "al centavo. En la exportación cada columna `_centavos` viene "
            "acompañada de su versión `_pesos` ya dividida.\n\n"
            "En Power BI: **suma con las de centavos y muestra con las de "
            "pesos.** Si sumas pesos con decimales sobre miles de renglones, "
            "el redondeo de punto flotante te va a desviar el total."
        )


def _respaldo() -> None:
    st.caption(
        "La base guarda a tus clientes, sus vehículos y todo el histórico de "
        "notas. Es el archivo más valioso del proyecto y no se sube al "
        "repositorio, así que el respaldo depende de ti."
    )

    if not db.RUTA_DB.exists():
        st.error("No se encontró la base de datos.")
        return

    tamano = db.RUTA_DB.stat().st_size
    modificada = datetime.fromtimestamp(db.RUTA_DB.stat().st_mtime)

    col1, col2, col3 = st.columns(3)
    col1.metric("Archivo", db.RUTA_DB.name)
    col2.metric("Tamaño", f"{tamano / 1024:,.0f} KB")
    col3.metric("Última escritura", modificada.strftime("%Y-%m-%d %H:%M"))

    st.download_button(
        "Descargar respaldo de la base",
        # `db.bytes_respaldo()` y no `db.RUTA_DB.read_bytes()`: en modo WAL,
        # leer el archivo tal cual puede perderse escrituras confirmadas que
        # todavía viven solo en `taller.db-wal` sin fusionarse. Sin caché a
        # propósito: la base pesa unos cientos de KB, copiarla toma
        # milisegundos, y cachearla por la fecha de modificación del archivo
        # reintroduciría el mismo riesgo que esto corrige.
        data=db.bytes_respaldo(),
        file_name=f"taller-{datetime.now():%Y%m%d-%H%M}.db",
        mime="application/octet-stream",
        help="Guárdalo fuera de esta computadora.",
    )

    cuadre = db.verificar_cuadre()
    if cuadre["coinciden"] and not cuadre["notas_descuadradas"]:
        st.success(
            f"Integridad correcta: notas y partidas suman lo mismo "
            f"({db.formato_pesos(cuadre['total_notas_centavos'])})."
        )
    else:
        st.error(
            f"La base no cuadra: notas "
            f"{db.formato_pesos(cuadre['total_notas_centavos'])} contra "
            f"partidas {db.formato_pesos(cuadre['total_partidas_centavos'])}, "
            f"y {len(cuadre['notas_descuadradas'])} notas descuadradas."
        )


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Configuración")

    # Un operador no administra nada, pero sí manda sobre su propia clave:
    # se le muestra su cuenta y nada más.
    if not _es_admin():
        _mi_cuenta()
        st.divider()
        st.info(
            "El resto de la configuración es solo para administradores. "
            "Pídele a quien administre la aplicación que haga el cambio que "
            "necesitas."
        )
        return

    cuenta, taller, catalogos, usuarios, exportar_tab, respaldo = st.tabs(
        ["Mi cuenta", "Datos del taller", "Catálogos", "Usuarios", "Exportar",
         "Respaldo"])
    with cuenta:
        _mi_cuenta()
    with taller:
        _datos_taller()
    with catalogos:
        _catalogos()
    with usuarios:
        _usuarios()
    with exportar_tab:
        _exportar()
    with respaldo:
        _respaldo()
