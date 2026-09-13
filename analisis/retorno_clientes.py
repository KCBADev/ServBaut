"""
Frecuencia de retorno de clientes.

Responde: ¿cuántos clientes vuelven, cada cuánto, y qué peso tienen en la
facturación?

Uso:
    .venv\\Scripts\\python.exe analisis\\retorno_clientes.py
"""

from __future__ import annotations

import altair as alt
import pandas as pd

import comun


def main() -> None:
    comun.preparar()
    notas = comun.cargar_notas()

    comun.titulo("FRECUENCIA DE RETORNO DE CLIENTES")

    notas["ingreso"] = notas["total_centavos"].map(comun.pesos)

    # --- Resumen por cliente ---
    por_cliente = (
        notas.groupby(["id_cliente", "cliente"])
        .agg(
            notas=("id_nota", "count"),
            ingreso=("ingreso", "sum"),
            primera=("fecha", "min"),
            ultima=("fecha", "max"),
        )
        .reset_index()
        .sort_values(["notas", "ingreso"], ascending=False)
    )

    # Clientes registrados que nunca han traído un carro.
    with comun.db.conectar() as conexion:
        registrados = pd.read_sql_query(
            "SELECT COUNT(*) AS n FROM clientes", conexion
        )["n"].iloc[0]

    atendidos = len(por_cliente)
    recurrentes = por_cliente[por_cliente["notas"] > 1]
    una_vez = por_cliente[por_cliente["notas"] == 1]

    print(f"  Clientes registrados        : {registrados}")
    print(f"  Clientes con al menos 1 nota: {atendidos}")
    print(f"  Nunca han traído vehículo   : {registrados - atendidos}")
    print()
    print(f"  Vinieron una sola vez : {len(una_vez):>3}  "
          f"({len(una_vez) / atendidos * 100:.1f}%)")
    print(f"  Vinieron más de una vez: {len(recurrentes):>3}  "
          f"({len(recurrentes) / atendidos * 100:.1f}%)")

    # --- Distribución de visitas ---
    distribucion = (
        por_cliente.groupby("notas")
        .agg(clientes=("id_cliente", "count"), ingreso=("ingreso", "sum"))
        .reset_index()
        .rename(columns={"notas": "visitas"})
    )
    print("\n  Distribución de visitas:")
    for _, f in distribucion.iterrows():
        print(f"    {int(f['visitas'])} visita(s): {int(f['clientes']):>3} clientes  "
              f"${f['ingreso']:>11,.2f}")

    if len(recurrentes) < 10:
        print(f"\n  [!] ADVERTENCIA: solo {len(recurrentes)} clientes han vuelto.")
        print("      Es una base demasiado chica para calcular una tasa de")
        print("      retorno confiable o proyectar la frecuencia de regreso.")
        print("      Los números de abajo describen esos casos concretos, no")
        print("      un comportamiento general de tu clientela.")

    # --- Peso de los recurrentes en la facturación ---
    total = por_cliente["ingreso"].sum()
    ingreso_recurrentes = recurrentes["ingreso"].sum()
    print(f"\n  Facturación total            : ${total:,.2f}")
    print(f"  Aportada por los recurrentes : ${ingreso_recurrentes:,.2f} "
          f"({ingreso_recurrentes / total * 100:.1f}%)")
    print(f"  Ticket medio, cliente de una vez : "
          f"${una_vez['ingreso'].mean():,.2f}")
    if len(recurrentes):
        print(f"  Ticket medio, cliente recurrente : "
              f"${recurrentes['ingreso'].mean():,.2f}  (acumulado de sus visitas)")

    # --- Días entre visitas ---
    print("\n  Detalle de los clientes que volvieron:")
    intervalos = []
    for _, cliente in recurrentes.iterrows():
        visitas = notas[notas["id_cliente"] == cliente["id_cliente"]] \
            .sort_values("fecha")
        dias = visitas["fecha"].diff().dt.days.dropna()
        for d in dias:
            intervalos.append({"cliente": cliente["cliente"], "dias": int(d)})
        fechas = ", ".join(visitas["fecha"].dt.strftime("%Y-%m-%d"))
        separacion = ", ".join(f"{int(d)}d" for d in dias)
        print(f"    {cliente['cliente']:<32} {int(cliente['notas'])} visitas  "
              f"${cliente['ingreso']:>10,.2f}")
        print(f"      fechas: {fechas}")
        print(f"      separación: {separacion}")

    if intervalos:
        dias_serie = pd.Series([i["dias"] for i in intervalos])
        print(f"\n  Días entre visitas — mediana: {dias_serie.median():.0f}, "
              f"mínimo: {dias_serie.min()}, máximo: {dias_serie.max()}")
        print(f"  (sobre {len(dias_serie)} intervalos observados; con tan pocos,")
        print("   la mediana es orientativa, no una predicción)")

    # --- Gráfica ---
    grafica = comun.afinar(
        alt.Chart(distribucion)
        .mark_bar(color=comun.SERIE_1, cornerRadiusEnd=3, size=42)
        .encode(
            x=alt.X("visitas:O", title="Número de visitas"),
            y=alt.Y("clientes:Q", title="Clientes"),
            tooltip=[alt.Tooltip("visitas:O", title="Visitas"),
                     alt.Tooltip("clientes:Q", title="Clientes"),
                     alt.Tooltip("ingreso:Q", title="Facturación",
                                 format="$,.2f")],
        )
        .properties(height=260, title="Cuántas veces ha vuelto cada cliente")
    )
    comun.guardar("retorno_distribucion", distribucion, grafica)

    salida = por_cliente.copy()
    salida["primera"] = salida["primera"].dt.strftime("%Y-%m-%d")
    salida["ultima"] = salida["ultima"].dt.strftime("%Y-%m-%d")
    comun.guardar("retorno_por_cliente", salida)
    if intervalos:
        comun.guardar("retorno_intervalos", pd.DataFrame(intervalos))


if __name__ == "__main__":
    main()
