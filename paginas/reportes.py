"""
Pantalla de reportes.

Trae a la aplicación los cuatro análisis que hasta ahora solo corrían por
terminal. Las consultas viven en db.py; aquí solo se dibujan.

Cada reporte dice cuándo los datos NO alcanzan para sostener la conclusión:
un promedio sobre una sola nota, o una tasa de retorno sobre cuatro clientes,
no son resultados, son ruido con formato de resultado.
"""

from __future__ import annotations

from datetime import datetime

import altair as alt
import pandas as pd
import streamlit as st

import db
import styles
from paginas.dashboard import _afinar, _barras_horizontales, _filtro_fechas, _pesos

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MINIMO_CONFIABLE = 3


def _tabla(titulo: str, datos: pd.DataFrame) -> None:
    with st.expander(f"Ver {titulo} en tabla"):
        st.dataframe(datos, width="stretch", hide_index=True)


# ---------------------------------------------------------------------------

def _estacionalidad(desde: str | None, hasta: str | None) -> None:
    st.subheader("Estacionalidad de la demanda")

    filas = db.ingresos_por_mes(desde, hasta)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    datos = pd.DataFrame([
        {"Mes": pd.to_datetime(f["mes"] + "-01"),
         "Notas": f["num_notas"],
         "Ingreso": _pesos(f["ingreso_centavos"])}
        for f in filas
    ])
    completo = pd.date_range(datos["Mes"].min(), datos["Mes"].max(), freq="MS")
    datos = (datos.set_index("Mes").reindex(completo, fill_value=0)
             .rename_axis("Mes").reset_index())

    vacios = int((datos["Notas"] == 0).sum())
    if vacios:
        st.warning(
            f"**{vacios} de {len(datos)} meses no tienen ninguna nota.** Eso no "
            "es temporada baja: es historial que todavía no se ha capturado. "
            "Con un solo ciclo anual completo no se puede separar una cosa de "
            "la otra, así que léelo como una foto del periodo capturado y no "
            "como un patrón que se pueda proyectar."
        )

    grafica = _afinar(
        alt.Chart(datos)
        .mark_bar(color=styles.SERIE_1, cornerRadiusEnd=3)
        .encode(
            x=alt.X("Mes:T", title=None, axis=alt.Axis(format="%b %Y", grid=False)),
            y=alt.Y("Notas:Q", title="Notas"),
            tooltip=[alt.Tooltip("Mes:T", format="%B %Y"),
                     alt.Tooltip("Notas:Q"),
                     alt.Tooltip("Ingreso:Q", format="$,.2f")],
        )
        .properties(height=260)
    )
    st.altair_chart(grafica, width="stretch")

    salida = datos.copy()
    salida["Mes"] = salida["Mes"].dt.strftime("%Y-%m")
    salida["Ingreso"] = salida["Ingreso"].map(lambda v: f"${v:,.2f}")
    _tabla("la actividad por mes", salida)


def _categorias(desde: str | None, hasta: str | None) -> None:
    st.subheader("Categorías por facturación")
    st.caption(
        "Facturación, no rentabilidad: el histórico trae precios de venta pero "
        "no costos, así que no se puede calcular margen."
    )

    filas = db.ingresos_por_categoria(desde, hasta)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    total = sum(f["ingreso_centavos"] for f in filas)
    datos = pd.DataFrame([
        {"Categoría": f["categoria"],
         "Ingreso": _pesos(f["ingreso_centavos"]),
         "Partidas": f["num_partidas"],
         "Porcentaje": f["ingreso_centavos"] / total * 100 if total else 0}
        for f in filas
    ])
    datos["Acumulado"] = datos["Porcentaje"].cumsum()

    hasta_80 = int((datos["Acumulado"] <= 80).sum()) + 1
    st.markdown(
        f"**{hasta_80} de {len(datos)} categorías** generan el 80% de la "
        f"facturación. La primera, **{datos.iloc[0]['Categoría']}**, "
        f"representa el {datos.iloc[0]['Porcentaje']:.1f}%."
    )

    st.altair_chart(
        _barras_horizontales(datos, "Categoría", "Ingreso", "Facturación"),
        width="stretch",
    )

    salida = datos.copy()
    salida["Ingreso"] = salida["Ingreso"].map(lambda v: f"${v:,.2f}")
    salida["Porcentaje"] = salida["Porcentaje"].map(lambda v: f"{v:.1f}%")
    salida["Acumulado"] = salida["Acumulado"].map(lambda v: f"{v:.1f}%")
    _tabla("las categorías", salida)


