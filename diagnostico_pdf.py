"""
Reporte de diagnóstico con escáner en PDF — Auto Servicio Bautista.

Mismo mecanismo que `nota_pdf.py` (rellenar la plantilla HTML aprobada e
imprimirla con Chromium), pero la plantilla de diagnóstico no repite un solo
bloque de fila: agrupa los códigos por sistema, con una tabla por grupo, así
que ese tramo se arma aquí en Python en vez de con el patrón
INICIO/FIN FILA que usa la orden de trabajo.
"""

from __future__ import annotations

import html
from pathlib import Path

import db
import nota_pdf

RAIZ = Path(__file__).resolve().parent

RUTA_PLANTILLA = (RAIZ / "Plantillas" / "Work_order" / "export"
                  / "diagnostico-plantilla.html")

# Clase CSS y etiqueta impresa por cada nivel de gravedad.
_PILL = {
    "ALTA": ("pill-alta", "ALTA"),
    "MEDIA": ("pill-media", "MEDIA"),
    "BAJA": ("pill-baja", "BAJA"),
    "INFO": ("pill-info", "INFO"),
}


def _texto(valor: object) -> str:
    """Escapa cualquier dato que venga de la base (mismo criterio que nota_pdf)."""
    if valor is None:
        return ""
    return html.escape(str(valor), quote=True)


def _parrafos(texto: str | None) -> str:
    """
    Texto libre del técnico (resumen, notas) a HTML, respetando sus saltos de
    línea. Se escapa primero y solo DESPUÉS se insertan los `<br>`, para que
    un resumen que traiga '<' o '&' no rompa el documento.
    """
    if not texto:
        return "—"
    return _texto(texto).replace("\n", "<br>")


def _sistemas(codigos: list[dict]) -> str:
    """
    Arma un bloque `<div class="sect">`... por cada sistema, en el orden en
    que aparecieron sus códigos, con su propia tabla de 4 columnas.

    Los códigos ya vienen en el orden de captura (columna `linea`); agrupar
    así, sin ordenar por sistema, respeta el orden en que el técnico los
    metió en vez de reordenarlos alfabéticamente.
    """
    grupos: list[tuple[str, str | None, list[dict]]] = []
    indice = {}
    for cod in codigos:
        sistema = cod["sistema"]
        if sistema not in indice:
            indice[sistema] = len(grupos)
            grupos.append((sistema, cod.get("sistema_nota"), []))
        grupos[indice[sistema]][2].append(cod)

    bloques = []
    for numero, (sistema, nota, filas) in enumerate(grupos, start=1):
        plural = "código" if len(filas) == 1 else "códigos"
        cabecera = (
            f'    <div class="sist-h"><span class="num">{numero}.</span>'
            f'<span class="nom">{_texto(sistema)}</span>'
            f'<span class="cta">{len(filas)} {plural}</span></div>'
        )
        nota_html = (f'    <div class="sist-nota">{_texto(nota)}</div>'
                    if nota else "")

        renglones = []
        for cod in filas:
            clase, etiqueta = _PILL.get(cod["gravedad"], _PILL["MEDIA"])
            renglones.append(
                "      <tr>"
                f'<td class="cod">{_texto(cod["codigo"])}</td>'
                f'<td class="desc">{_texto(cod["descripcion"])}</td>'
                f'<td class="sig">{_texto(cod["significado"])}</td>'
                f'<td class="grav"><span class="pill {clase}">{etiqueta}</span></td>'
                "</tr>"
            )

        tabla = (
            '    <table class="dtc">\n'
            "      <thead>\n"
            '        <tr><th class="cod">CÓDIGO</th><th class="desc">DESCRIPCIÓN '
            'DEL ESCÁNER</th><th class="sig">QUÉ SIGNIFICA</th>'
            '<th class="grav">GRAVEDAD</th></tr>\n'
            "      </thead>\n"
            "      <tbody>\n" + "\n".join(renglones) + "\n      </tbody>\n"
            "    </table>"
        )

        bloques.append("\n".join(x for x in (cabecera, nota_html, tabla) if x))

    return "\n".join(bloques)


def _otros_modulos(texto: str | None) -> str:
    if not texto:
        return ""
    return (
        '  <div class="sect" style="padding-top:0">\n'
        '    <div class="otros"><span class="k">OTROS MÓDULOS</span>'
        f"{_parrafos(texto)}</div>\n"
        "  </div>\n"
    )


def _rellenar(diagnostico: dict) -> str:
    if not RUTA_PLANTILLA.exists():
        raise nota_pdf.PlantillaNoEncontrada(
            f"No se encontró la plantilla en {RUTA_PLANTILLA}. "
            f"Debe estar el archivo exportado del diseño."
        )

    documento = RUTA_PLANTILLA.read_text(encoding="utf-8")

    valores = {
        "{{TITULO_DOCUMENTO}}": "DIAGNÓSTICO CON ESCÁNER",
        "{{FOLIO}}": _texto(diagnostico["id_diagnostico"]),
        "{{CLIENTE_NOMBRE}}": _texto(diagnostico["cliente"]),
        "{{FECHA}}": nota_pdf._fecha(diagnostico["fecha"]),
        "{{MARCA}}": _texto(diagnostico.get("marca")),
        "{{ANIO}}": _texto(diagnostico.get("anio")),
        "{{TIPO}}": _texto(diagnostico.get("modelo")),
        "{{CELULAR}}": _texto(diagnostico.get("telefono")),
        "{{COLOR}}": _texto(diagnostico.get("color")),
        "{{PLACAS}}": _texto(diagnostico.get("placas")),
        "{{TECNICO}}": _texto(diagnostico.get("tecnico")) or "—",
        "{{NUM_MODULOS}}": _texto(diagnostico.get("num_modulos")) or "—",
        "{{NUM_CODIGOS}}": str(len(diagnostico["codigos"])),
        "{{SISTEMAS_HTML}}": _sistemas(diagnostico["codigos"]),
        "{{OTROS_MODULOS_HTML}}": _otros_modulos(diagnostico.get("otros_modulos")),
        "{{RESUMEN_HTML}}": _parrafos(diagnostico.get("resumen")),
    }
    for marcador, valor in valores.items():
        documento = documento.replace(marcador, valor)
    return documento


def generar(id_diagnostico: str) -> bytes:
    """Devuelve el reporte de diagnóstico como bytes de PDF."""
    diagnostico = db.obtener_diagnostico(id_diagnostico)
    if diagnostico is None:
        raise ValueError(f"No existe el diagnóstico {id_diagnostico}.")
    return nota_pdf._a_pdf(_rellenar(diagnostico), carpeta=RUTA_PLANTILLA.parent)


def nombre_archivo(id_diagnostico: str) -> str:
    """Nombre sugerido para la descarga: `diagnostico-DX-001.pdf`."""
    return f"diagnostico-{id_diagnostico}.pdf"
