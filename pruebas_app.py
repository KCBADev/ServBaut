"""
Prueba de humo de la interfaz — Servicio Bautista.

Usa AppTest, el harness oficial de Streamlit: ejecuta la app de verdad sin
navegador y permite comprobar que cada pantalla renderiza sin excepciones y
que el candado de autenticación funciona.

Se ejecuta contra taller.db en modo lectura; no escribe nada.

Uso:
    .venv\\Scripts\\python.exe pruebas_app.py
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from streamlit.testing.v1 import AppTest

import auth
import config
import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

RAIZ = Path(__file__).resolve().parent

fallos = 0
pruebas = 0

SESION = {"id_usuario": 1, "usuario": "admin", "rol": "admin"}


def comprobar(descripcion: str, condicion: bool, detalle: str = "") -> None:
    global fallos, pruebas
    pruebas += 1
    if condicion:
        print(f"  [OK] {descripcion}")
    else:
        fallos += 1
        print(f"  [!!] FALLÓ: {descripcion}")
        if detalle:
            print(f"       {detalle}")


def texto_de(app: AppTest) -> str:
    """Junta el texto visible de la app para poder buscar en él."""
    partes = []
    for coleccion in (app.title, app.header, app.subheader, app.markdown,
                      app.caption, app.info, app.warning, app.error,
                      app.success, app.metric):
        for elemento in coleccion:
            valor = getattr(elemento, "value", None)
            if isinstance(valor, str):
                partes.append(valor)
            label = getattr(elemento, "label", None)
            if isinstance(label, str):
                partes.append(label)
    return " | ".join(partes)


def sin_excepciones(app: AppTest) -> str:
    return "; ".join(str(e.value) for e in app.exception)


def _copiar_base_consistente(origen: Path, destino: Path) -> None:
    """
    Copia `origen` a `destino` usando el respaldo en caliente de SQLite.

    Un `shutil.copy2` directo copiaría solo el archivo `.db` principal: si
    hay escrituras recientes que todavía viven en `taller.db-wal` y no se han
    volcado ahí, esas filas se perderían en la copia. `Connection.backup()`
    copia el estado lógico de la base —lo que vería cualquier lectura nueva—,
    WAL incluido.
    """
    origen_con = sqlite3.connect(origen)
    destino_con = sqlite3.connect(destino)
    try:
        origen_con.backup(destino_con)
    finally:
        destino_con.close()
        origen_con.close()


def abrir(autenticado: bool = True) -> AppTest:
    """Arranca la app completa, opcionalmente ya autenticada."""
    app = AppTest.from_file("app.py", default_timeout=60)
    if autenticado:
        app.session_state.usuario = dict(SESION)
    app.run()
    return app


def abrir_pagina(modulo: str, rol: str = "admin") -> AppTest:
    """
    Ejecuta una sola pantalla de forma aislada.

    `switch_page` resuelve rutas de archivo y estas páginas se definen con
    funciones, no con scripts; y `from_function` copia solo el cuerpo de la
    función, sin los imports de su módulo. Por eso se arma un guion mínimo que
    importa la página y la invoca.
    """
    fuente = (
        "import sys\n"
        f"sys.path.insert(0, {str(RAIZ)!r})\n"
        f"from paginas import {modulo}\n"
        f"{modulo}.mostrar()\n"
    )
    app = AppTest.from_string(fuente, default_timeout=60)
    app.session_state.usuario = {**SESION, "rol": rol}
    app.run()
    return app


def _prueba_cambio_obligatorio() -> None:
    """
    Ejercita la pantalla que se interpone cuando la cuenta nace con una
    contraseña que la persona no eligió (`debe_cambiar_password = 1`): que
    bloquee la navegación, que rechace una contraseña demasiado corta sin
    apagar la bandera, y que una contraseña válida sí la apague y deje pasar.

    Corre sobre una base temporal aislada por la misma razón que
    `_prueba_diagnosticos_interaccion`: no tiene sentido dejar cuentas de
    prueba con contraseñas conocidas rondando ninguna base real.
    """
    print("\n--- Cambio de contraseña obligatorio (base temporal aislada) ---")
    original_ruta = db.RUTA_DB
    carpeta = tempfile.mkdtemp(prefix="pruebas_cambio_obligatorio_",
                               dir=config.ruta_temporal())
    db.RUTA_DB = Path(carpeta) / "prueba.db"
    try:
        db.inicializar_esquema()
        with db.transaccion() as c:
            id_usuario = auth.crear_usuario(
                c, "provisional", "ClaveProvisional123", rol="admin",
                debe_cambiar_password=True)

        sesion = {"id_usuario": id_usuario, "usuario": "provisional",
                  "rol": "admin", "debe_cambiar_password": True}
        app = AppTest.from_file("app.py", default_timeout=60)
        app.session_state.usuario = dict(sesion)
        app.run()
        comprobar("Arranca sin excepciones", not app.exception,
                  sin_excepciones(app))
        visible = texto_de(app)
        comprobar("Muestra la pantalla de cambio obligatorio",
                  "Elige una contraseña" in visible)
        comprobar("Bloquea la navegación: no se llega al contenido",
                  "Dashboard" not in visible and "Catálogo" not in visible,
                  visible[:200])

        print("\n--- Rechaza una contraseña demasiado corta ---")
        campos = app.text_input
        campos[0].set_value("corta")
        campos[1].set_value("corta")
        app = app.button[0].click().run()
        comprobar("Muestra el error de longitud",
                  any("al menos 8 caracteres" in e.value for e in app.error))
        with db.conectar() as c:
            fila = c.execute(
                "SELECT debe_cambiar_password FROM usuarios WHERE id_usuario = ?",
                (id_usuario,)).fetchone()
        comprobar("La bandera sigue activa en la base",
                  bool(fila["debe_cambiar_password"]))

        print("\n--- Acepta una contraseña válida y deja pasar ---")
        campos = app.text_input
        campos[0].set_value("ClaveNuevaSegura456")
        campos[1].set_value("ClaveNuevaSegura456")
        app = app.button[0].click().run()
        comprobar("Confirma el cambio", any("actualizada" in s.value
                                            for s in app.success))
        comprobar("Ya no pide cambiar la contraseña: llega a la navegación",
                  not app.session_state.usuario["debe_cambiar_password"])
        with db.conectar() as c:
            fila = c.execute(
                "SELECT debe_cambiar_password FROM usuarios WHERE id_usuario = ?",
                (id_usuario,)).fetchone()
        comprobar("Y la bandera queda apagada en la base",
                  not fila["debe_cambiar_password"])
        with db.conectar() as c:
            comprobar("La contraseña nueva sí funciona",
                      auth.autenticar(c, "provisional",
                                      "ClaveNuevaSegura456") is not None)
    finally:
        db.RUTA_DB = original_ruta
        shutil.rmtree(carpeta, ignore_errors=True)


def _prueba_limite_de_acceso_sobrevive_recarga() -> None:
    """
    Prueba el motivo por el que el límite de intentos se movió a la base: que
    NO se reinicie con una «recarga de la página».

    `AppTest.from_file` arma una ejecución nueva de `app.py` cada vez que se
    llama, exactamente como recargar la pestaña en un navegador de verdad —
    empieza con `st.session_state` vacío. Si el límite siguiera viviendo ahí
    (como antes), una segunda instancia como esta lo encontraría en cero.
    Encontrarlo activo demuestra que la autoridad es la base, no la sesión.
    """
    print("\n--- Límite de acceso: sobrevive a una recarga (base aislada) ---")
    original_ruta = db.RUTA_DB
    carpeta = tempfile.mkdtemp(prefix="pruebas_limite_acceso_",
                               dir=config.ruta_temporal())
    db.RUTA_DB = Path(carpeta) / "prueba.db"
    try:
        db.inicializar_esquema()
        with db.transaccion() as c:
            auth.crear_usuario(c, "candado", "ClaveCorrecta123", rol="admin")

        maximo = config.max_intentos()
        app = AppTest.from_file("app.py", default_timeout=60)
        app.run()
        for _ in range(maximo + 1):
            app.text_input[0].set_value("candado")
            app.text_input[1].set_value("clave-equivocada")
            app = app.button[0].click().run()
        comprobar(f"El intento {maximo + 1} ya avisa que hay que esperar, "
                  f"sin esperar a uno más",
                  any("Espera" in e.value for e in app.error),
                  sin_excepciones(app))

        print("\n--- «Recarga»: una instancia nueva de la app ---")
        recarga = AppTest.from_file("app.py", default_timeout=60)
        recarga.run()
        recarga.text_input[0].set_value("candado")
        recarga.text_input[1].set_value("ClaveCorrecta123")  # la correcta
        recarga = recarga.button[0].click().run()
        comprobar("El bloqueo sigue activo aunque la contraseña ahora sí sea "
                  "correcta y la sesión sea otra",
                  any("Espera" in e.value for e in recarga.error))
        comprobar("Y sigue sin autenticarse",
                  "usuario" not in recarga.session_state)

        print("\n--- Tras limpiar el bloqueo, sí deja entrar ---")
        db.limpiar_intentos("candado")
        tercera = AppTest.from_file("app.py", default_timeout=60)
        tercera.run()
        tercera.text_input[0].set_value("candado")
        tercera.text_input[1].set_value("ClaveCorrecta123")
        tercera = tercera.button[0].click().run()
        comprobar("Con el bloqueo limpio, la contraseña correcta sí entra",
                  "usuario" in tercera.session_state,
                  sin_excepciones(tercera))
    finally:
        db.RUTA_DB = original_ruta
        shutil.rmtree(carpeta, ignore_errors=True)


def _prueba_diagnosticos_interaccion() -> None:
    """
    Ejercita de verdad el clic de «Agregar código» en Diagnósticos con
    escáner — la interacción exacta que causó un bug real
    (`StreamlitWidgetAlreadyInstantiatedError`) el día que se agregó la
    pantalla, y que ni la lectura de código ni el resto de estas pruebas
    (que solo abren la pantalla en frío) habría atrapado.

    Corre sobre una base TEMPORAL, nunca sobre `taller.db`: una prueba que
    guarda un diagnóstico de verdad tiene que poder repetirse sin ir
    dejando folios de prueba en la base real del taller cada vez que se
    corre. `db.RUTA_DB` se redirige mientras dura esta función y se
    restaura siempre, para que el resto de la suite (que sí corre contra la
    base real) no quede afectado.
    """
    print("\n--- Diagnósticos: flujo completo (base temporal aislada) ---")
    original_ruta = db.RUTA_DB
    # El temporal del sistema, salvo que TALLER_TMP diga otra cosa. Antes esto
    # forzaba la carpeta de la base (D:) porque C: andaba muy justo de espacio,
    # pero atar la suite al disco de datos es justo lo que le impedía correr en
    # el CI o en un contenedor, donde no existe ningún D:. La base de prueba
    # pesa unos cientos de KB y `pruebas_datos.py` lleva tiempo creando la suya
    # en el temporal del sistema sin ningún problema.
    carpeta = tempfile.mkdtemp(prefix="pruebas_diagnosticos_",
                               dir=config.ruta_temporal())
    db.RUTA_DB = Path(carpeta) / "prueba.db"
    try:
        db.inicializar_esquema()
        db.sembrar_marcas()
        with db.transaccion() as c:
            c.execute("INSERT INTO categorias (nombre) VALUES ('Motor')")
            c.execute("INSERT INTO acciones (nombre) VALUES ('Reemplazo')")
        id_cliente = db.crear_cliente("Cliente de prueba", "3312345678")
        db.crear_vehiculo(id_cliente, "Jeep", "Patriot", 2020, "Negro")

        app = abrir_pagina("diagnosticos")
        comprobar("Diagnósticos abre sin excepciones sobre la base aislada",
                  not app.exception, sin_excepciones(app))

        selector_cliente = next(
            sb for sb in app.selectbox if (sb.label or "").startswith("Cliente"))
        etiqueta = next(o for o in selector_cliente.options if "prueba" in o.lower())
        app = selector_cliente.set_value(etiqueta).run()
        comprobar("Elegir el cliente no truena",
                  not app.exception, sin_excepciones(app))

        selector_vehiculo = next(
            sb for sb in app.selectbox if (sb.label or "").startswith("Vehículo"))
        app = selector_vehiculo.set_value(list(selector_vehiculo.options)[0]).run()
        comprobar("Elegir el vehículo no truena",
                  not app.exception, sin_excepciones(app))

        app.text_input(key="diag_sistema_nuevo_0").set_value("Motor")
        app.text_input(key="diag_codigo_0").set_value("P0135")
        app.text_input(key="diag_descripcion_0").set_value("Descripción de prueba")
        app.text_area(key="diag_significado_0").set_value("Significado de prueba")
        app = app.button(key="diag_agregar_codigo_0").click().run()
        comprobar("Agregar el primer código no truena (el bug real de hoy)",
                  not app.exception, sin_excepciones(app))

        selectores_sistema = [
            sb for sb in app.selectbox if (sb.label or "").startswith("Sistema")]
        comprobar("El sistema queda preseleccionado para el siguiente código",
                  bool(selectores_sistema) and selectores_sistema[0].value == "Motor",
                  str([sb.value for sb in selectores_sistema]))

        app.text_input(key="diag_codigo_1").set_value("P0401")
        app.text_input(key="diag_descripcion_1").set_value("Segunda descripción")
        app.text_area(key="diag_significado_1").set_value("Segundo significado")
        app = app.button(key="diag_agregar_codigo_1").click().run()
        comprobar("Agregar un segundo código del mismo sistema no truena",
                  not app.exception, sin_excepciones(app))

        quitar = next(
            sb for sb in app.selectbox if (sb.label or "") == "Quitar renglón")
        app = quitar.set_value(1).run()
        boton_quitar = next(b for b in app.button if b.label == "Quitar")
        app = boton_quitar.click().run()
        comprobar("Quitar un renglón no truena", not app.exception, sin_excepciones(app))

        app.text_area(key="diag_resumen").set_value("Resumen de prueba.")
        app.run()
        boton_guardar = next(b for b in app.button if b.label == "Guardar diagnóstico")
        comprobar("El botón de guardar se habilita con los datos completos",
                  not boton_guardar.disabled)
        app = boton_guardar.click().run()
        comprobar("Guardar el diagnóstico no truena", not app.exception, sin_excepciones(app))

        exito = [s.value for s in app.success]
        comprobar("Muestra el mensaje de éxito con el folio",
                  bool(exito) and "guardado" in exito[0].lower(), str(exito))

        # El PDF se pide en dos pasos: primero «Preparar», y solo entonces
        # aparece la descarga. Así abrir un documento guardado no levanta un
        # Chromium en cada redibujado (ver `descargas.boton_pdf`).
        preparar = next((b for b in app.button if "Preparar" in b.label), None)
        comprobar("Ofrece preparar el reporte en PDF (sin generarlo de entrada)",
                  preparar is not None, str([b.label for b in app.button]))
        comprobar("Y todavía no hay botón de descarga",
                  not app.download_button)
        if preparar is not None:
            app = preparar.click().run()
            etiquetas_pdf = [b.label for b in app.download_button]
            comprobar("Tras prepararlo, ofrece descargar el reporte en PDF",
                      any("PDF" in e for e in etiquetas_pdf), str(etiquetas_pdf))

        if exito:
            folio = re.search(r"DX-\d+", exito[0]).group(0)
            import diagnostico_pdf
            pdf = diagnostico_pdf.generar(folio)
            comprobar(f"El PDF se genera de verdad ({len(pdf)} bytes)",
                      len(pdf) > 10_000)

        boton_otro = next(b for b in app.button if b.label == "Capturar otro diagnóstico")
        app = boton_otro.click().run()
        comprobar("«Capturar otro diagnóstico» no truena",
                  not app.exception, sin_excepciones(app))

        resumen_vacio = next(
            (t for t in app.text_area if (t.label or "").startswith("Resumen")), None)
        comprobar("El resumen queda en blanco para el siguiente diagnóstico "
                  "(no el del anterior)",
                  resumen_vacio is not None and not resumen_vacio.value,
                  repr(resumen_vacio.value if resumen_vacio else None))

        fecha_widget = next(
            (d for d in app.date_input if (d.label or "").startswith("Fecha")), None)
        comprobar("La fecha vuelve a hoy",
                  fecha_widget is not None and fecha_widget.value == date.today(),
                  str(fecha_widget.value if fecha_widget else None))
    finally:
        db.RUTA_DB = original_ruta
        shutil.rmtree(carpeta, ignore_errors=True)


def main() -> None:
    if not db.RUTA_DB.exists():
        print("No existe taller.db. Corre primero cargar_datos.py")
        sys.exit(1)

    # Se corre sobre una COPIA temporal, nunca sobre taller.db directamente.
    # Antes bastaba con que las pantallas fueran de solo lectura; ahora
    # app.py prepara la base sola al arrancar (crea el esquema si falta,
    # sella la version, aplica migraciones automaticas como la v9), y eso
    # si escribe. Correr esta suite no debe ser la primera vez que
    # taller.db se migra -- eso le toca al arranque real de la app.
    original_ruta = db.RUTA_DB
    carpeta = tempfile.mkdtemp(prefix="pruebas_app_", dir=config.ruta_temporal())
    copia = Path(carpeta) / "taller.db"
    _copiar_base_consistente(original_ruta, copia)
    db.RUTA_DB = copia
    try:
        print("\n--- El candado de autenticación ---")
        app = abrir(autenticado=False)
        comprobar("La app arranca sin excepciones", not app.exception, sin_excepciones(app))
        visible = texto_de(app)
        comprobar("Sin sesión se muestra la pantalla de acceso",
                  "Servicio Bautista" in visible)
        comprobar("Sin sesión NO se llega al contenido de la app",
                  "Dashboard" not in visible and "Catálogo" not in visible,
                  visible[:200])
        comprobar("Se piden usuario y contraseña", len(app.text_input) == 2)
        comprobar("La pantalla de acceso trae el fondo animado",
                  any("#lluvia" in m.value for m in app.markdown))

        print("\n--- Rechazo de credenciales incorrectas ---")
        app.text_input[0].set_value("admin")
        app.text_input[1].set_value("clave-incorrecta")
        app.button[0].click().run()
        comprobar("Rechaza la contraseña incorrecta", len(app.error) > 0)
        comprobar("El mensaje no revela si el usuario existe",
                  any("Usuario o contraseña incorrectos" in e.value for e in app.error))
        comprobar("Sigue sin haber sesión", "usuario" not in app.session_state)

        _prueba_cambio_obligatorio()
        _prueba_limite_de_acceso_sobrevive_recarga()

        print("\n--- Con sesión abierta ---")
        app = abrir()
        comprobar("Renderiza sin excepciones", not app.exception, sin_excepciones(app))
        comprobar("Aparece el botón de cerrar sesión",
                  any("Cerrar sesión" in b.label for b in app.button))
        # La barra lateral ya no dice con qué cuenta se entró: ahí va el logo del
        # taller. El dato no se perdió, se mudó a Configuración → Mi cuenta, y
        # ahí es donde se comprueba — saber con qué cuenta estás sigue
        # importando, solo que ya no ocupa lugar en la navegación.
        app_cuenta = abrir_pagina("configuracion")
        comprobar("Configuración identifica al usuario de la sesión",
                  "admin" in texto_de(app_cuenta), texto_de(app_cuenta)[:200])

        # El fondo animado es solo de la pantalla de acceso: el resto de la app
        # tiene su propio lienzo oscuro y no debe heredar la animación.
        comprobar("El fondo animado NO se filtra al resto de la app",
                  not any("#lluvia" in m.value for m in app.markdown))

        print("\n--- Expiración de sesión ---")
        comprobar("Una sesión recién abierta queda con sus dos relojes",
                  "inicio_sesion" in app.session_state
                  and "ultima_actividad" in app.session_state)

        app_inactiva = abrir()
        # Retrocede el reloj de actividad más allá del límite de inactividad,
        # sin tocar el de duración absoluta: así se aísla el motivo exacto
        # por el que se cierra.
        app_inactiva.session_state.ultima_actividad = (
            datetime.now(timezone.utc)
            - timedelta(minutes=config.minutos_inactividad() + 1))
        app_inactiva = app_inactiva.run()
        comprobar("Por inactividad, cierra la sesión sola",
                  "usuario" not in app_inactiva.session_state)
        comprobar("Y vuelve a la pantalla de acceso",
                  len(app_inactiva.text_input) == 2)
        comprobar("Avisa por qué se cerró",
                  any("venció por inactividad" in i.value
                      for i in app_inactiva.info))

        app_vencida = abrir()
        # Aquí al revés: la actividad es reciente (justo ahora), pero el
        # inicio de la sesión es de hace más de config.horas_sesion() — la
        # tablet que nunca se apaga y nunca deja de tocarse.
        app_vencida.session_state.inicio_sesion = (
            datetime.now(timezone.utc)
            - timedelta(hours=config.horas_sesion() + 1))
        app_vencida.session_state.ultima_actividad = datetime.now(timezone.utc)
        app_vencida = app_vencida.run()
        comprobar("Por duración máxima, cierra la sesión aunque siga activa",
                  "usuario" not in app_vencida.session_state)

        app_vigente = abrir()
        app_vigente.session_state.ultima_actividad = (
            datetime.now(timezone.utc) - timedelta(minutes=1))
        app_vigente = app_vigente.run()
        comprobar("Dentro de los límites, la sesión sigue viva",
                  "usuario" in app_vigente.session_state)

        print("\n--- Cada pantalla renderiza ---")
        for modulo, esperado in (
            ("dashboard", "Dashboard"),
            ("cotizaciones", "Cotizaciones"),
            ("crear_nota", "Crear nota"),
            ("notas", "Notas de servicio"),
            ("diagnosticos", "Diagnósticos con escáner"),
            ("vehiculos", "Vehículos"),
            ("clientes", "Clientes"),
            ("catalogo", "Catálogo"),
            ("reportes", "Reportes"),
            ("configuracion", "Configuración"),
        ):
            app = abrir_pagina(modulo)
            detalle = sin_excepciones(app)
            comprobar(f"{esperado}: sin excepciones", not app.exception, detalle)
            comprobar(f"{esperado}: muestra su título",
                      any(esperado in t.value for t in app.title), texto_de(app)[:200])

        print("\n--- Los datos reales llegan a las pantallas ---")
        # Se compara contra la base EN VIVO, no contra un número fijo del
        # histórico: en cuanto el taller empiece a operar de verdad, cada cliente
        # o nota nueva haría que un número mágico fallara con una falsa alarma.
        # Lo que importa comprobar es que la pantalla y la base dicen lo mismo.
        app = abrir_pagina("clientes")
        metricas = {m.label: m.value for m in app.metric}
        total_clientes = len(db.listar_clientes())
        comprobar(f"Clientes muestra el total real ({metricas.get('Clientes encontrados')} "
                  f"de {total_clientes})",
                  metricas.get("Clientes encontrados") == str(total_clientes),
                  str(metricas))

        app = abrir_pagina("catalogo")
        metricas = {m.label: m.value for m in app.metric}
        total_conceptos = len(db.listar_catalogo())
        comprobar(f"Catálogo muestra el total real ({metricas.get('Conceptos')} "
                  f"de {total_conceptos})",
                  metricas.get("Conceptos") == str(total_conceptos), str(metricas))

        app = abrir_pagina("notas")
        metricas = {m.label: m.value for m in app.metric}
        total_notas = len(db.listar_notas())
        facturado_real = db.formato_pesos(
            db.verificar_cuadre()["total_notas_centavos"])
        comprobar(f"Notas muestra el total real ({metricas.get('Notas')} "
                  f"de {total_notas})",
                  metricas.get("Notas") == str(total_notas), str(metricas))
        comprobar(f"Notas muestra el importe real ({metricas.get('Facturado')} "
                  f"vs {facturado_real})",
                  metricas.get("Facturado") == facturado_real, str(metricas))

        app = abrir_pagina("vehiculos")
        metricas = {m.label: m.value for m in app.metric}
        vehiculos_reales = db.listar_vehiculos()
        sin_servicio_real = sum(1 for v in vehiculos_reales if not v["num_notas"])
        comprobar(f"Vehículos muestra el total real ({metricas.get('Vehículos')} "
                  f"de {len(vehiculos_reales)})",
                  metricas.get("Vehículos") == str(len(vehiculos_reales)),
                  str(metricas))
        comprobar(f"Y cuenta bien los que no tienen servicios todavía "
                  f"({metricas.get('Sin servicios')} de {sin_servicio_real})",
                  metricas.get("Sin servicios") == str(sin_servicio_real),
                  str(metricas))

        # La captura sigue el orden de las columnas de la hoja del taller.
        app = abrir_pagina("crear_nota")
        visible = texto_de(app)
        for bloque in ("1 · Cliente", "2 · Nota y vehículo",
                       "3 · Servicios y productos", "4 · Totales"):
            comprobar(f"Crear nota trae el bloque «{bloque}»",
                      bloque in visible, visible[:300])
        comprobar("Y ofrece la casilla de IVA",
                  any("Aplicar IVA" in (c.label or "") for c in app.checkbox),
                  str([c.label for c in app.checkbox]))

        # Mismo formulario que «Crear nota», sin folio: es un presupuesto.
        app = abrir_pagina("cotizaciones")
        visible = texto_de(app)
        comprobar("Cotizaciones ofrece capturar una nueva",
                  "1 · Cliente" in visible, visible[:300])
        comprobar("Y no le pide folio al cliente (a diferencia de Crear nota)",
                  "ID_N" not in visible)
        comprobar("Trae las pestañas de captura y consulta",
                  {"Nueva cotización", "Consultar"} <= {t.label for t in app.tabs},
                  str([t.label for t in app.tabs]))

        # Reporte de escáner: mismo cliente/vehículo que una nota, pero sin
        # dinero — la lista de códigos y el resumen se llenan a mano.
        app = abrir_pagina("diagnosticos")
        visible = texto_de(app)
        comprobar("Diagnósticos trae las pestañas de captura y consulta",
                  {"Nuevo diagnóstico", "Consultar"} <= {t.label for t in app.tabs},
                  str([t.label for t in app.tabs]))
        comprobar("Y no le pide dinero al cliente (no es una nota ni cotización)",
                  "IVA" not in visible and "Subtotal" not in visible, visible[:300])

        app = abrir_pagina("configuracion")
        comprobar("Configuración deja entrar a un administrador",
                  not any("solo para administradores" in e.value for e in app.error),
                  texto_de(app)[:200])

        comprobar("Y le ofrece cambiar su propia contraseña",
                  any("Contraseña actual" in (t.label or "")
                      for t in app.text_input),
                  str([t.label for t in app.text_input]))

        # El rol restringe lo que debe restringir: un operador no administra la
        # aplicación, pero sí manda sobre su propia clave. Lo segundo importa
        # tanto como lo primero — si no, se queda sin poder cambiarla.
        app = abrir_pagina("configuracion", rol="operador")
        visible = texto_de(app)
        comprobar("Un operador sí puede cambiar su propia contraseña",
                  any("Contraseña actual" in (t.label or "")
                      for t in app.text_input),
                  str([t.label for t in app.text_input]))
        comprobar("Pero se le avisa que el resto es de administradores",
                  "solo para administradores" in visible, visible[:200])
        comprobar("Y no alcanza ninguna pestaña de administración",
                  not any(t.label in {"Datos del taller", "Catálogos", "Usuarios",
                                      "Exportar", "Respaldo"}
                          for t in app.tabs),
                  str([t.label for t in app.tabs]))

        print("\n--- Abrir una nota: detalle, edición y PDF ---")
        app = abrir_pagina("notas")
        selector = next((s for s in app.selectbox
                         if "Abrir una nota" in (s.label or "")), None)
        comprobar("Existe el selector para abrir una nota", selector is not None)

        if selector is not None:
            app = selector.set_value("N-016").run()
            comprobar("El panel de la nota renderiza sin excepciones",
                      not app.exception, sin_excepciones(app))

            metricas = {m.label: m.value for m in app.metric}
            comprobar(f"Muestra el folio ({metricas.get('Folio')})",
                      metricas.get("Folio") == "N-016")
            comprobar(f"Muestra el total ({metricas.get('Total')})",
                      metricas.get("Total") == "$13,936.00")
            comprobar(f"Muestra el estado ({metricas.get('Estado')})",
                      metricas.get("Estado") in db.ESTADOS)
            comprobar(f"Muestra el saldo ({metricas.get('Saldo')})",
                      metricas.get("Saldo") is not None)
            comprobar("Ofrece cambiar el estado del trabajo",
                      any("Estado del trabajo" in (s.label or "")
                          for s in app.selectbox))

            visible = texto_de(app)
            comprobar("Confirma que el total cuadra con las partidas",
                      "cuadra con la suma" in visible, visible[-300:])

            etiquetas = [b.label for b in app.button]
            comprobar("Ofrece guardar los cambios de las partidas",
                      any("Guardar cambios de las partidas" in e for e in etiquetas),
                      str(etiquetas))
            comprobar("Ofrece guardar cliente y vehículo",
                      any("Guardar cliente y vehículo" in e for e in etiquetas),
                      str(etiquetas))
            comprobar("Ofrece eliminar la nota",
                      any("Eliminar esta nota" in e for e in etiquetas),
                      str(etiquetas))

            # El botón de eliminar debe pedir confirmación, no borrar de inmediato.
            eliminar = next(b for b in app.button if "Eliminar esta nota" in b.label)
            app = eliminar.click().run()
            comprobar("Eliminar pide confirmación antes de borrar",
                      any("no se puede deshacer" in w.value.lower()
                          for w in app.warning), texto_de(app)[-300:])
            comprobar("Y ofrece cancelar",
                      any("Cancelar" in b.label for b in app.button))
            comprobar("La nota sigue existiendo mientras no se confirme",
                      db.obtener_nota("N-016") is not None)

        print("\n--- Abrir una cotización: detalle y PDF ---")
        app = abrir_pagina("cotizaciones")
        selector = next((s for s in app.selectbox
                         if "Abrir una cotización" in (s.label or "")), None)
        comprobar("Existe el selector para abrir una cotización",
                  selector is not None)

        # La fila que arma "Consultar" para la tabla no trae teléfono, placas ni
        # renglones (eso es lo que causaba el KeyError al abrir el detalle); esta
        # prueba abre una cotización real de punta a punta para no dejar ese
        # camino sin cubrir otra vez.
        cotizaciones_reales = db.listar_cotizaciones()
        if selector is not None and cotizaciones_reales:
            folio = cotizaciones_reales[0]["id_cotizacion"]
            app = selector.set_value(folio).run()
            comprobar(f"El detalle de la cotización renderiza sin excepciones "
                      f"({folio})", not app.exception, sin_excepciones(app))

            metricas = {m.label: m.value for m in app.metric}
            comprobar(f"Muestra el folio ({metricas.get('Folio')})",
                      metricas.get("Folio") == folio)
            comprobar(f"Muestra el estado ({metricas.get('Estado')})",
                      metricas.get("Estado") in db.ESTADOS_COTIZACION)

            # Abrir el detalle NO debe armar el PDF: solo ofrecer prepararlo. Es
            # lo que evita esperar ~2 s (un Chromium) cada vez que se consulta
            # una cotización guardada.
            comprobar("Abrir el detalle no genera el PDF de entrada",
                      not app.download_button)
            preparar = next((b for b in app.button if "Preparar" in b.label), None)
            comprobar("Ofrece preparar la cotización en PDF",
                      preparar is not None, str([b.label for b in app.button]))
            if preparar is not None:
                app = preparar.click().run()
                etiquetas_pdf = [b.label for b in app.download_button]
                comprobar("Tras prepararla, ofrece descargar la cotización en PDF",
                          any("Descargar cotización en PDF" in e
                              for e in etiquetas_pdf),
                          str(etiquetas_pdf))

        _prueba_diagnosticos_interaccion()

        print("\n--- Cerrar sesión ---")
        app = abrir()
        for boton in app.button:
            if "Cerrar sesión" in boton.label:
                boton.click().run()
                break
        comprobar("Cerrar sesión limpia la sesión", "usuario" not in app.session_state)
        comprobar("Y devuelve a la pantalla de acceso", len(app.text_input) == 2)

        print()
        print("=" * 74)
        if fallos:
            print(f"{fallos} de {pruebas} pruebas FALLARON.")
        else:
            print(f"Las {pruebas} pruebas pasaron.")
        print("=" * 74)
        sys.exit(1 if fallos else 0)
    finally:
        db.RUTA_DB = original_ruta
        shutil.rmtree(carpeta, ignore_errors=True)


if __name__ == "__main__":
    main()
