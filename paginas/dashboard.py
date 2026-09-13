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

# Paleta de datos revalidada contra el lienzo OSCURO de la interfaz: los tonos
# viven en styles.py para que las gráficas y la interfaz no se separen nunca.
# Detalle de contraste en styles.py, junto a SERIE_1/SERIE_2.
SERIE_1 = styles.SERIE_1
SERIE_2 = styles.SERIE_2
SUPERFICIE = styles.FONDO
REJILLA = styles.REJILLA
EJE = styles.EJE
TINTA_TENUE = styles.TEXTO_TENUE
TINTA_SECUNDARIA = styles.TEXTO_APAGADO

# Tinta de las etiquetas que van DENTRO de una marca de color. No puede ser
# una sola: sobre el menta hace falta tinta oscura (10.05:1) y sobre el coral,
# clara (4.22:1). Cada gráfica que rotula por dentro elige según su serie.
TINTA_SOBRE_SERIE_1 = styles.FONDO
TINTA_SOBRE_SERIE_2 = styles.TEXTO


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
            # `labelOverlap=False`: por omisión Altair va tirando etiquetas
            # cuando cree que se enciman, y dejaba la gráfica con barras sin
            # nombre — sin saber de quién es cada barra, la gráfica no sirve.
            y=alt.Y(f"{campo_categoria}:N", title=None,
                    sort=alt.SortField(campo_valor, order="descending"),
                    axis=alt.Axis(labelOverlap=False, labelLimit=170)),
            tooltip=[
                alt.Tooltip(f"{campo_categoria}:N", title="Concepto"),
                alt.Tooltip(f"{campo_valor}:Q", title=titulo_valor, format=formato),
            ],
        )
        # 30 px por barra en vez de 26: con menos, las etiquetas del eje se
        # encimaban y Altair volvía a esconderlas aunque se lo prohíba.
        .properties(height=max(160, 30 * len(datos)))
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
        min_value=inicio, max_value=fin, format="DD/MM/YYYY",
    )
    col2.caption(
        f"Historial disponible:  \n"
        f"**{db.formato_fecha(minimo)}** a **{db.formato_fecha(maximo)}**"
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
            # La tinta se decide por serie, no por gráfica: el menta es un
            # color claro y pide texto oscuro; el coral es oscuro y pide
            # texto claro. Una sola tinta dejaría una de las dos ilegible.
            "Tinta": (TINTA_SOBRE_SERIE_1 if f["tipo_concepto"] == "Producto"
                      else TINTA_SOBRE_SERIE_2),
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
    # El color de la tinta viene calculado por fila (ver `datos_mix_tipo`) y
    # se pasa con `scale=None` para que Altair lo use tal cual en vez de
    # tratarlo como una categoría más que colorear.
    etiquetas = (
        alt.Chart(datos)
        .mark_text(fontWeight="bold", fontSize=13)
        .encode(
            x=alt.X("Ingreso:Q", stack="zero", bandPosition=0.5, title=None),
            detail="Tipo:N",
            text=alt.Text("Etiqueta:N"),
            color=alt.Color("Tinta:N", scale=None, legend=None),
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

    # Fuera las dos columnas que solo sirven para dibujar la etiqueta dentro
    # de la barra: una repite el porcentaje y la otra es un color en hex.
    tabla = datos.drop(columns=["Etiqueta", "Tinta"])
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


def _ticket_por_marca(desde: str | None, hasta: str | None) -> None:
    st.subheader("Ticket promedio por marca")

    filas = db.ticket_por_marca(desde, hasta)
    if not filas:
        st.info("Ninguna marca tiene todavía suficientes notas para "
                "promediar.")
        return

    datos = pd.DataFrame([
        {
            "Marca": f["marca"],
            "Ticket": _pesos(f["ticket_centavos"]),
            "Notas": f["num_notas"],
        }
        for f in filas
    ])

    st.altair_chart(
        _barras_horizontales(datos, "Marca", "Ticket", "Ticket promedio"),
        width="stretch",
    )
    st.caption("Solo marcas con dos notas o más: un promedio sobre una sola "
               "nota no dice nada.")

    tabla = datos.copy()
    tabla["Ticket"] = tabla["Ticket"].map(lambda v: f"${v:,.2f}")
    _tabla("el ticket por marca", tabla)


def datos_dispersion(desde: str | None, hasta: str | None) -> pd.DataFrame:
    """Una fila por nota, con las variables cuantitativas que se cruzan."""
    filas = db.listar_notas(desde=desde, hasta=hasta)
    return pd.DataFrame([
        {
            "Folio": f["id_nota"],
            "Cliente": f["cliente"],
            "Vehiculo": f"{f['marca'] or ''} {f['modelo'] or ''}".strip() or "—",
            "Anio": f["anio"],
            "Renglones": f["num_partidas"],
            "Total": _pesos(f["total_centavos"]),
        }
        for f in filas
    ])


def _grafica_dispersion(datos: pd.DataFrame, campo_x: str, titulo_x: str,
                        formato_x: str = ",.0f") -> alt.Chart:
    """
    Nube de puntos con su recta de tendencia.

    La recta es la mitad del valor de un diagrama de dispersión: sin ella hay
    que adivinar a ojo si la nube sube, baja o no dice nada.
    """
    base = alt.Chart(datos)
    puntos = base.mark_circle(size=90, color=SERIE_1, opacity=0.65).encode(
        x=alt.X(f"{campo_x}:Q", title=titulo_x,
                scale=alt.Scale(zero=False, nice=True),
                axis=alt.Axis(format=formato_x)),
        y=alt.Y("Total:Q", title="Total de la nota",
                axis=alt.Axis(format="$,.0f")),
        tooltip=[
            alt.Tooltip("Folio:N", title="Nota"),
            alt.Tooltip("Cliente:N", title="Cliente"),
            alt.Tooltip("Vehiculo:N", title="Vehículo"),
            alt.Tooltip(f"{campo_x}:Q", title=titulo_x, format=formato_x),
            alt.Tooltip("Total:Q", title="Total", format="$,.2f"),
        ],
    )
    tendencia = (
        base.mark_line(color=styles.TEXTO_TENUE, strokeDash=[6, 4],
                       strokeWidth=2)
        .transform_regression(campo_x, "Total")
        .encode(x=f"{campo_x}:Q", y="Total:Q")
    )
    return _afinar((puntos + tendencia).properties(height=320))


def _dispersion_anio(desde: str | None, hasta: str | None) -> None:
    st.subheader("Antigüedad del vehículo y ticket")

    datos = datos_dispersion(desde, hasta)
    datos = datos[datos["Anio"].notna()]
    if datos.empty:
        st.info("Ninguna nota del rango tiene el año del vehículo capturado.")
        return

    st.altair_chart(
        _grafica_dispersion(datos, "Anio", "Año del vehículo", "d"),
        width="stretch",
    )
    st.caption("Cada punto es una nota. La línea punteada es la tendencia: si "
               "va plana, el año del coche no predice cuánto se cobra.")

    tabla = datos[["Folio", "Vehiculo", "Anio", "Total"]].copy()
    tabla["Anio"] = tabla["Anio"].astype("Int64")
    tabla["Total"] = tabla["Total"].map(lambda v: f"${v:,.2f}")
    tabla = tabla.rename(columns={"Anio": "Año", "Vehiculo": "Vehículo"})
    _tabla("las notas por año de vehículo", tabla)


def _dispersion_renglones(desde: str | None, hasta: str | None) -> None:
    st.subheader("Renglones por nota y ticket")

    datos = datos_dispersion(desde, hasta)
    if datos.empty:
        st.info("Sin notas en el rango.")
        return

    st.altair_chart(
        _grafica_dispersion(datos, "Renglones", "Renglones en la nota"),
        width="stretch",
    )
    st.caption("Responde de dónde sale una nota grande: de muchos conceptos "
               "o de conceptos caros. Si la nube sube parejo, es volumen.")

    tabla = datos[["Folio", "Cliente", "Renglones", "Total"]].copy()
    tabla["Total"] = tabla["Total"].map(lambda v: f"${v:,.2f}")
    _tabla("las notas por número de renglones", tabla)


def datos_pastel_categorias(desde: str | None, hasta: str | None,
                            limite: int = 5) -> pd.DataFrame:
    """
    Ingreso por categoría, recortado a las mayores y un cajón de «Otras».

    Un pastel con once rebanadas no se lee: las últimas quedan como hilos sin
    etiqueta. Se quedan las `limite` mayores y el resto se junta, que además
    es la lectura honesta — lo que importa aquí es la concentración.
    """
    filas = db.ingresos_por_categoria(desde, hasta)
    if not filas:
        return pd.DataFrame(columns=["Categoría", "Ingreso", "Porcentaje"])

    ordenadas = sorted(filas, key=lambda f: f["ingreso_centavos"], reverse=True)
    principales = ordenadas[:limite]
    resto = ordenadas[limite:]

    partes = [{"Categoría": f["categoria"],
               "Ingreso": _pesos(f["ingreso_centavos"])}
              for f in principales]
    if resto:
        partes.append({
            "Categoría": "Otras",
            "Ingreso": _pesos(sum(f["ingreso_centavos"] for f in resto)),
        })

    datos = pd.DataFrame(partes)
    total = datos["Ingreso"].sum()
    datos["Porcentaje"] = datos["Ingreso"] / total * 100 if total else 0
    datos["EtiquetaPct"] = datos["Porcentaje"].map(lambda v: f"{v:.0f}%")
    return datos


def grafica_pastel_categorias(datos: pd.DataFrame) -> alt.Chart:
    """Pastel de composición, rotulado: el color no es el único canal."""
    colores = styles.RAMPA[:len(datos)]
    if "Otras" in set(datos["Categoría"]):
        colores = styles.RAMPA[:len(datos) - 1] + [styles.RAMPA_RESTO]

    base = alt.Chart(datos).encode(
        theta=alt.Theta("Ingreso:Q", stack=True),
        color=alt.Color(
            "Categoría:N",
            scale=alt.Scale(domain=list(datos["Categoría"]), range=colores),
            legend=alt.Legend(title=None, orient="right"),
        ),
        tooltip=[
            alt.Tooltip("Categoría:N", title="Categoría"),
            alt.Tooltip("Ingreso:Q", title="Ingreso", format="$,.2f"),
            alt.Tooltip("Porcentaje:Q", title="Del total", format=".1f"),
        ],
    )
    # Dona y no pastel lleno: el hueco del centro da dónde apoyar la vista y
    # hace más fácil comparar los arcos por su longitud.
    arco = base.mark_arc(innerRadius=62, outerRadius=118,
                         stroke=SUPERFICIE, strokeWidth=2)
    etiquetas = base.mark_text(radius=140, fontSize=11,
                               fill=styles.TEXTO).encode(
        # Con el signo: un «36» suelto junto a un arco no dice de qué es.
        text=alt.Text("EtiquetaPct:N")
    )
    return _afinar((arco + etiquetas).properties(height=320))


def _pastel_categorias(desde: str | None, hasta: str | None) -> None:
    st.subheader("Reparto del ingreso por categoría")

    datos = datos_pastel_categorias(desde, hasta)
    if datos.empty:
        st.info("Sin datos en el rango.")
        return

    st.altair_chart(grafica_pastel_categorias(datos), width="stretch")
    mayor = datos.iloc[0]
    st.caption(f"{mayor['Categoría']} sola es el {mayor['Porcentaje']:.0f}% "
               f"de lo facturado. Las cifras son porcentajes.")

    # Fuera la columna que solo existe para rotular el arco.
    tabla = datos.drop(columns=["EtiquetaPct"])
    tabla["Ingreso"] = tabla["Ingreso"].map(lambda v: f"${v:,.2f}")
    tabla["Porcentaje"] = tabla["Porcentaje"].map(lambda v: f"{v:.1f}%")
    _tabla("el reparto por categoría", tabla)


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
    izquierda, derecha = st.columns(2)
    with izquierda:
        _pastel_categorias(desde, hasta)
    with derecha:
        _ticket_por_marca(desde, hasta)

    # Los dos cruces cuantitativos van al final y juntos: son los que piden
    # más tiempo de lectura, y de entrada estorbarían a quien solo entra a ver
    # cómo va el mes.
    st.divider()
    izquierda, derecha = st.columns(2)
    with izquierda:
        _dispersion_anio(desde, hasta)
    with derecha:
        _dispersion_renglones(desde, hasta)

    st.divider()
    _top_clientes(desde, hasta)
