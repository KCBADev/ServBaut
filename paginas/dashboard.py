"""
Dashboard — Servicio Bautista.

Un solo filtro de fechas gobierna todo el tablero: ninguna gráfica trae su
propio filtro.

Decisiones de visualización:
  * Los KPIs van como cifras, no como gráficas de una barra.
  * Las magnitudes por categoría nominal (categorías, marcas, clientes) usan
    barras horizontales de UN color: pintar cada barra según su valor
    duplicaría en el color lo que la longitud ya dice.
  * El mix Producto/Servicio es parte-de-un-todo, así que va apilado, con
    leyenda y etiquetas directas — nunca un pastel de dos rebanadas.
  * Cada gráfica trae su tabla equivalente para que ningún valor dependa
    solo del color o del tooltip.
"""

from __future__ import annotations

from datetime import date, datetime

import altair as alt
import pandas as pd
import streamlit as st

import db
import styles

# Paleta de datos revalidada contra el lienzo BLANCO de la interfaz: los tonos
# viven en styles.py para que las gráficas y la interfaz no se separen nunca.
# Detalle de contraste en styles.py, junto a SERIE_1/SERIE_2.
SERIE_1 = styles.SERIE_1
SERIE_2 = styles.SERIE_2
SUPERFICIE = styles.FONDO
REJILLA = styles.REJILLA
EJE = styles.EJE
TINTA_TENUE = styles.TEXTO_TENUE
TINTA_SECUNDARIA = styles.TEXTO_APAGADO


def _pesos(centavos: int | None) -> float:
    """Convierte a pesos para graficar (Altair necesita números, no Decimal)."""
    return float(db.centavos_a_pesos(centavos or 0))


def _afinar(grafica: alt.Chart) -> alt.Chart:
    """Aplica el mismo cromo discreto a todas las gráficas."""
    return (
        grafica
        # Fondo transparente: la gráfica se apoya en el lienzo oscuro de la
        # app en vez de traer su propio rectángulo blanco.
        .configure(background="transparent")
        .configure_view(strokeWidth=0)
        .configure_axis(
            gridColor=REJILLA, gridWidth=1, domainColor=EJE, tickColor=EJE,
            labelColor=TINTA_TENUE, titleColor=TINTA_SECUNDARIA,
            labelFontSize=11, titleFontSize=11, titleFontWeight="normal",
        )
        .configure_legend(
            labelColor=TINTA_SECUNDARIA, titleColor=TINTA_SECUNDARIA,
            labelFontSize=11, titleFontSize=11, symbolType="square",
        )
    )


def _barras_horizontales(datos: pd.DataFrame, campo_categoria: str,
                         campo_valor: str, titulo_valor: str,
                         formato: str = "$,.0f") -> alt.Chart:
    """Barras horizontales de un solo color, ordenadas de mayor a menor."""
    return _afinar(
        alt.Chart(datos)
        .mark_bar(color=SERIE_1, cornerRadiusEnd=4, height=16)
        .encode(
            x=alt.X(f"{campo_valor}:Q", title=titulo_valor,
                    axis=alt.Axis(format=formato)),
            y=alt.Y(f"{campo_categoria}:N", title=None,
                    sort=alt.SortField(campo_valor, order="descending")),
            tooltip=[
                alt.Tooltip(f"{campo_categoria}:N", title="Concepto"),
                alt.Tooltip(f"{campo_valor}:Q", title=titulo_valor, format=formato),
            ],
        )
        .properties(height=max(160, 26 * len(datos)))
    )


