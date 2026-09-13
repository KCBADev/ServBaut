"""
Estacionalidad de la demanda.

Responde: ¿en qué meses y en qué días de la semana entra más trabajo al taller?

Uso:
    .venv\\Scripts\\python.exe analisis\\estacionalidad.py
"""

from __future__ import annotations

import altair as alt
import pandas as pd

import comun

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def main() -> None:
    comun.preparar()
    notas = comun.cargar_notas()

    comun.titulo("ESTACIONALIDAD DE LA DEMANDA")

    notas["ingreso"] = notas["total_centavos"].map(comun.pesos)
    notas["mes"] = notas["fecha"].dt.to_period("M")
    notas["mes_del_anio"] = notas["fecha"].dt.month
    notas["dia_semana"] = notas["fecha"].dt.dayofweek

    # --- Serie mensual completa, con los meses vacíos en cero ---
    por_mes = notas.groupby("mes").agg(
        notas=("id_nota", "count"), ingreso=("ingreso", "sum")
    )
    completo = pd.period_range(por_mes.index.min(), por_mes.index.max(), freq="M")
    por_mes = por_mes.reindex(completo, fill_value=0).rename_axis("mes").reset_index()
    por_mes["mes"] = por_mes["mes"].astype(str)

    meses_activos = int((por_mes["notas"] > 0).sum())
    meses_vacios = int((por_mes["notas"] == 0).sum())

    print(f"  Periodo cubierto     : {por_mes['mes'].iloc[0]} a {por_mes['mes'].iloc[-1]}")
    print(f"  Meses en el periodo  : {len(por_mes)}")
    print(f"  Meses con trabajo    : {meses_activos}")
    print(f"  Meses sin una sola nota: {meses_vacios}")

    print("\n  Actividad por mes:")
    for _, fila in por_mes.iterrows():
        barra = "█" * int(fila["notas"])
        print(f"    {fila['mes']}  {int(fila['notas']):>2} notas  "
              f"${fila['ingreso']:>10,.2f}  {barra}")

    # --- Advertencia sobre la validez del análisis ---
    if meses_vacios >= len(por_mes) / 3:
        print(f"\n  [!] ADVERTENCIA: {meses_vacios} de {len(por_mes)} meses no tienen")
        print("      ninguna nota. Eso no es estacionalidad: es que el registro")
        print("      del taller empieza a ser continuo hasta cierta fecha. Con")
        print("      un solo ciclo anual completo NO se puede separar 'temporada")
        print("      baja' de 'todavía no se anotaban las notas'. Trata lo que")
        print("      sigue como una foto del periodo activo, no como un patrón")
        print("      estacional que se pueda proyectar al año que viene.")

    # --- Por mes del año ---
    por_mes_anio = (
        notas.groupby("mes_del_anio")
        .agg(notas=("id_nota", "count"), ingreso=("ingreso", "sum"))
        .reindex(range(1, 13), fill_value=0)
        .reset_index()
    )
    por_mes_anio["Mes"] = por_mes_anio["mes_del_anio"].map(lambda m: MESES[m - 1])

    print("\n  Acumulado por mes del año (todos los años juntos):")
    for _, fila in por_mes_anio.iterrows():
        print(f"    {fila['Mes']:<11} {int(fila['notas']):>2} notas  "
              f"${fila['ingreso']:>10,.2f}")

    # --- Por día de la semana ---
    por_dia = (
        notas.groupby("dia_semana")
        .agg(notas=("id_nota", "count"), ingreso=("ingreso", "sum"))
        .reindex(range(7), fill_value=0)
        .reset_index()
    )
    por_dia["Día"] = por_dia["dia_semana"].map(lambda d: DIAS[d])

    print("\n  Por día de la semana:")
    for _, fila in por_dia.iterrows():
        print(f"    {fila['Día']:<11} {int(fila['notas']):>2} notas  "
              f"${fila['ingreso']:>10,.2f}")

    ocupados = por_dia[por_dia["notas"] > 0]
    if len(ocupados):
        mejor = ocupados.loc[ocupados["notas"].idxmax()]
        print(f"\n  Día con más entradas: {mejor['Día']} ({int(mejor['notas'])} notas)")
    sin_trabajo = por_dia[por_dia["notas"] == 0]["Día"].tolist()
    if sin_trabajo:
        print(f"  Días sin ninguna nota: {', '.join(sin_trabajo)}")

    # --- Gráficas ---
    serie = comun.afinar(
        alt.Chart(por_mes.assign(Mes=pd.to_datetime(por_mes["mes"] + "-01")))
        .mark_bar(color=comun.SERIE_1, cornerRadiusEnd=3)
        .encode(
            x=alt.X("Mes:T", title=None, axis=alt.Axis(format="%b %Y", grid=False)),
            y=alt.Y("notas:Q", title="Notas"),
            tooltip=[alt.Tooltip("Mes:T", format="%B %Y"),
                     alt.Tooltip("notas:Q", title="Notas"),
                     alt.Tooltip("ingreso:Q", title="Ingreso", format="$,.2f")],
        )
        .properties(height=260, title="Notas por mes (los meses vacíos son ceros reales)")
    )
    comun.guardar("estacionalidad_por_mes", por_mes, serie)

    grafica_dias = comun.afinar(
        alt.Chart(por_dia)
        .mark_bar(color=comun.SERIE_1, cornerRadiusEnd=3, size=28)
        .encode(
            x=alt.X("Día:N", title=None, sort=DIAS),
            y=alt.Y("notas:Q", title="Notas"),
            tooltip=[alt.Tooltip("Día:N"), alt.Tooltip("notas:Q", title="Notas")],
        )
        .properties(height=240, title="Notas por día de la semana")
    )
    comun.guardar("estacionalidad_por_dia", por_dia[["Día", "notas", "ingreso"]],
                  grafica_dias)
    comun.guardar("estacionalidad_por_mes_del_anio",
                  por_mes_anio[["Mes", "notas", "ingreso"]])


if __name__ == "__main__":
    main()
