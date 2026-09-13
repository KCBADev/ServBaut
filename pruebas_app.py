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

import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest

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


def main() -> None:
    if not db.RUTA_DB.exists():
        print("No existe taller.db. Corre primero cargar_datos.py")
        sys.exit(1)

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

    print("\n--- Con sesión abierta ---")
    app = abrir()
    comprobar("Renderiza sin excepciones", not app.exception, sin_excepciones(app))
    comprobar("Aparece el botón de cerrar sesión",
              any("Cerrar sesión" in b.label for b in app.button))
    comprobar("La barra lateral identifica al usuario",
              "admin" in texto_de(app))
    # El fondo negro es solo de la pantalla de acceso: el dashboard está
    # diseñado sobre superficie clara y sus colores se validaron contra ella.
    comprobar("El fondo animado NO se filtra al resto de la app",
              not any("#lluvia" in m.value for m in app.markdown))

    print("\n--- Cada pantalla renderiza ---")
    for modulo, esperado in (
        ("dashboard", "Dashboard"),
        ("cotizaciones", "Cotizaciones"),
        ("crear_nota", "Crear nota"),
        ("notas", "Notas de servicio"),
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

    app = abrir_pagina("configuracion")
    comprobar("Configuración deja entrar a un administrador",
              not any("solo para administradores" in e.value for e in app.error),
              texto_de(app)[:200])

    # El rol por fin restringe algo: un operador no debe poder entrar.
    app = abrir_pagina("configuracion", rol="operador")
    comprobar("Configuración bloquea a un operador",
              any("solo para administradores" in e.value for e in app.error),
              texto_de(app)[:200])

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

        etiquetas_pdf = [b.label for b in app.download_button]
        comprobar("Ofrece descargar la cotización en PDF",
                  any("Descargar cotización en PDF" in e
                      for e in etiquetas_pdf),
                  str(etiquetas_pdf))

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


if __name__ == "__main__":
    main()
