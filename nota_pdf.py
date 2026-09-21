"""
Orden de trabajo en PDF — Auto Servicio Bautista.

Rellena la plantilla HTML aprobada del taller y la imprime con Chromium.

Antes este módulo DIBUJABA el PDF con fpdf2, coordenada por coordenada. El
diseño nuevo usa flexbox, grid, `@page` y `@font-face`, que fpdf2 no sabe
interpretar, así que la única forma de respetarlo sin recrearlo a mano es
renderizar el HTML con un motor de verdad.

La puerta pública no cambió: `generar(id_nota)` sigue devolviendo los bytes del
PDF y `nombre_archivo(id_nota)` el nombre sugerido, que es lo que usan las
pantallas y las pruebas.
"""

from __future__ import annotations

import base64
import concurrent.futures
import functools
import html
import re
from datetime import datetime
from pathlib import Path

import db

RAIZ = Path(__file__).resolve().parent

# Las tipografías del diseño. La plantilla las pide como `url('fonts/X.woff2')`,
# rutas relativas que solo resolverían si el HTML se guardara como archivo justo
# al lado de esa carpeta. En vez de eso se incrustan en el documento antes de
# imprimir (ver `_incrustar_fuentes`).
RUTA_FUENTES = RAIZ / "assets" / "fonts"
PATRON_FUENTE = re.compile(r"url\('fonts/([A-Za-z0-9._-]+\.woff2)'\)")

# Archivo es una tipografía VARIABLE: un solo archivo cubre todo el rango de
# grosores, y el `font-weight` que declara cada `@font-face` de la plantilla es
# lo que fija el eje al imprimir. Por eso los cuatro nombres que la plantilla
# pide (Regular, Medium, SemiBold, Bold) se sirven del mismo archivo, y no hay
# que guardar cuatro copias casi idénticas en el repositorio.
FUENTE_DE_RESERVA = "Archivo-Variable.woff2"

# La plantilla aprobada. Es la única de la carpeta que trae los marcadores y el
# bloque de filas; las otras (`.dc.html`) dependen del lienzo de diseño y no
# sirven para imprimir.
RUTA_PLANTILLA = (RAIZ / "Plantillas" / "Work_order" / "export"
                  / "orden-trabajo-plantilla.html")

# Mínimo de renglones impresos: con menos, la hoja se ve corta y deja un hueco
# raro entre la tabla y el total.
FILAS_MINIMAS = 8

# El bloque que se repite una vez por concepto.
PATRON_FILA = re.compile(
    r"<!--\s*INICIO FILA.*?-->(.*?)<!--\s*FIN FILA\s*-->", re.DOTALL)


class PlantillaNoEncontrada(FileNotFoundError):
    """La plantilla del diseño no está donde se espera."""


def _texto(valor: object) -> str:
    """
    Escapa cualquier dato que venga de la base.

    Un cliente llamado «Muebles & Cía <SA>» no debe poder romper la maquetación
    ni inyectar marcado en el documento que se le entrega.
    """
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def _fecha(iso: str | None) -> str:
    """De `2026-01-21` a `21/01/2026`."""
    if not iso:
        return ""
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return _texto(iso)


def _sin_signo(centavos: int | None) -> str:
    """
    Importe sin el signo de pesos.

    La plantilla imprime el `$` del total en su propio `<span class="cur">`,
    así que ese hueco debe recibir solo la cifra.
    """
    return db.formato_pesos(centavos).lstrip("$")


def _descripcion(partida: dict) -> str:
    """
    Arma la descripción del renglón para la columna única de la plantilla.

    El diseño tiene una sola columna de texto, así que la acción, la posición y
    el lado —que en pantalla son columnas aparte— se juntan aquí entre
    paréntesis para no perder información.
    """
    texto = partida["descripcion"]
    if partida["cantidad"] > 1:
        texto = f"{partida['cantidad']} × {texto}"

    detalle = " · ".join(
        str(x) for x in (partida.get("accion"), partida.get("posicion"),
                         partida.get("lado")) if x
    )
    if detalle:
        texto = f"{texto} ({detalle})"
    return _texto(texto)


