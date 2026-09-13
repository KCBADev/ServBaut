"""
Ticket promedio por marca de vehículo.

Responde: ¿qué marcas dejan las notas más grandes, y en cuáles hay suficientes
casos para creerle al promedio?

Uso:
    .venv\\Scripts\\python.exe analisis\\ticket_por_marca.py
"""

from __future__ import annotations

import altair as alt

import comun

# Debajo de este número de notas, un promedio se mueve demasiado con un solo
# caso como para tomarlo en serio.
MINIMO_CONFIABLE = 3


def main() -> None:
    comun.preparar()
    notas = comun.cargar_notas()

    comun.titulo("TICKET PROMEDIO POR MARCA")

    notas["ingreso"] = notas["total_centavos"].map(comun.pesos)

    resumen = (
        notas.groupby("marca")
        .agg(
            notas_count=("id_nota", "count"),
            ingreso=("ingreso", "sum"),
            ticket_medio=("ingreso", "mean"),
            ticket_mediano=("ingreso", "median"),
            minimo=("ingreso", "min"),
            maximo=("ingreso", "max"),
        )
        .reset_index()
        .sort_values("ticket_medio", ascending=False)
    )
    resumen["confiable"] = resumen["notas_count"] >= MINIMO_CONFIABLE

    global_medio = notas["ingreso"].mean()
    print(f"  Ticket promedio del taller: ${global_medio:,.2f}")
    print(f"  Notas totales             : {len(notas)}")
    print(f"  Marcas distintas          : {len(resumen)}")

    print(f"\n  {'Marca':<14}{'Notas':>7}{'Promedio':>14}{'Mediana':>14}"
          f"{'Mínimo':>13}{'Máximo':>13}")
    print("  " + "-" * 75)
    for _, f in resumen.iterrows():
        marca = f["marca"] + ("" if f["confiable"] else " *")
        print(f"  {marca:<14}{int(f['notas_count']):>7}"
              f" ${f['ticket_medio']:>11,.2f} ${f['ticket_mediano']:>11,.2f}"
              f" ${f['minimo']:>10,.2f} ${f['maximo']:>10,.2f}")

    pocas = resumen[~resumen["confiable"]]
    if len(pocas):
        print(f"\n  * Marcas con menos de {MINIMO_CONFIABLE} notas: "
              f"{len(pocas)} de {len(resumen)}.")
        print("    Su 'promedio' es prácticamente una sola nota; no las uses")
        print("    para decidir precios ni para comparar contra otras marcas.")

    confiables = resumen[resumen["confiable"]]
    if len(confiables):
        print(f"\n  Marcas con {MINIMO_CONFIABLE} notas o más "
              f"({len(confiables)} de {len(resumen)}):")
        for _, f in confiables.iterrows():
            diferencia = (f["ticket_medio"] - global_medio) / global_medio * 100
            señal = "por encima" if diferencia >= 0 else "por debajo"
            print(f"    {f['marca']:<14} ${f['ticket_medio']:>10,.2f}  "
                  f"({abs(diferencia):>5.1f}% {señal} del promedio general)")

        # La diferencia entre media y mediana delata notas atípicas.
        sesgadas = confiables[
            (confiables["ticket_medio"] - confiables["ticket_mediano"]).abs()
            > global_medio * 0.25
        ]
        if len(sesgadas):
            print("\n  Media contra mediana (una brecha grande = alguna nota atípica):")
            for _, f in sesgadas.iterrows():
                print(f"    {f['marca']:<14} media ${f['ticket_medio']:,.2f} vs "
                      f"mediana ${f['ticket_mediano']:,.2f}  "
                      f"-> la jala una nota de ${f['maximo']:,.2f}")
        else:
            print("\n  Media y mediana van parejas en todas las marcas con")
            print("  suficientes notas: ninguna la está jalando una nota atípica.")

    # --- Gráfica: solo las marcas con suficientes casos ---
    if len(confiables):
        datos = confiables.rename(columns={"marca": "Marca",
                                           "ticket_medio": "Ticket"})
        grafica = comun.barras(
            datos, "Marca", "Ticket", "Ticket promedio",
            f"Ticket promedio por marca (solo marcas con {MINIMO_CONFIABLE}+ notas)",
        )
        comun.guardar("ticket_por_marca", resumen, grafica)
    else:
        comun.guardar("ticket_por_marca", resumen)


if __name__ == "__main__":
    main()
