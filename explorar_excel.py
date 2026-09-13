"""
Paso 0 — Inspección del archivo de Excel de origen.

Objetivo: verificar la estructura REAL del archivo antes de diseñar la base de
datos. El script no asume que las tablas estén en columnas concretas: detecta
automáticamente los bloques de columnas contiguas con datos (separados por
columnas vacías) y reporta, para cada uno, dimensiones, tipos de dato, nulos
por columna y valores únicos de las columnas categóricas.

Uso:
    .venv\\Scripts\\python.exe explorar_excel.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

# La consola de Windows no usa UTF-8 por defecto; sin esto los acentos se rompen.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Rutas relativas a la raíz del proyecto (no rutas absolutas de Windows).
RAIZ = Path(__file__).resolve().parent

# Ancho de los separadores visuales del reporte.
ANCHO = 78


def titulo(texto: str, caracter: str = "=") -> None:
    """Imprime un encabezado de sección."""
    print()
    print(caracter * ANCHO)
    print(texto)
    print(caracter * ANCHO)


def localizar_excel() -> Path:
    """
    Busca el archivo de Excel de origen en la raíz del proyecto.

    Se busca por patrón en lugar de por nombre exacto porque la especificación
    lo nombra `1_MySQL_AutoSB.xlsx` pero el archivo real usa un punto.
    """
    # Se ignoran los archivos `~$...` que Excel crea mientras el libro está abierto.
    def utiles(patron: str) -> list[Path]:
        return sorted(p for p in RAIZ.glob(patron) if not p.name.startswith("~$"))

    candidatos = utiles("*MySQL_AutoSB*.xlsx") or utiles("*.xlsx")
    if not candidatos:
        raise SystemExit(f"No se encontró ningún archivo .xlsx en {RAIZ}")
    if len(candidatos) > 1:
        print(f"[aviso] Se encontraron varios .xlsx, se usa el primero: "
              f"{[c.name for c in candidatos]}")
    return candidatos[0]


def letra_columna(indice: int) -> str:
    """Convierte un índice 0-based al nombre de columna de Excel (0 -> A)."""
    letras = ""
    indice += 1
    while indice > 0:
        indice, resto = divmod(indice - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def detectar_bloques(df_raw: pd.DataFrame) -> list[tuple[int, int]]:
    """
    Detecta bloques de columnas contiguas que contienen datos.

    Devuelve una lista de tuplas (col_inicio, col_fin) inclusivas, en índices
    0-based. Las columnas completamente vacías actúan como separadores; así es
    como se descubre que una hoja contiene más de una tabla lado a lado.
    """
    columnas_con_datos = [
        i for i in range(df_raw.shape[1]) if df_raw.iloc[:, i].notna().any()
    ]
    if not columnas_con_datos:
        return []

    bloques: list[tuple[int, int]] = []
    inicio = anterior = columnas_con_datos[0]
    for col in columnas_con_datos[1:]:
        if col != anterior + 1:  # hueco -> se cierra el bloque actual
            bloques.append((inicio, anterior))
            inicio = col
        anterior = col
    bloques.append((inicio, anterior))
    return bloques


def extraer_tabla(df_raw: pd.DataFrame, col_ini: int, col_fin: int) -> pd.DataFrame:
    """
    Convierte un bloque de columnas crudas en un DataFrame con encabezado.

    Toma la primera fila del bloque como nombres de columna y descarta las
    filas que quedaron completamente vacías.
    """
    bloque = df_raw.iloc[:, col_ini : col_fin + 1].copy()
    bloque = bloque.dropna(how="all")
    if bloque.empty:
        return bloque

    encabezado = bloque.iloc[0].tolist()
    tabla = bloque.iloc[1:].copy()
    tabla.columns = [str(c).strip() if pd.notna(c) else f"col_{i}"
                     for i, c in enumerate(encabezado)]
    tabla = tabla.dropna(how="all").reset_index(drop=True)
    # Deja que pandas re-infiera los tipos: al leer con header=None todo llega como object.
    return tabla.infer_objects()


def describir_tabla(tabla: pd.DataFrame, nombre: str) -> None:
    """Reporta dimensiones, tipos, nulos y valores únicos de una tabla."""
    titulo(f"{nombre}", "-")
    filas, columnas = tabla.shape
    print(f"Dimensiones: {filas} filas x {columnas} columnas")

    if tabla.empty:
        print("(tabla vacía)")
        return

    # --- Tipos de dato y nulos por columna ---
    print("\nColumnas (tipo | nulos | únicos | ejemplo):")
    for col in tabla.columns:
        serie = tabla[col]
        nulos = int(serie.isna().sum())
        unicos = int(serie.nunique(dropna=True))
        muestra = serie.dropna()
        ejemplo = repr(muestra.iloc[0]) if len(muestra) else "—"
        pct = f"{nulos / filas * 100:5.1f}%"
        print(f"  {str(col)[:26]:<26} {str(serie.dtype):<12} "
              f"nulos={nulos:>4} ({pct})  únicos={unicos:>4}  ej={ejemplo[:24]}")

    # --- Valores únicos de columnas categóricas ---
    # Se consideran categóricas las columnas no numéricas con pocos valores
    # distintos, o cualquier columna con <= 30 valores distintos.
    print("\nValores únicos de columnas categóricas:")
    hubo_categorica = False
    for col in tabla.columns:
        serie = tabla[col]
        unicos = int(serie.nunique(dropna=True))
        es_texto = not pd.api.types.is_numeric_dtype(serie) and \
                   not pd.api.types.is_datetime64_any_dtype(serie)
        if unicos <= 30 and (es_texto or unicos <= 20):
            hubo_categorica = True
            valores = serie.dropna().unique().tolist()
            valores_str = ", ".join(str(v) for v in sorted(valores, key=str))
            print(f"  {col} ({unicos}): {valores_str}")
        elif es_texto and unicos > 30:
            hubo_categorica = True
            top = serie.value_counts().head(5)
            resumen = ", ".join(f"{k} ({v})" for k, v in top.items())
            print(f"  {col} ({unicos} distintos, top 5): {resumen}")
    if not hubo_categorica:
        print("  (ninguna)")

    # --- Rangos de columnas numéricas y de fecha ---
    numericas = [c for c in tabla.columns if pd.api.types.is_numeric_dtype(tabla[c])]
    if numericas:
        print("\nRangos numéricos:")
        for col in numericas:
            serie = pd.to_numeric(tabla[col], errors="coerce")
            print(f"  {col}: min={serie.min()}  max={serie.max()}  suma={serie.sum():,.2f}")

    # Detecta columnas de fecha aunque hayan llegado como texto u object.
    for col in tabla.columns:
        serie = tabla[col]
        if pd.api.types.is_datetime64_any_dtype(serie):
            print(f"\nRango de fechas en '{col}': {serie.min()} a {serie.max()}")
        elif serie.dtype == object:
            convertida = pd.to_datetime(serie, errors="coerce")
            # Solo se reporta si la mayoría de los valores son fechas válidas.
            if convertida.notna().sum() > 0.8 * serie.notna().sum() and serie.notna().sum() > 0:
                print(f"\nRango de fechas en '{col}' (convertida): "
                      f"{convertida.min()} a {convertida.max()}")


def main() -> None:
    ruta = localizar_excel()

    titulo("PASO 0 — INSPECCIÓN DEL ARCHIVO DE ORIGEN")
    print(f"Archivo : {ruta.name}")
    print(f"Ruta    : {ruta.relative_to(RAIZ)} (relativa a la raíz del proyecto)")
    print(f"Tamaño  : {ruta.stat().st_size:,} bytes")
    print(f"pandas  : {pd.__version__}")

    # --- Hojas del libro ---
    libro = pd.ExcelFile(ruta)
    titulo("HOJAS DEL LIBRO")
    for i, hoja in enumerate(libro.sheet_names, 1):
        crudo = pd.read_excel(ruta, sheet_name=hoja, header=None)
        print(f"  {i}. '{hoja}' — {crudo.shape[0]} filas x {crudo.shape[1]} columnas (crudo)")

    # --- Análisis por hoja ---
    tablas: dict[str, pd.DataFrame] = {}
    for hoja in libro.sheet_names:
        crudo = pd.read_excel(ruta, sheet_name=hoja, header=None)
        bloques = detectar_bloques(crudo)

        titulo(f"HOJA '{hoja}'")
        print(f"Rango crudo: {crudo.shape[0]} filas x {crudo.shape[1]} columnas")
        print(f"Bloques de columnas con datos detectados: {len(bloques)}")
        for col_ini, col_fin in bloques:
            print(f"  - Columnas {letra_columna(col_ini)}–{letra_columna(col_fin)} "
                  f"(índices {col_ini}–{col_fin})")

        if len(bloques) > 1:
            print("\n  >>> Esta hoja contiene MÁS DE UNA TABLA lado a lado.")
            print("      Leerla como una sola tabla sería un error.")

        # Vista cruda de las primeras filas para confirmar visualmente el corte.
        print("\nPrimeras 3 filas (crudo, sin encabezado):")
        with pd.option_context("display.max_columns", None, "display.width", 200):
            print(crudo.head(3).to_string())

        for n, (col_ini, col_fin) in enumerate(bloques, 1):
            tabla = extraer_tabla(crudo, col_ini, col_fin)
            etiqueta = (f"HOJA '{hoja}' — TABLA {n} "
                        f"(columnas {letra_columna(col_ini)}–{letra_columna(col_fin)})")
            describir_tabla(tabla, etiqueta)
            tablas[f"{hoja}#{n}"] = tabla

    # --- Validación cruzada de totales ---
    titulo("VALIDACIÓN DE TOTALES")
    sumas: dict[str, float] = {}
    for clave, tabla in tablas.items():
        for col in tabla.columns:
            if str(col).strip().upper() == "TOTAL":
                suma = pd.to_numeric(tabla[col], errors="coerce").sum()
                sumas[f"{clave}.{col}"] = float(suma)
                print(f"  Suma de '{col}' en {clave}: {suma:,.2f}")

    if len(sumas) >= 2:
        valores = list(sumas.values())
        diferencia = max(valores) - min(valores)
        print(f"\n  Diferencia entre sumas: {diferencia:,.2f}")
        if abs(diferencia) < 0.01:
            print("  ✓ Las sumas COINCIDEN.")
        else:
            print("  ✗ Las sumas NO coinciden — revisar antes de migrar.")

    titulo("FIN DE LA INSPECCIÓN")


if __name__ == "__main__":
    main()
