"""
Categorías más rentables.

ADVERTENCIA IMPORTANTE: el archivo de origen no trae costos, solo precios de
venta. Sin costo no se puede calcular rentabilidad — lo que este script mide
es FACTURACIÓN, que no es lo mismo. Una categoría puede facturar mucho y dejar
poco margen. Para rentabilidad de verdad haría falta capturar el costo de cada
refacción y el costo por hora de la mano de obra.

Uso:
    .venv\\Scripts\\python.exe analisis\\rentabilidad_categorias.py
"""

from __future__ import annotations

import altair as alt

import comun


def main() -> None:
    comun.preparar()
    partidas = comun.cargar_partidas()

    comun.titulo("CATEGORÍAS POR FACTURACIÓN")
    print("  [!] Sin datos de costo, esto mide facturación, no rentabilidad.")
    print("      Ver la nota al inicio del script.")

    partidas["ingreso"] = partidas["total_centavos"].map(comun.pesos)
    total = partidas["ingreso"].sum()

    resumen = (
        partidas.groupby("categoria")
        .agg(
            ingreso=("ingreso", "sum"),
            partidas=("id_partida", "count"),
            notas=("id_nota", "nunique"),
            ticket_medio=("ingreso", "mean"),
        )
        .sort_values("ingreso", ascending=False)
        .reset_index()
    )
    resumen["porcentaje"] = resumen["ingreso"] / total * 100
    resumen["acumulado"] = resumen["porcentaje"].cumsum()

    print(f"\n  Facturación total: ${total:,.2f}\n")
    print(f"  {'Categoría':<18}{'Ingreso':>13}{'%':>8}{'Acum.':>8}"
          f"{'Partidas':>10}{'Medio':>12}")
    print("  " + "-" * 69)
    for _, f in resumen.iterrows():
        print(f"  {f['categoria']:<18}${f['ingreso']:>11,.2f}"
              f"{f['porcentaje']:>7.1f}%{f['acumulado']:>7.1f}%"
              f"{int(f['partidas']):>10} ${f['ticket_medio']:>10,.2f}")

    # --- Concentración: ¿cuántas categorías hacen el 80%? ---
    hasta_80 = int((resumen["acumulado"] <= 80).sum()) + 1
    print(f"\n  Concentración: {hasta_80} de {len(resumen)} categorías generan "
          f"el 80% de la facturación.")
    print(f"  La primera sola ({resumen.iloc[0]['categoria']}) representa el "
          f"{resumen.iloc[0]['porcentaje']:.1f}%.")

    # --- Mix producto/servicio dentro de cada categoría ---
    mix = (
        partidas.pivot_table(index="categoria", columns="tipo_concepto",
                             values="ingreso", aggfunc="sum", fill_value=0)
        .reset_index()
    )
    for columna in ("Producto", "Servicio"):
        if columna not in mix.columns:
            mix[columna] = 0.0
    mix["total"] = mix["Producto"] + mix["Servicio"]
    mix["% servicio"] = mix["Servicio"] / mix["total"] * 100
    mix = mix.sort_values("total", ascending=False)

    print("\n  Mix dentro de cada categoría (qué tanto es mano de obra y servicios):")
    print(f"  {'Categoría':<18}{'Producto':>13}{'Servicio':>14}{'% servicio':>13}")
    print("  " + "-" * 58)
    for _, f in mix.iterrows():
        print(f"  {f['categoria']:<18}${f['Producto']:>11,.2f}"
              f" ${f['Servicio']:>11,.2f}{f['% servicio']:>12.1f}%")

    print("\n  Lectura: una categoría con alto % de servicio depende del tiempo")
    print("  del taller; una con alto % de producto depende de la refacción y")
    print("  del margen que dé el proveedor. Son negocios distintos.")

    # --- Gráficas ---
    grafica = comun.barras(
        resumen.rename(columns={"categoria": "Categoría", "ingreso": "Ingreso"}),
        "Categoría", "Ingreso", "Facturación",
        "Facturación por categoría (no es margen: no hay datos de costo)",
    )
    comun.guardar("categorias_facturacion", resumen, grafica)

    largo = mix.melt(id_vars="categoria", value_vars=["Producto", "Servicio"],
                     var_name="Tipo", value_name="Ingreso")
    apilada = comun.afinar(
        alt.Chart(largo)
        .mark_bar(stroke=comun.SUPERFICIE, strokeWidth=2, height=16)
        .encode(
            x=alt.X("Ingreso:Q", title="Facturación", stack="zero",
                    axis=alt.Axis(format="$,.0f")),
            y=alt.Y("categoria:N", title=None,
                    sort=alt.SortField("Ingreso", order="descending")),
            color=alt.Color("Tipo:N",
                            scale=alt.Scale(domain=["Producto", "Servicio"],
                                            range=[comun.SERIE_1, comun.SERIE_2]),
                            legend=alt.Legend(title=None, orient="top")),
            tooltip=[alt.Tooltip("categoria:N", title="Categoría"),
                     alt.Tooltip("Tipo:N"),
                     alt.Tooltip("Ingreso:Q", format="$,.2f")],
        )
        .properties(height=max(160, 26 * mix["categoria"].nunique()),
                    title="Producto vs Servicio dentro de cada categoría")
    )
    comun.guardar("categorias_mix", mix, apilada)


if __name__ == "__main__":
    main()