def _filas(plantilla: str, partidas: list[dict]) -> str:
    """Repite el bloque de fila por cada partida y rellena hasta el mínimo."""
    coincidencia = PATRON_FILA.search(plantilla)
    if coincidencia is None:
        raise ValueError(
            "La plantilla no trae el bloque <!-- INICIO FILA --> / "
            "<!-- FIN FILA -->; no se puede saber qué repetir por concepto."
        )
    molde = coincidencia.group(1)

    renglones = [
        molde
        .replace("{{CONCEPTO_DESCRIPCION}}", _descripcion(p))
        .replace("{{CONCEPTO_PRECIO}}", _texto(
            db.formato_pesos(p["total_centavos"])))
        for p in partidas
    ]

    # Filas en blanco hasta completar la hoja. Conservan su altura por el CSS
    # de la plantilla, así que la tabla se ve como un formato rayado.
    for _ in range(max(0, FILAS_MINIMAS - len(renglones))):
        renglones.append(
            molde.replace("{{CONCEPTO_DESCRIPCION}}", "")
                 .replace("{{CONCEPTO_PRECIO}}", "")
        )

    return plantilla[:coincidencia.start()] + "".join(renglones) \
        + plantilla[coincidencia.end():]


def _rellenar(folio: str, registro: dict, titulo: str) -> str:
    """
    Sustituye todos los marcadores de la plantilla con los datos de una nota o
    de una cotización — ambas comparten exactamente las mismas claves (se arman
    con el mismo JOIN a clientes/vehículos), así que una sola función basta;
    lo único que cambia entre ellas es el folio y el rótulo del documento.
    """
    if not RUTA_PLANTILLA.exists():
        raise PlantillaNoEncontrada(
            f"No se encontró la plantilla en {RUTA_PLANTILLA}. "
            f"Debe estar el archivo exportado del diseño."
        )

    documento = _filas(RUTA_PLANTILLA.read_text(encoding="utf-8"),
                       registro["partidas"])

    iva = registro["total_centavos"] - registro["subtotal_centavos"]

    valores = {
        "{{TITULO_DOCUMENTO}}": _texto(titulo),
        "{{FOLIO}}": _texto(folio),
        "{{CLIENTE_NOMBRE}}": _texto(registro["cliente"]),
        "{{FECHA}}": _fecha(registro["fecha"]),
        "{{MARCA}}": _texto(registro.get("marca")),
        # Nomenclatura del taller: Marca (Chevrolet), Año (2016) y Tipo — el
        # modelo específico de esa marca (Malibú). La plantilla original traía
        # una etiqueta «MODELO» sin campo de año; se corrigió el rótulo a
        # «AÑO» directamente en el HTML para no forzar el año dentro de un
        # campo que dice otra cosa.
        "{{ANIO}}": _texto(registro.get("anio")),
        "{{TIPO}}": _texto(registro.get("modelo")),
        "{{CELULAR}}": _texto(registro.get("telefono")),
        "{{COLOR}}": _texto(registro.get("color")),
        "{{PLACAS}}": _texto(registro.get("placas")),
        "{{SUBTOTAL}}": _texto(db.formato_pesos(registro["subtotal_centavos"])),
        "{{IVA}}": _texto(db.formato_pesos(iva)),
        "{{TOTAL}}": _texto(_sin_signo(registro["total_centavos"])),
    }
    for marcador, valor in valores.items():
        documento = documento.replace(marcador, valor)
    return documento


@functools.lru_cache(maxsize=8)
def _fuente_base64(archivo: Path) -> str:
    """
    Lee un `.woff2` y lo devuelve en base64, recordando el resultado.

    La plantilla la pide cuatro veces (una por grosor) y la misma orden se
    imprime muchas veces por sesión: leer y codificar el archivo una sola vez
    ahorra ese trabajo repetido. Las tipografías no cambian mientras el
    proceso vive, así que recordarlas es seguro.
    """
    return base64.b64encode(archivo.read_bytes()).decode("ascii")


