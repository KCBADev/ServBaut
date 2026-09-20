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

import concurrent.futures
import html
import re
import tempfile
from datetime import datetime
from pathlib import Path

import db

RAIZ = Path(__file__).resolve().parent

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


def _imprimir(ruta_html: Path) -> bytes:
    """Abre el archivo en Chromium y lo imprime a PDF."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as motor:
        navegador = motor.chromium.launch()
        try:
            pagina = navegador.new_page()
            # Se abre como ARCHIVO y no con set_content: sin URL base, las
            # rutas relativas de la plantilla (las tipografías de `fonts/`) no
            # resolverían y la hoja saldría con la fuente de reserva.
            pagina.goto(ruta_html.as_uri(), wait_until="load")
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


def _a_pdf(documento: str, carpeta: Path | None = None) -> bytes:
    """
    Renderiza el HTML ya relleno.

    El archivo temporal se escribe DENTRO de la carpeta de la plantilla para
    que las rutas relativas sigan apuntando a donde deben. Por omisión es la
    carpeta de ESTE módulo (`orden-trabajo-plantilla.html`); otros módulos
    que rellenen una plantilla distinta (como `diagnostico_pdf.py`) deben
    pasar la suya en `carpeta` — si no, las rutas relativas de su plantilla
    (tipografías, logo) resolverían contra la carpeta equivocada en cuanto
    dejaran de coincidir por casualidad.

    El render corre en un hilo aparte porque la API síncrona de Playwright se
    niega a funcionar si en el hilo actual hay un bucle de asyncio corriendo, y
    Streamlit ejecuta el script en un hilo propio donde eso puede pasar.
    """
    temporal = tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", dir=carpeta or RUTA_PLANTILLA.parent,
        delete=False, encoding="utf-8")
    try:
        temporal.write(documento)
        temporal.close()
        ruta = Path(temporal.name)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as hilo:
            return hilo.submit(_imprimir, ruta).result()
    finally:
        Path(temporal.name).unlink(missing_ok=True)


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
