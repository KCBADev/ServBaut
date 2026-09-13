"""
Exportación de datos — Auto Servicio Bautista.

Genera la base en formatos que se puedan trabajar fuera de la aplicación.

OJO CON POWER BI: no puede abrir un archivo `.sql`. Un volcado SQL es un guion
de instrucciones, no una fuente de datos; hay que ejecutarlo primero en un
servidor (MySQL, MariaDB, SQL Server) y luego conectar Power BI a ESE servidor.
Por eso aquí hay tres formatos:

  * `.sql`  — volcado en dialecto MySQL, para levantar la base en un servidor.
              Es el camino si quieres la base viva y consultable.
  * `.csv`  — un archivo por tabla dentro de un ZIP. Power BI los importa
              directo con «Obtener datos → Carpeta» y es lo más rápido.
  * `.xlsx` — un libro con una hoja por tabla. También se importa directo y es
              más cómodo de revisar a ojo antes de cargarlo.

Los importes salen en DOS columnas: los centavos enteros tal como se guardan y
su equivalente en pesos ya dividido, para que en Power BI no haya que recordar
la conversión ni arriesgarse a graficar centavos como si fueran pesos.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime

import pandas as pd

import db

# Orden de volcado: las tablas referenciadas van antes que quienes las
# referencian, para que el guion se pueda ejecutar de corrido.
TABLAS = [
    "categorias", "acciones", "marcas", "categorias_producto",
    "marcas_producto", "clientes", "vehiculos", "catalogo", "productos",
    "notas", "partidas", "usuarios", "taller",
]

# Las columnas de dinero se guardan en centavos; se acompañan de su versión en
# pesos para que el análisis externo no tenga que dividir a mano.
COLUMNAS_CENTAVOS = "_centavos"

# `usuarios` lleva hashes de contraseñas: nunca sale en una exportación
# pensada para análisis.
TABLAS_SENSIBLES = {"usuarios"}


def _tablas_existentes(conexion) -> list[str]:
    presentes = {
        f["name"] for f in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%'")
    }
    return [t for t in TABLAS if t in presentes and t not in TABLAS_SENSIBLES]


def _con_pesos(marco: pd.DataFrame) -> pd.DataFrame:
    """Duplica cada columna de centavos con su equivalente en pesos."""
    salida = marco.copy()
    for columna in marco.columns:
        if columna.endswith(COLUMNAS_CENTAVOS):
            nombre = columna.replace(COLUMNAS_CENTAVOS, "_pesos")
            salida[nombre] = marco[columna].map(
                lambda v: None if pd.isna(v) else round(v / 100, 2))
    return salida


def leer_tablas(con_pesos: bool = True) -> dict[str, pd.DataFrame]:
    """Devuelve cada tabla exportable como DataFrame."""
    datos: dict[str, pd.DataFrame] = {}
    with db.conectar() as conexion:
        for tabla in _tablas_existentes(conexion):
            marco = pd.read_sql_query(f"SELECT * FROM {tabla}", conexion)
            datos[tabla] = _con_pesos(marco) if con_pesos else marco
    return datos


# ---------------------------------------------------------------------------
# Volcado SQL
# ---------------------------------------------------------------------------

def _tipo_mysql(serie: pd.Series, columna: str) -> str:
    if columna.endswith("_centavos") or columna.startswith("id_") and \
            pd.api.types.is_integer_dtype(serie):
        return "BIGINT"
    if pd.api.types.is_integer_dtype(serie):
        return "BIGINT"
    if pd.api.types.is_float_dtype(serie):
        return "DECIMAL(14,4)"
    if columna == "fecha":
        return "DATE"
    # Una tabla vacía o una columna toda nula deja el máximo en NaN; se toma
    # un ancho por omisión en vez de reventar la exportación completa.
    sin_nulos = serie.dropna()
    largo = int(sin_nulos.astype(str).str.len().max()) if len(sin_nulos) else 32
    return "VARCHAR(255)" if largo <= 255 else "TEXT"


def _valor_sql(valor) -> str:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "NULL"
    if pd.isna(valor):
        return "NULL"
    if isinstance(valor, (int,)) and not isinstance(valor, bool):
        return str(valor)
    if isinstance(valor, float):
        return repr(valor)
    texto = str(valor).replace("\\", "\\\\").replace("'", "''")
    return f"'{texto}'"


def volcado_sql() -> bytes:
    """
    Genera un volcado en dialecto MySQL: estructura y datos.

    No se copian las llaves foráneas de SQLite tal cual porque los tipos no
    coinciden entre motores; se emiten las tablas con sus tipos equivalentes y
    los datos, que es lo que hace falta para analizar. Si vas a usar la base
    como sistema vivo y no solo para reportes, conviene añadir las
    restricciones a mano después.
    """
    datos = leer_tablas(con_pesos=False)
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")

    lineas = [
        "-- Volcado de Auto Servicio Bautista",
        f"-- Generado el {ahora}",
        "--",
        "-- Para usarlo en Power BI: ejecuta este archivo en un servidor MySQL",
        "-- y luego conecta Power BI a ese servidor. Power BI NO abre .sql",
        "-- directamente. Si solo quieres los datos, usa la exportación a CSV.",
        "--",
        "-- Los importes están en CENTAVOS como entero (columnas _centavos).",
        "-- Para verlos en pesos: columna / 100.",
        "",
        "SET NAMES utf8mb4;",
        "SET FOREIGN_KEY_CHECKS = 0;",
        "",
    ]

    for tabla, marco in datos.items():
        lineas.append(f"-- {'-' * 68}")
        lineas.append(f"-- Tabla: {tabla}  ({len(marco)} filas)")
        lineas.append(f"-- {'-' * 68}")
        lineas.append(f"DROP TABLE IF EXISTS `{tabla}`;")

        columnas = [
            f"  `{c}` {_tipo_mysql(marco[c], c)}" for c in marco.columns
        ]
        lineas.append(f"CREATE TABLE `{tabla}` (")
        lineas.append(",\n".join(columnas))
        lineas.append(") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;")
        lineas.append("")

        if len(marco):
            nombres = ", ".join(f"`{c}`" for c in marco.columns)
            # En lotes de 200: un INSERT gigante puede rebasar el
            # max_allowed_packet del servidor y fallar entero.
            for inicio in range(0, len(marco), 200):
                trozo = marco.iloc[inicio:inicio + 200]
                lineas.append(f"INSERT INTO `{tabla}` ({nombres}) VALUES")
                filas = [
                    "(" + ", ".join(_valor_sql(v) for v in fila) + ")"
                    for fila in trozo.itertuples(index=False, name=None)
                ]
                lineas.append(",\n".join(filas) + ";")
            lineas.append("")

    lineas.append("SET FOREIGN_KEY_CHECKS = 1;")
    lineas.append("")
    return "\n".join(lineas).encode("utf-8")


# ---------------------------------------------------------------------------
# CSV y Excel
# ---------------------------------------------------------------------------

def paquete_csv() -> bytes:
    """Un ZIP con un CSV por tabla, listo para «Obtener datos → Carpeta»."""
    datos = leer_tablas()
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as zip_archivo:
        for tabla, marco in datos.items():
            # utf-8-sig para que Excel no destroce los acentos al abrirlo.
            zip_archivo.writestr(
                f"{tabla}.csv",
                marco.to_csv(index=False, encoding="utf-8-sig"))
        zip_archivo.writestr("LEEME.txt", _instrucciones())
    return memoria.getvalue()


def libro_excel() -> bytes:
    """Un libro con una hoja por tabla."""
    datos = leer_tablas()
    memoria = io.BytesIO()
    with pd.ExcelWriter(memoria, engine="openpyxl") as escritor:
        for tabla, marco in datos.items():
            # Excel no admite nombres de hoja de más de 31 caracteres.
            marco.to_excel(escritor, sheet_name=tabla[:31], index=False)
    return memoria.getvalue()


# ---------------------------------------------------------------------------
# Exportación con la estructura de la hoja de cálculo del taller
#
# El taller llevaba sus notas en Excel antes de esta app, y sigue siendo el
# formato en el que sabe leer sus datos de un vistazo. Los encabezados van
# LITERALES —acentos y mayúsculas incluidos— porque `cargar_datos.py` los
# busca por nombre exacto: así lo que sale de aquí se puede volver a cargar.
# De ahí también las rarezas que se respetan a propósito: «Tipo De concepto»
# con D mayúscula, «TOTAL» en una hoja y «Total» en la otra.
# ---------------------------------------------------------------------------

HOJA_CLIENTES_NOTAS = "TC_TA"
HOJA_SERVICIOS = "TSA"

# La hoja TC_TA lleva DOS tablas lado a lado. Los clientes arrancan en la
# columna A y las notas en la E, así que la D queda vacía: ese hueco es lo
# que `explorar_excel.detectar_bloques` usa para saber dónde termina una
# tabla y empieza la otra. Mover este número rompe la reimportación.
COLUMNA_NOTAS = 4


def _pesos(centavos: int | None) -> float | None:
    """
    Centavos a pesos para escribir en la hoja.

    La hoja del taller guarda pesos, no centavos. Se pasa por `Decimal` para
    que la división sea exacta y solo al final a `float`, que es lo que
    openpyxl sabe escribir como número.
    """
    if centavos is None:
        return None
    return float(db.centavos_a_pesos(centavos))


def _marco_clientes(conexion) -> pd.DataFrame:
    filas = conexion.execute(
        "SELECT id_cliente, nombre, telefono FROM clientes ORDER BY id_cliente"
    ).fetchall()
    return pd.DataFrame(
        [{"ID_Cliente (PK)": f["id_cliente"],
          "Nombre": f["nombre"],
          # Texto, no número: en el archivo original venía como número y por
          # eso existe `cargar_datos.limpiar_telefono`. Sale ya corregido.
          "Telefono": f["telefono"]}
         for f in filas],
        columns=["ID_Cliente (PK)", "Nombre", "Telefono"],
    )


def _marco_notas(conexion) -> pd.DataFrame:
    filas = conexion.execute(
        """
        SELECT n.id_nota, n.id_cliente, n.fecha, v.marca, v.anio, v.modelo,
               v.color, n.total_centavos
          FROM notas n
          LEFT JOIN vehiculos v ON v.id_vehiculo = n.id_vehiculo
         ORDER BY n.id_nota
        """
    ).fetchall()
    marco = pd.DataFrame(
        [{"ID_N (PK)": f["id_nota"],
          "ID_Cliente (FK)": f["id_cliente"],
          # Fecha de verdad, no texto: así Excel la muestra como fecha y
          # `pd.to_datetime` la reconoce al volver a cargarla.
          "Fecha": date.fromisoformat(f["fecha"]),
          "Marca": f["marca"],
          "Año": f["anio"],
          # En la hoja del taller «Tipo» es el MODELO del vehículo.
          "Tipo": f["modelo"],
          "Color": f["color"],
          "TOTAL": _pesos(f["total_centavos"])}
         for f in filas],
        columns=["ID_N (PK)", "ID_Cliente (FK)", "Fecha", "Marca", "Año",
                 "Tipo", "Color", "TOTAL"],
    )
    # Una nota sin vehículo deja el año vacío, y eso basta para que pandas
    # convierta toda la columna a float y escriba «2012.0» en la celda.
    marco["Año"] = marco["Año"].astype("Int64")
    return marco


def _marco_servicios(conexion) -> pd.DataFrame:
    filas = conexion.execute(
        """
        SELECT p.id_nota, p.tipo_concepto, p.categoria, p.accion,
               p.descripcion, p.posicion, p.lado, p.cantidad,
               p.precio_unitario_centavos, p.total_centavos, p.notas
          FROM partidas p
         ORDER BY p.id_nota, p.linea
        """
    ).fetchall()
    # Sin la columna «ID_SA (PK)» del original: era un consecutivo global sin
    # significado, y el cargador tampoco la lee. Cada renglón se relaciona
    # con su nota por «ID_N (FK)».
    return pd.DataFrame(
        [{"ID_N (FK)": f["id_nota"],
          "Tipo De concepto": f["tipo_concepto"],
          "Categoría": f["categoria"],
          "Acción": f["accion"],
          "Descripción": f["descripcion"],
          "Posición": f["posicion"],
          "Lado": f["lado"],
          "Cantidad": f["cantidad"],
          "Precio unitario": _pesos(f["precio_unitario_centavos"]),
          "Total": _pesos(f["total_centavos"]),
          "Notas": f["notas"]}
         for f in filas],
        columns=["ID_N (FK)", "Tipo De concepto", "Categoría", "Acción",
                 "Descripción", "Posición", "Lado", "Cantidad",
                 "Precio unitario", "Total", "Notas"],
    )


def libro_original() -> bytes:
    """
    El libro con la estructura de la hoja de cálculo de siempre del taller.

    Las cotizaciones quedan fuera a propósito: no son trabajo realizado y el
    formato original no las contempla.
    """
    with db.conectar() as conexion:
        clientes = _marco_clientes(conexion)
        notas = _marco_notas(conexion)
        servicios = _marco_servicios(conexion)

    return escribir_libro_original(clientes, notas, servicios)


def escribir_libro_original(clientes: pd.DataFrame, notas: pd.DataFrame,
                            servicios: pd.DataFrame) -> bytes:
    """
    Arma el libro a partir de los tres marcos ya construidos.

    Se separa de `libro_original` para que el generador del archivo de
    ejemplo pueda reutilizar exactamente el mismo escritor, y no haya dos
    sitios donde mantener la geometría de la hoja.
    """
    memoria = io.BytesIO()
    with pd.ExcelWriter(memoria, engine="openpyxl") as escritor:
        clientes.to_excel(escritor, sheet_name=HOJA_CLIENTES_NOTAS,
                          index=False, startcol=0)
        notas.to_excel(escritor, sheet_name=HOJA_CLIENTES_NOTAS,
                       index=False, startcol=COLUMNA_NOTAS)
        servicios.to_excel(escritor, sheet_name=HOJA_SERVICIOS, index=False)
    return memoria.getvalue()


def _instrucciones() -> str:
    return (
        "Auto Servicio Bautista — exportación de datos\n"
        "=============================================\n\n"
        "Un archivo CSV por tabla.\n\n"
        "PARA POWER BI\n"
        "  1. Obtener datos → Carpeta → elige la carpeta donde descomprimiste\n"
        "     esto.\n"
        "  2. Combinar y transformar, o carga cada CSV por separado.\n"
        "  3. Relaciones sugeridas:\n"
        "       notas.id_cliente    → clientes.id_cliente\n"
        "       notas.id_vehiculo   → vehiculos.id_vehiculo\n"
        "       partidas.id_nota    → notas.id_nota\n"
        "       partidas.id_catalogo→ catalogo.id_catalogo\n"
        "       partidas.id_producto→ productos.id_producto\n"
        "       productos.id_cat    → categorias_producto.id_cat\n\n"
        "IMPORTES\n"
        "  Se guardan en centavos como entero (columnas que terminan en\n"
        "  _centavos) para que las sumas sean exactas. Cada una viene\n"
        "  acompañada de su versión en pesos (_pesos) ya dividida.\n"
        "  Usa las de pesos para mostrar y las de centavos para sumar.\n\n"
        "OJO\n"
        "  La tabla de usuarios NO se exporta: contiene hashes de contraseñas.\n"
    )


def nombre_archivo(extension: str, sufijo: str = "") -> str:
    """
    Nombre sugerido para la descarga: `taller-20260912-1430.xlsx`.

    El `sufijo` distingue formatos que comparten extensión — si no, el libro
    por tablas y el que imita la hoja del taller se bajarían con el mismo
    nombre y uno quedaría como «(1)».
    """
    marca = f"-{sufijo}" if sufijo else ""
    return f"taller{marca}-{datetime.now():%Y%m%d-%H%M}.{extension}"


def resumen() -> pd.DataFrame:
    """Cuántas filas tiene cada tabla exportable."""
    datos = leer_tablas(con_pesos=False)
    return pd.DataFrame(
        [{"Tabla": t, "Filas": len(m), "Columnas": len(m.columns)}
         for t, m in datos.items()]
    )