def _incrustar_fuentes(documento: str) -> str:
    """
    Cambia cada `url('fonts/X.woff2')` por el archivo incrustado en base64.

    Así el documento queda autocontenido y se puede imprimir sin escribirlo a
    disco: es lo que permite que `_a_pdf` no deje archivos temporales dentro de
    la carpeta del código. El logo ya venía incrustado desde el diseño; las
    tipografías eran lo único que seguía siendo una ruta relativa.

    Si un `.woff2` no está, su URL se deja intacta y Chromium cae a la pila de
    tipografías de reserva, igual que hoy. Una fuente ausente no puede impedir
    que se imprima una orden de trabajo.
    """
    def reemplazo(coincidencia: re.Match[str]) -> str:
        archivo = RUTA_FUENTES / coincidencia.group(1)
        if not archivo.is_file():
            archivo = RUTA_FUENTES / FUENTE_DE_RESERVA
        if not archivo.is_file():
            return coincidencia.group(0)
        return f"url('data:font/woff2;base64,{_fuente_base64(archivo)}')"

    return PATRON_FUENTE.sub(reemplazo, documento)


def _imprimir(documento: str) -> bytes:
    """Carga el HTML en Chromium y lo imprime a PDF."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as motor:
        navegador = motor.chromium.launch()
        try:
            pagina = navegador.new_page()
            # El documento llega autocontenido (logo y tipografías en base64),
            # así que no hace falta ninguna URL base ni escribirlo a disco.
            pagina.set_content(documento, wait_until="load")
            # Sin esto la primera orden se imprime antes de que las tipografías
            # terminen de cargar.
            pagina.evaluate("document.fonts.ready")
            return pagina.pdf(
                format="Letter",
                # Obligatorio: sin él Chromium omite los fondos y las barras
                # del diseño salen en blanco.
                print_background=True,
                # El tamaño y los márgenes los manda el `@page` de la plantilla.
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            navegador.close()


def _a_pdf(documento: str) -> bytes:
    """
    Renderiza el HTML ya relleno y devuelve los bytes del PDF.

    Antes esto escribía un archivo temporal DENTRO de la carpeta de la
    plantilla, porque era la única forma de que resolvieran sus rutas
    relativas. Eso obligaba a que el directorio del código fuera escribible —
    imposible en una imagen de solo lectura — y dejaba basura si el proceso
    moría a media impresión. Con el documento autocontenido, ya no hace falta
    tocar el disco.

    El render corre en un hilo aparte porque la API síncrona de Playwright se
    niega a funcionar si en el hilo actual hay un bucle de asyncio corriendo, y
    Streamlit ejecuta el script en un hilo propio donde eso puede pasar.
    """
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as hilo:
        return hilo.submit(_imprimir, _incrustar_fuentes(documento)).result()


def generar(id_nota: str) -> bytes:
    """Devuelve la orden de trabajo como bytes de PDF."""
    nota = db.obtener_nota(id_nota)
    if nota is None:
        raise ValueError(f"No existe la nota {id_nota}.")
    return _a_pdf(_rellenar(nota["id_nota"], nota, "ORDEN DE TRABAJO"))


def nombre_archivo(id_nota: str) -> str:
    """Nombre sugerido para la descarga: `orden-N-016.pdf`."""
    return f"orden-{id_nota}.pdf"


def generar_cotizacion(id_cotizacion: str) -> bytes:
    """
    Devuelve la cotización como bytes de PDF, con el mismo diseño de la orden.

    El rótulo cambia a «COTIZACIÓN» — nunca debe salir impresa como «ORDEN DE
    TRABAJO», que es justo la confusión que el folio COT- ya evita en pantalla.
    """
    cotizacion = db.obtener_cotizacion(id_cotizacion)
    if cotizacion is None:
        raise ValueError(f"No existe la cotización {id_cotizacion}.")
    return _a_pdf(_rellenar(cotizacion["id_cotizacion"], cotizacion, "COTIZACIÓN"))


def nombre_archivo_cotizacion(id_cotizacion: str) -> str:
    """Nombre sugerido para la descarga: `cotizacion-COT-003.pdf`."""
    return f"cotizacion-{id_cotizacion}.pdf"