def _tabla(titulo: str, datos: pd.DataFrame) -> None:
    """Equivalente en tabla de una gráfica: ningún valor depende solo del color."""
    with st.expander(f"Ver {titulo} en tabla"):
        st.dataframe(datos, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------

def _filtro_fechas() -> tuple[str | None, str | None]:
    """La única fila de filtros del tablero; gobierna todas las gráficas."""
    minimo, maximo = db.rango_fechas()
    if not minimo:
        return None, None

    inicio = datetime.strptime(minimo, "%Y-%m-%d").date()
    fin = datetime.strptime(maximo, "%Y-%m-%d").date()

    col1, col2 = st.columns([3, 1])
    rango = col1.date_input(
        "Rango de fechas", value=(inicio, fin),
        min_value=inicio, max_value=fin, format="YYYY-MM-DD",
    )
    col2.caption(
        f"Historial disponible:  \n**{minimo}** a **{maximo}**"
    )

    # Mientras se elige la segunda fecha, Streamlit devuelve una sola.
    if isinstance(rango, (tuple, list)) and len(rango) == 2:
        return rango[0].isoformat(), rango[1].isoformat()
    if isinstance(rango, (tuple, list)) and len(rango) == 1:
        return rango[0].isoformat(), maximo
    if isinstance(rango, date):
        return rango.isoformat(), maximo
    return minimo, maximo


def _kpis(desde: str | None, hasta: str | None) -> None:
    datos = db.kpis(desde, hasta)

    # Columnas desiguales: el ingreso total es una cifra mucho más larga que
    # las demás y con cinco columnas iguales se cortaba en "$381,1…".
    col1, col2, col3, col4 = st.columns([1.5, 0.8, 1.3, 1.4])
    col1.metric("Ingreso total", db.formato_pesos(datos["ingreso_centavos"]))
    col2.metric("Notas", f"{datos['num_notas']:,}")
    col3.metric("Ticket promedio",
                db.formato_pesos(datos["ticket_promedio_centavos"]))
    col4.metric("Por cobrar", db.formato_pesos(datos["por_cobrar_centavos"]),
                help="Lo facturado que todavía no se ha pagado.")

    col5, col6, col7, col8 = st.columns([1.5, 0.8, 1.3, 1.4])
    col5.metric("Clientes atendidos", f"{datos['clientes_atendidos']:,}")
    col6.metric("Vehículos", f"{datos['vehiculos_atendidos']:,}")
    col7.metric("Clientes recurrentes", f"{datos['clientes_recurrentes']:,}",
                help="Clientes con más de una nota dentro del rango elegido.")
    col8.metric("Notas abiertas", f"{datos['notas_abiertas']:,}",
                help="Las que todavía no se han entregado.")


def grafica_ingresos_por_mes(datos: pd.DataFrame) -> alt.Chart:
    """Serie de tiempo de una sola serie: sin leyenda, el título la nombra."""
    base = alt.Chart(datos).encode(
        x=alt.X("Mes:T", title=None, axis=alt.Axis(format="%b %Y", grid=False)),
        y=alt.Y("Ingreso:Q", title="Ingreso",
                axis=alt.Axis(format="$,.0f")),
    )
    area = base.mark_area(color=SERIE_1, opacity=0.12)
    linea = base.mark_line(color=SERIE_1, strokeWidth=2)
    # Anillo de 2px del color de la superficie para que los puntos no se
    # empasten donde la serie sube rápido.
    puntos = base.mark_point(color=SERIE_1, filled=True, size=70,
                             stroke=SUPERFICIE, strokeWidth=2).encode(
        tooltip=[
            alt.Tooltip("Mes:T", title="Mes", format="%B %Y"),
            alt.Tooltip("Ingreso:Q", title="Ingreso", format="$,.2f"),
            alt.Tooltip("Notas:Q", title="Notas"),
        ],
    )
    return _afinar((area + linea + puntos).properties(height=300))


def datos_ingresos_por_mes(desde: str | None, hasta: str | None) -> pd.DataFrame:
    """
    Ingresos por mes, con los meses sin notas rellenados en cero.

    La consulta solo devuelve los meses que tuvieron notas. Graficar eso tal
    cual hace que la línea una enero de 2024 con diciembre de 2024 en una
    diagonal recta, inventando un crecimiento sostenido durante once meses en
    los que en realidad no hubo trabajo. Un mes sin notas facturó cero, y así
    debe dibujarse.
    """
    filas = db.ingresos_por_mes(desde, hasta)
    if not filas:
        return pd.DataFrame(columns=["Mes", "Ingreso", "Notas"])

    datos = pd.DataFrame([
        {
            "Mes": pd.to_datetime(f["mes"] + "-01"),
            "Ingreso": _pesos(f["ingreso_centavos"]),
            "Notas": f["num_notas"],
        }
        for f in filas
    ])

    meses_completos = pd.date_range(datos["Mes"].min(), datos["Mes"].max(),
                                    freq="MS")
    return (
        datos.set_index("Mes")
        .reindex(meses_completos, fill_value=0)
        .rename_axis("Mes")
        .reset_index()
    )


def _ingresos_por_mes(desde: str | None, hasta: str | None) -> None:
    st.subheader("Ingresos por mes")

    datos = datos_ingresos_por_mes(desde, hasta)
    if datos.empty:
        st.info("No hay notas en el rango elegido.")
        return

    st.altair_chart(grafica_ingresos_por_mes(datos), width="stretch")

    tabla = datos.copy()
    tabla["Mes"] = tabla["Mes"].dt.strftime("%Y-%m")
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    _tabla("los ingresos por mes", tabla)


def _por_categoria(desde: str | None, hasta: str | None) -> None:
    st.subheader("Ingresos por categoría")

    filas = db.ingresos_por_categoria(desde, hasta)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    datos = pd.DataFrame([
        {
            "Categoría": f["categoria"],
            "Ingreso": _pesos(f["ingreso_centavos"]),
            "Partidas": f["num_partidas"],
        }
        for f in filas
    ])

    st.altair_chart(
        _barras_horizontales(datos, "Categoría", "Ingreso", "Ingreso"),
        width="stretch",
    )

    tabla = datos.copy()
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    _tabla("los ingresos por categoría", tabla)


def datos_mix_tipo(desde: str | None, hasta: str | None) -> pd.DataFrame:
    filas = db.mix_tipo_concepto(desde, hasta)
    total = sum(f["ingreso_centavos"] for f in filas)
    return pd.DataFrame([
        {
            "Tipo": f["tipo_concepto"],
            "Ingreso": _pesos(f["ingreso_centavos"]),
            "Partidas": f["num_partidas"],
            "Porcentaje": f["ingreso_centavos"] / total * 100 if total else 0,
            # Etiqueta con el signo incluido: un "43" suelto dentro de la barra
            # no dice de qué es.
            "Etiqueta": f"{f['ingreso_centavos'] / total * 100:.0f}%" if total else "0%",
        }
        for f in filas
    ])


def grafica_mix_tipo(datos: pd.DataFrame) -> alt.Chart:
    """
    Parte-de-un-todo con dos elementos: barra apilada, nunca un pastel.

    El `stroke` del color de la superficie crea la separación de 2px entre
    segmentos sin dibujar un borde alrededor de las marcas.
    """
    barra = (
        alt.Chart(datos)
        .mark_bar(height=48, stroke=SUPERFICIE, strokeWidth=2)
        .encode(
            x=alt.X("Ingreso:Q", title="Ingreso", stack="zero",
                    axis=alt.Axis(format="$,.0f")),
            color=alt.Color(
                "Tipo:N",
                scale=alt.Scale(domain=["Producto", "Servicio"],
                                range=[SERIE_1, SERIE_2]),
                legend=alt.Legend(title=None, orient="top"),
            ),
            tooltip=[
                alt.Tooltip("Tipo:N", title="Tipo"),
                alt.Tooltip("Ingreso:Q", title="Ingreso", format="$,.2f"),
                alt.Tooltip("Porcentaje:Q", title="Del total", format=".1f"),
                alt.Tooltip("Partidas:Q", title="Partidas"),
            ],
        )
    )
    # Etiqueta directa dentro de cada segmento: solo el porcentaje, que cabe.
    # Etiqueta en tinta oscura, no blanca: los dos colores del mix rondan una
    # luminosidad media, donde el texto oscuro contrasta mucho mejor.
    etiquetas = (
        alt.Chart(datos)
        .mark_text(color=styles.TEXTO, fontWeight="bold", fontSize=13)
        .encode(
            x=alt.X("Ingreso:Q", stack="zero", bandPosition=0.5, title=None),
            detail="Tipo:N",
            text=alt.Text("Etiqueta:N"),
        )
    )
    return _afinar((barra + etiquetas).properties(height=110))


def _mix_tipo(desde: str | None, hasta: str | None) -> None:
    st.subheader("Producto vs Servicio")

    datos = datos_mix_tipo(desde, hasta)
    if datos.empty:
        st.info("Sin datos en el rango.")
        return

    st.altair_chart(grafica_mix_tipo(datos), width="stretch")

    tabla = datos.copy()
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    tabla["Porcentaje"] = tabla["Porcentaje"].map(lambda v: f"{v:.1f}%")
    _tabla("el mix", tabla)


def _marcas(desde: str | None, hasta: str | None) -> None:
    st.subheader("Marcas más atendidas")

    filas = db.marcas_mas_atendidas(desde, hasta, limite=10)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    datos = pd.DataFrame([
        {
            "Marca": f["marca"],
            "Notas": f["num_notas"],
            "Ingreso": _pesos(f["ingreso_centavos"]),
        }
        for f in filas
    ])

    st.altair_chart(
        _barras_horizontales(datos, "Marca", "Notas", "Notas", formato=",.0f"),
        width="stretch",
    )

    tabla = datos.copy()
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    _tabla("las marcas", tabla)


def _top_clientes(desde: str | None, hasta: str | None) -> None:
    st.subheader("Top clientes por facturación")

    filas = db.top_clientes(desde, hasta, limite=10)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    datos = pd.DataFrame([
        {
            "Cliente": f["nombre"],
            "Ingreso": _pesos(f["ingreso_centavos"]),
            "Notas": f["num_notas"],
        }
        for f in filas
    ])

    st.altair_chart(
        _barras_horizontales(datos, "Cliente", "Ingreso", "Ingreso"),
        width="stretch",
    )

    tabla = datos.copy()
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    _tabla("el top de clientes", tabla)


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Dashboard")

    desde, hasta = _filtro_fechas()
    if desde is None:
        st.info("Todavía no hay notas registradas.")
        return

    st.divider()
    _kpis(desde, hasta)

    st.divider()
    _ingresos_por_mes(desde, hasta)

    st.divider()
    izquierda, derecha = st.columns(2)
    with izquierda:
        _por_categoria(desde, hasta)
    with derecha:
        _mix_tipo(desde, hasta)
        st.write("")
        _marcas(desde, hasta)

    st.divider()
    _top_clientes(desde, hasta)
