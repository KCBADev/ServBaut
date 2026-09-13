"""
Paso 0 (segunda parte) — Verificación de integridad y de las reglas de negocio.

La inspección estructural (explorar_excel.py) ya confirmó qué hay en el archivo.
Este script verifica lo que realmente condiciona el diseño del esquema:
integridad referencial, consistencia de los totales, calidad del texto y si el
catálogo se puede derivar sin ambigüedad.

Uso:
    .venv\\Scripts\\python.exe verificar_datos.py
"""

from __future__ import annotations

import sys

import pandas as pd

# Se reutiliza la lógica de lectura ya validada en el script de inspección.
from explorar_excel import ANCHO, detectar_bloques, extraer_tabla, localizar_excel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def titulo(texto: str) -> None:
    print()
    print("=" * ANCHO)
    print(texto)
    print("=" * ANCHO)


def check(condicion: bool, mensaje_ok: str, mensaje_error: str) -> bool:
    """Imprime el resultado de una comprobación y lo devuelve."""
    print(f"  {'[OK] ' if condicion else '[!!] '}{mensaje_ok if condicion else mensaje_error}")
    return condicion


def cargar_tablas() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Devuelve (clientes, notas, partidas) leídas del Excel de origen."""
    ruta = localizar_excel()

    crudo_tc = pd.read_excel(ruta, sheet_name="TC_TA", header=None)
    bloques_tc = detectar_bloques(crudo_tc)
    clientes = extraer_tabla(crudo_tc, *bloques_tc[0])
    notas = extraer_tabla(crudo_tc, *bloques_tc[1])

    crudo_tsa = pd.read_excel(ruta, sheet_name="TSA", header=None)
    bloques_tsa = detectar_bloques(crudo_tsa)
    partidas = extraer_tabla(crudo_tsa, *bloques_tsa[0])

    return clientes, notas, partidas


def main() -> None:
    clientes, notas, partidas = cargar_tablas()

    # ------------------------------------------------------------------
    titulo("1. INTEGRIDAD REFERENCIAL")
    # ------------------------------------------------------------------
    ids_cliente = set(clientes["ID_Cliente (PK)"])
    ids_nota = set(notas["ID_N (PK)"])

    huerfanos_notas = set(notas["ID_Cliente (FK)"]) - ids_cliente
    check(not huerfanos_notas,
          "Notas → Clientes: sin huérfanos",
          f"Notas → Clientes: IDs huérfanos {sorted(huerfanos_notas)}")

    huerfanos_partidas = set(partidas["ID_N (FK)"]) - ids_nota
    check(not huerfanos_partidas,
          "Partidas → Notas: sin huérfanos",
          f"Partidas → Notas: IDs huérfanos {sorted(huerfanos_partidas)}")

    notas_sin_partidas = ids_nota - set(partidas["ID_N (FK)"])
    check(not notas_sin_partidas,
          f"Las {len(ids_nota)} notas tienen al menos una partida",
          f"Notas sin partidas: {sorted(notas_sin_partidas)}")

    # Clientes sin notas: no es un error, pero conviene saberlo.
    clientes_sin_notas = ids_cliente - set(notas["ID_Cliente (FK)"])
    print(f"  [i]  Clientes sin ninguna nota: {len(clientes_sin_notas)} "
          f"{sorted(clientes_sin_notas) if clientes_sin_notas else ''}")

    # ------------------------------------------------------------------
    titulo("2. CONSISTENCIA DE TOTALES")
    # ------------------------------------------------------------------
    suma_notas = float(pd.to_numeric(notas["TOTAL"]).sum())
    suma_partidas = float(pd.to_numeric(partidas["Total"]).sum())
    print(f"  Suma TOTAL en Notas    : {suma_notas:>15,.2f}")
    print(f"  Suma Total en Partidas : {suma_partidas:>15,.2f}")
    print(f"  Esperado por la spec   : {381146.50:>15,.2f}")
    check(abs(suma_notas - suma_partidas) < 0.01,
          "Los totales globales coinciden",
          "Los totales globales NO coinciden")
    check(abs(suma_notas - 381146.50) < 0.01,
          "Coincide con el valor esperado en la especificación",
          "NO coincide con el valor esperado en la especificación")

    # Regla obligatoria: el TOTAL de cada nota == suma de sus partidas.
    print("\n  Verificación nota por nota:")
    suma_por_nota = partidas.groupby("ID_N (FK)")["Total"].sum()
    comparacion = notas.set_index("ID_N (PK)")["TOTAL"].astype(float).to_frame("total_nota")
    comparacion["suma_partidas"] = suma_por_nota
    comparacion["diferencia"] = comparacion["total_nota"] - comparacion["suma_partidas"]
    descuadradas = comparacion[comparacion["diferencia"].abs() >= 0.01]
    if check(descuadradas.empty,
             f"Las {len(comparacion)} notas cuadran con sus partidas",
             f"{len(descuadradas)} notas NO cuadran"):
        pass
    else:
        print(descuadradas.to_string())

    # ¿Total de partida == Cantidad x Precio unitario?
    print("\n  Verificación de cada partida (Total = Cantidad × Precio unitario):")
    calculado = pd.to_numeric(partidas["Cantidad"]) * pd.to_numeric(partidas["Precio unitario"])
    diferencia_partida = pd.to_numeric(partidas["Total"]) - calculado
    malas = partidas[diferencia_partida.abs() >= 0.01]
    if check(malas.empty,
             "Todas las partidas cumplen Total = Cantidad × Precio unitario",
             f"{len(malas)} partidas NO cumplen la fórmula"):
        pass
    else:
        cols = ["ID_N (FK)", "Descripción", "Cantidad", "Precio unitario", "Total"]
        print(malas[cols].to_string())

    # ------------------------------------------------------------------
    titulo("3. LLAVE PRIMARIA DE PARTIDAS (ID_SA)")
    # ------------------------------------------------------------------
    id_sa = partidas["ID_SA (PK)"]
    no_nulos = id_sa.dropna()
    print(f"  Filas totales      : {len(partidas)}")
    print(f"  ID_SA nulos        : {int(id_sa.isna().sum())}")
    print(f"  ID_SA no nulos     : {len(no_nulos)}")
    print(f"  ID_SA distintos    : {no_nulos.nunique()}")
    print(f"  Rango              : {no_nulos.min():.0f} – {no_nulos.max():.0f}")
    check(no_nulos.nunique() == len(no_nulos),
          "Los ID_SA existentes no tienen duplicados",
          "Hay ID_SA duplicados")
    print("  [i]  Conclusión: la PK es inservible tal cual → se regenera como "
          "INTEGER PRIMARY KEY AUTOINCREMENT.")

    # ------------------------------------------------------------------
    titulo("4. CALIDAD DE LOS DATOS DE TEXTO")
    # ------------------------------------------------------------------
    # Espacios sobrantes: afectan búsquedas, detección de duplicados y joins.
    for nombre, tabla in (("Clientes", clientes), ("Notas", notas), ("Partidas", partidas)):
        for col in tabla.columns:
            serie = tabla[col]
            if serie.dtype == object or str(serie.dtype).startswith("str"):
                texto = serie.dropna().astype(str)
                con_espacios = texto[texto != texto.str.strip()]
                if len(con_espacios):
                    print(f"  [!!] {nombre}.{col}: {len(con_espacios)} valores con "
                          f"espacios sobrantes → ej. {con_espacios.iloc[0]!r}")

    # Nombres de cliente duplicados (tras normalizar espacios).
    nombres = clientes["Nombre"].astype(str).str.strip()
    duplicados = nombres[nombres.duplicated(keep=False)]
    check(duplicados.empty,
          "No hay nombres de cliente duplicados",
          f"Nombres duplicados: {sorted(set(duplicados))}")

    # Teléfonos: se leen como float y deben guardarse como texto.
    tel = clientes["Telefono"].dropna()
    tel_texto = tel.map(lambda v: str(int(v)))
    longitudes = tel_texto.str.len().value_counts().sort_index()
    print(f"\n  Teléfonos no nulos: {len(tel)} de {len(clientes)}")
    print(f"  Longitudes en dígitos: {dict(longitudes)}")
    check(set(longitudes.index) == {10},
          "Todos los teléfonos tienen 10 dígitos",
          f"Hay teléfonos con longitud distinta de 10: {dict(longitudes)}")
    print(f"  [i]  Convertidos a texto quedan así: {tel_texto.iloc[0]!r} "
          f"(no {tel.iloc[0]!r})")

    # La columna 'Tipo' (modelo) llegó como object: puede tener tipos mezclados.
    tipos_python = notas["Tipo"].map(lambda v: type(v).__name__).value_counts()
    print(f"\n  Tipos de Python en Notas.'Tipo' (el MODELO): {dict(tipos_python)}")
    if len(tipos_python) > 1:
        no_texto = notas[notas["Tipo"].map(lambda v: not isinstance(v, str))]
        print(f"  [!!] {len(no_texto)} modelos no son texto → "
              f"{no_texto['Tipo'].tolist()}")
        print("       Se deben guardar como TEXT para no perder el formato.")

    # Fila con 'Tipo De concepto' nulo.
    sin_tipo = partidas[partidas["Tipo De concepto"].isna()]
    if len(sin_tipo):
        print(f"\n  [!!] {len(sin_tipo)} partida(s) sin 'Tipo De concepto':")
        cols = ["ID_N (FK)", "Categoría", "Acción", "Descripción",
                "Cantidad", "Precio unitario", "Total"]
        print(sin_tipo[cols].to_string(index=False))

    # ------------------------------------------------------------------
    titulo("5. ¿SE PUEDE DERIVAR EL CATÁLOGO SIN AMBIGÜEDAD?")
    # ------------------------------------------------------------------
    # La spec pide "las 89 descripciones únicas con su Tipo y Categoría". Eso
    # solo funciona si cada descripción tiene UN solo tipo y UNA sola categoría.
    print(f"  Descripciones únicas: {partidas['Descripción'].nunique()}")

    por_descripcion = partidas.groupby("Descripción").agg(
        tipos=("Tipo De concepto", lambda s: sorted(set(s.dropna()))),
        categorias=("Categoría", lambda s: sorted(set(s.dropna()))),
        veces=("Descripción", "size"),
    )
    ambiguas_tipo = por_descripcion[por_descripcion["tipos"].map(len) > 1]
    ambiguas_categoria = por_descripcion[por_descripcion["categorias"].map(len) > 1]

    check(ambiguas_tipo.empty,
          "Cada descripción tiene un único 'Tipo De concepto'",
          f"{len(ambiguas_tipo)} descripciones tienen MÁS DE UN tipo")
    if not ambiguas_tipo.empty:
        print(ambiguas_tipo[["tipos", "veces"]].to_string())

    check(ambiguas_categoria.empty,
          "Cada descripción tiene una única 'Categoría'",
          f"{len(ambiguas_categoria)} descripciones aparecen en VARIAS categorías")
    if not ambiguas_categoria.empty:
        print("\n  Descripciones que cruzan categorías:")
        detalle = ambiguas_categoria.copy()
        detalle["categorias"] = detalle["categorias"].map(lambda c: ", ".join(c))
        print(detalle[["categorias", "veces"]].to_string())
        combinaciones = partidas.groupby(
            ["Descripción", "Categoría", "Tipo De concepto"], dropna=False
        ).size()
        print(f"\n  [i]  Descripciones únicas          : {partidas['Descripción'].nunique()}")
        print(f"  [i]  Combinaciones desc+categoría+tipo: {len(combinaciones)}")
        print("       → la PK del catálogo NO puede ser solo la descripción.")

    # Precio más reciente por concepto: requiere la fecha de la nota.
    print("\n  Derivación del precio más reciente:")
    partidas_con_fecha = partidas.merge(
        notas[["ID_N (PK)", "Fecha"]], left_on="ID_N (FK)", right_on="ID_N (PK)", how="left"
    )
    check(partidas_con_fecha["Fecha"].notna().all(),
          "Todas las partidas tienen fecha vía su nota (se puede calcular el precio vigente)",
          "Hay partidas sin fecha asociada")

    # Cuántos conceptos han tenido más de un precio distinto en el histórico.
    precios_distintos = partidas.groupby("Descripción")["Precio unitario"].nunique()
    variables = precios_distintos[precios_distintos > 1]
    print(f"  [i]  Conceptos con más de un precio histórico: {len(variables)} "
          f"de {len(precios_distintos)}")

    titulo("FIN DE LA VERIFICACIÓN")


if __name__ == "__main__":
    main()