def _retorno(desde: str | None, hasta: str | None) -> None:
    st.subheader("Retorno de clientes")

    datos = db.kpis(desde, hasta)
    atendidos = datos["clientes_atendidos"]
    recurrentes = datos["clientes_recurrentes"]
    if not atendidos:
        st.info("Sin datos en el rango.")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Clientes atendidos", atendidos)
    col2.metric("Volvieron", recurrentes)
    col3.metric("Tasa de retorno", f"{recurrentes / atendidos * 100:.1f}%")

    if recurrentes < 10:
        st.warning(
            f"Solo **{recurrentes} clientes** han vuelto. Es una base "
            "demasiado chica para calcular una tasa de retorno confiable o "
            "proyectar cada cuánto regresan: los números describen esos casos "
            "concretos, no el comportamiento de tu clientela."
        )

    top = db.top_clientes(desde, hasta, limite=10)
    tabla = pd.DataFrame([
        {"Cliente": f["nombre"],
         "Notas": f["num_notas"],
         "Facturado": _pesos(f["ingreso_centavos"])}
        for f in top
    ])
    st.altair_chart(
        _barras_horizontales(tabla, "Cliente", "Facturado", "Facturación"),
        width="stretch",
    )
    salida = tabla.copy()
    salida["Facturado"] = salida["Facturado"].map(lambda v: f"${v:,.2f}")
    _tabla("el top de clientes", salida)


def _ticket_marca(desde: str | None, hasta: str | None) -> None:
    st.subheader("Ticket promedio por marca")

    filas = db.ticket_por_marca(desde, hasta, minimo_notas=1)
    if not filas:
        st.info("Sin datos en el rango.")
        return

    datos = pd.DataFrame([
        {"Marca": f["marca"],
         "Notas": f["num_notas"],
         "Ticket": _pesos(f["ticket_centavos"])}
        for f in filas
    ])
    confiables = datos[datos["Notas"] >= MINIMO_CONFIABLE]
    pocas = len(datos) - len(confiables)

    if pocas:
        st.warning(
            f"**{pocas} de {len(datos)} marcas** tienen menos de "
            f"{MINIMO_CONFIABLE} notas. Su promedio es prácticamente una sola "
            "nota; quedan fuera de la gráfica y no sirven para decidir precios."
        )

    if len(confiables):
        st.altair_chart(
            _barras_horizontales(confiables, "Marca", "Ticket",
                                 "Ticket promedio"),
            width="stretch",
        )

    salida = datos.copy()
    salida["Ticket"] = salida["Ticket"].map(lambda v: f"${v:,.2f}")
    salida["Confiable"] = salida["Notas"].map(
        lambda n: "Sí" if n >= MINIMO_CONFIABLE else "No")
    _tabla("todas las marcas", salida)


# ---------------------------------------------------------------------------

def mostrar() -> None:
    styles.apply_global_theme()
    st.title("Reportes")

    desde, hasta = _filtro_fechas()
    if desde is None:
        st.info("Todavía no hay notas registradas.")
        return

    st.divider()
    estacionalidad, categorias, retorno, marcas = st.tabs([
        "Estacionalidad", "Categorías", "Retorno de clientes", "Ticket por marca",
    ])
    with estacionalidad:
        _estacionalidad(desde, hasta)
    with categorias:
        _categorias(desde, hasta)
    with retorno:
        _retorno(desde, hasta)
    with marcas:
        _ticket_marca(desde, hasta)
