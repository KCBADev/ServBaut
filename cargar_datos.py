"""
Carga inicial del histórico desde el Excel a SQLite — Servicio Bautista.

El Excel es SOLO la fuente de la carga inicial: la app nunca lo escribe.

Idempotente: correrlo de nuevo no duplica ni pisa nada. Cada inserción usa
`ON CONFLICT DO NOTHING` sobre la llave natural, así que una segunda corrida
solo agrega lo que falte y respeta lo que hayas editado desde la app (precios
del catálogo, teléfonos corregidos, etc.).

Para reimportar desde cero: `--reiniciar` (borra el histórico y lo vuelve a
cargar; conserva los usuarios).

Uso:
    .venv\\Scripts\\python.exe cargar_datos.py
    .venv\\Scripts\\python.exe cargar_datos.py --reiniciar
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter

import pandas as pd

import arranque
import db
from explorar_excel import detectar_bloques, extraer_tabla, localizar_excel

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# Concepto que NO va al catálogo: cruza 8 categorías con precios de 150 a
# 8,490, así que se captura libre y con precio manual en cada nota.
CONCEPTO_LIBRE = "Mano de obra"

# Tipo que se imputa a la única partida del histórico sin 'Tipo De concepto'.
# Verificado: las otras 14 filas de 'Amortiguador' son todas Producto.
TIPO_POR_OMISION = "Producto"

# Las notas del histórico ya se hicieron y se entregaron.
ESTADO_HISTORICO = "Entregado"

# El Excel del taller trae dos marcas escritas como se teclearon en su día.
# Se estandarizan al nombre oficial al cargar, porque `marcas.nombre` es la
# llave a la que apuntan los vehículos: si una recarga volviera a meter
# «Mercedes» junto al «Mercedes-Benz» que ya está en la base, la misma marca
# quedaría partida en dos y el historial del coche con ella.
EQUIVALENCIAS_MARCA = {
    "Mercedes": "Mercedes-Benz",
    "KIA": "Kia",
}


def log(mensaje: str = "") -> None:
    print(mensaje)


def limpiar_texto(valor) -> str | None:
    """Normaliza un valor de texto: quita espacios sobrantes, vacío -> None."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if pd.isna(valor):
        return None
    texto = str(valor).strip()
    return texto or None


def normalizar_marca(valor) -> str | None:
    """Limpia la marca y la deja con su nombre oficial."""
    marca = limpiar_texto(valor)
    return EQUIVALENCIAS_MARCA.get(marca, marca)


def limpiar_telefono(valor) -> str | None:
    """
    Convierte el teléfono a texto de dígitos.

    pandas lo lee como float (5550100001.0); guardarlo así perdería el formato
    y cualquier cero a la izquierda.
    """
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, float):
        return str(int(valor))
    return str(valor).strip() or None


# ---------------------------------------------------------------------------
# Lectura y normalización del Excel
# ---------------------------------------------------------------------------

def leer_excel() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Lee las tres tablas reales del libro, ya normalizadas."""
    ruta = localizar_excel()
    log(f"Origen: {ruta.name}")

    # La hoja TC_TA contiene DOS tablas lado a lado separadas por una columna
    # vacía. Se detectan los bloques en vez de asumir las columnas.
    crudo_tc = pd.read_excel(ruta, sheet_name="TC_TA", header=None)
    bloques = detectar_bloques(crudo_tc)
    if len(bloques) != 2:
        raise SystemExit(
            f"Se esperaban 2 tablas en la hoja TC_TA y se detectaron {len(bloques)}. "
            "Revisa el archivo antes de cargar."
        )
    clientes = extraer_tabla(crudo_tc, *bloques[0])
    notas = extraer_tabla(crudo_tc, *bloques[1])

    crudo_tsa = pd.read_excel(ruta, sheet_name="TSA", header=None)
    partidas = extraer_tabla(crudo_tsa, *detectar_bloques(crudo_tsa)[0])

    return clientes, notas, partidas


def normalizar(clientes: pd.DataFrame, notas: pd.DataFrame,
               partidas: pd.DataFrame) -> tuple[list, list, list]:
    """
    Aplica todas las transformaciones acordadas y devuelve listas de tuplas
    listas para insertar. Reporta cada corrección que hace.
    """
    log("\n--- Normalización ---")

    # ----- Clientes -----
    filas_clientes = []
    espacios = 0
    for _, fila in clientes.iterrows():
        nombre_crudo = str(fila["Nombre"])
        nombre = limpiar_texto(nombre_crudo)
        if nombre != nombre_crudo:
            espacios += 1
        filas_clientes.append((
            int(fila["ID_Cliente (PK)"]),
            nombre,
            limpiar_telefono(fila["Telefono"]),
        ))
    log(f"  Clientes: {len(filas_clientes)} | nombres con espacios corregidos: {espacios}")

    # ----- Notas -----
    filas_notas = []
    modelos_no_texto = 0
    for _, fila in notas.iterrows():
        modelo = fila["Tipo"]  # en el Excel se llama 'Tipo' pero es el MODELO
        if not isinstance(modelo, str) and pd.notna(modelo):
            modelos_no_texto += 1
        filas_notas.append((
            limpiar_texto(fila["ID_N (PK)"]),
            int(fila["ID_Cliente (FK)"]),
            pd.to_datetime(fila["Fecha"]).strftime("%Y-%m-%d"),
            normalizar_marca(fila["Marca"]),
            int(fila["Año"]) if pd.notna(fila["Año"]) else None,
            limpiar_texto(modelo),
            limpiar_texto(fila["Color"]),
        ))
    log(f"  Notas: {len(filas_notas)} | modelos numéricos pasados a texto: "
        f"{modelos_no_texto}")

    # ----- Partidas -----
    p = partidas.copy()

    # Ojo: no se guardan las columnas ya limpias en el DataFrame. Al asignar una
    # serie con None a una columna de tipo object, pandas los vuelve a convertir
    # en NaN (float) y esos NaN se colarían en las tuplas de inserción. La
    # limpieza se aplica al construir cada fila, sobre la columna original.
    imputados = int(p["Tipo De concepto"].isna().sum())
    p["tipo_concepto"] = p["Tipo De concepto"].map(limpiar_texto).fillna(TIPO_POR_OMISION)
    if imputados:
        log(f"  Partidas sin 'Tipo De concepto': {imputados} -> imputadas como "
            f"'{TIPO_POR_OMISION}'")

    # El consecutivo dentro de cada nota se deriva del orden original de la
    # hoja, que ya agrupa las partidas por nota (verificado en el Paso 0).
    p["linea"] = p.groupby("ID_N (FK)").cumcount() + 1

    filas_partidas = []
    correcciones = []
    for _, fila in p.iterrows():
        descripcion = limpiar_texto(fila["Descripción"])
        cantidad = int(fila["Cantidad"])
        precio_cent = db.pesos_a_centavos(fila["Precio unitario"])
        total_cent = db.pesos_a_centavos(fila["Total"])

        # El TOTAL de la nota se calculó con el 'Total' de la partida, así que
        # ese es el dato bueno: si no cuadra con cantidad x precio, se respeta
        # el total y se recalcula el precio unitario.
        if total_cent != cantidad * precio_cent:
            precio_corregido = total_cent // cantidad
            # Si el total no es divisible entre la cantidad, corregir el precio
            # alteraría el total y rompería la suma global de 381,146.50. En ese
            # caso hay que revisar la fila a mano, no adivinar.
            if precio_corregido * cantidad != total_cent:
                raise SystemExit(
                    f"La partida {fila['ID_N (FK)']} línea {fila['linea']} "
                    f"({descripcion}) tiene un total de "
                    f"{db.formato_pesos(total_cent)} que no es divisible entre "
                    f"una cantidad de {cantidad}. Corrígela en el Excel antes de cargar."
                )
            correcciones.append(
                f"{fila['ID_N (FK)']} línea {fila['linea']} "
                f"({descripcion}): precio "
                f"{db.formato_pesos(precio_cent)} -> {db.formato_pesos(precio_corregido)} "
                f"para respetar el total de {db.formato_pesos(total_cent)}"
            )
            precio_cent = precio_corregido

        filas_partidas.append((
            limpiar_texto(fila["ID_N (FK)"]),
            int(fila["linea"]),
            fila["tipo_concepto"],
            limpiar_texto(fila["Categoría"]),
            limpiar_texto(fila["Acción"]),
            descripcion,
            limpiar_texto(fila["Posición"]),
            limpiar_texto(fila["Lado"]),
            cantidad,
            precio_cent,
            total_cent,
        ))

    log(f"  Partidas: {len(filas_partidas)}")
    if correcciones:
        log(f"  Correcciones de precio aplicadas: {len(correcciones)}")
        for detalle in correcciones:
            log(f"    * {detalle}")

    return filas_clientes, filas_notas, filas_partidas


def derivar_catalogo(filas_partidas: list, filas_notas: list) -> list:
    """
    Construye el catálogo a partir del histórico.

    Llave (descripcion, tipo_concepto): con ella ningún concepto cruza
    categorías. El precio es el más reciente observado, según la fecha de la
    nota en la que apareció. La mano de obra se excluye a propósito.
    """
    fecha_de_nota = {n[0]: n[2] for n in filas_notas}

    # Se recorre en orden de fecha para que el último visto sea el más reciente.
    ordenadas = sorted(filas_partidas, key=lambda f: fecha_de_nota[f[0]])

    catalogo: dict[tuple[str, str], list] = {}
    for fila in ordenadas:
        _, _, tipo, categoria, _, descripcion, _, _, _, precio_cent, _ = fila
        if descripcion == CONCEPTO_LIBRE:
            continue
        catalogo[(descripcion, tipo)] = [descripcion, tipo, categoria, precio_cent]

    log(f"  Catálogo derivado: {len(catalogo)} conceptos "
        f"(excluye '{CONCEPTO_LIBRE}')")
    return [tuple(v) for v in catalogo.values()]


# ---------------------------------------------------------------------------
# Escritura en la base
# ---------------------------------------------------------------------------

def reiniciar_historico(conexion: sqlite3.Connection) -> None:
    """Borra el histórico para reimportarlo desde cero. Conserva los usuarios."""
    log("\n--- Reiniciando histórico (se conservan los usuarios) ---")
    # El orden importa por las llaves foráneas.
    for tabla in ("partidas", "notas", "vehiculos", "catalogo", "clientes",
                  "marcas", "acciones", "categorias"):
        borradas = conexion.execute(f"DELETE FROM {tabla}").rowcount
        log(f"  {tabla}: {borradas} filas borradas")
    # Reinicia los contadores AUTOINCREMENT de las tablas vaciadas.
    conexion.execute(
        "DELETE FROM sqlite_sequence WHERE name IN "
        "('partidas', 'catalogo', 'clientes', 'vehiculos')"
    )


def cargar(conexion: sqlite3.Connection, filas_clientes: list, filas_notas: list,
           filas_partidas: list, filas_catalogo: list) -> dict:
    """Inserta todo dentro de una sola transacción. Devuelve el conteo insertado."""
    insertados = {}

    # ----- Tablas de referencia (derivadas de los propios datos) -----
    categorias = sorted({f[3] for f in filas_partidas if f[3]})
    acciones = sorted({f[4] for f in filas_partidas if f[4]})
    marcas = sorted({n[3] for n in filas_notas if n[3]})

    for tabla, valores in (("categorias", categorias), ("acciones", acciones),
                           ("marcas", marcas)):
        cursor = conexion.executemany(
            f"INSERT INTO {tabla} (nombre) VALUES (?) ON CONFLICT DO NOTHING",
            [(v,) for v in valores],
        )
        insertados[tabla] = cursor.rowcount
        log(f"  {tabla}: {cursor.rowcount} de {len(valores)} insertadas")

    # ----- Clientes -----
    cursor = conexion.executemany(
        """
        INSERT INTO clientes (id_cliente, nombre, telefono)
        VALUES (?, ?, ?)
        ON CONFLICT (id_cliente) DO NOTHING
        """,
        filas_clientes,
    )
    insertados["clientes"] = cursor.rowcount
    log(f"  clientes: {cursor.rowcount} de {len(filas_clientes)} insertados")

    # ----- Vehículos -----
    # El Excel guarda el vehículo dentro de cada nota, repetido. Se agrupa por
    # cliente + marca + modelo, SIN el año: si dos notas del mismo carro no
    # coinciden en el año es un error de captura, y meterlo en la llave
    # partiría el carro en dos fichas en vez de destapar el problema.
    agrupados: dict[tuple, list] = {}
    for _, id_cliente, _, marca, anio, modelo, color in filas_notas:
        agrupados.setdefault(
            (id_cliente, marca, (modelo or "").strip()), []
        ).append((anio, color))

    filas_vehiculos = []
    for (id_cliente, marca, modelo), vistas in agrupados.items():
        anios = [a for a, _ in vistas if a is not None]
        colores = [c for _, c in vistas if c]
        filas_vehiculos.append((
            id_cliente, marca, modelo or None,
            Counter(anios).most_common(1)[0][0] if anios else None,
            Counter(colores).most_common(1)[0][0] if colores else None,
        ))
        if len(set(anios)) > 1:
            log(f"    [!] {marca} {modelo or '?'} del cliente #{id_cliente}: "
                f"años distintos entre notas ({sorted(set(anios))}); "
                f"se toma {filas_vehiculos[-1][3]}")

    cursor = conexion.executemany(
        """
        INSERT INTO vehiculos (id_cliente, marca, modelo, anio, color)
        VALUES (?, ?, ?, ?, ?)
        """,
        filas_vehiculos,
    )
    insertados["vehiculos"] = cursor.rowcount
    log(f"  vehiculos: {cursor.rowcount} derivados de las {len(filas_notas)} notas")

    # ----- Notas (total_centavos lo calcularán los triggers) -----
    mapa_vehiculos = {
        (f["id_cliente"], f["marca"], (f["modelo"] or "")): f["id_vehiculo"]
        for f in conexion.execute(
            "SELECT id_vehiculo, id_cliente, marca, modelo FROM vehiculos")
    }
    notas_con_vehiculo = [
        (id_nota, id_cliente,
         mapa_vehiculos.get((id_cliente, marca, (modelo or "").strip())),
         fecha, ESTADO_HISTORICO, 0)
        for id_nota, id_cliente, fecha, marca, anio, modelo, color in filas_notas
    ]
    cursor = conexion.executemany(
        """
        INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha, estado,
                           pagado_centavos)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (id_nota) DO NOTHING
        """,
        notas_con_vehiculo,
    )
    insertados["notas"] = cursor.rowcount
    log(f"  notas: {cursor.rowcount} de {len(filas_notas)} insertadas")

    # ----- Catálogo -----
    # DO NOTHING y no DO UPDATE: el catálogo es editable desde la app y una
    # segunda corrida no debe pisar un precio que hayas cambiado a mano.
    cursor = conexion.executemany(
        """
        INSERT INTO catalogo (descripcion, tipo_concepto, categoria,
                              precio_actual_centavos)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (descripcion, tipo_concepto) DO NOTHING
        """,
        filas_catalogo,
    )
    insertados["catalogo"] = cursor.rowcount
    log(f"  catalogo: {cursor.rowcount} de {len(filas_catalogo)} insertados")

    # ----- Partidas -----
    # Se enlazan al catálogo por su llave natural; NULL para la mano de obra.
    referencias = {
        (f["descripcion"], f["tipo_concepto"]): f["id_catalogo"]
        for f in conexion.execute(
            "SELECT id_catalogo, descripcion, tipo_concepto FROM catalogo"
        )
    }
    con_referencia = [
        (nota, linea, referencias.get((descripcion, tipo)), tipo, categoria,
         accion, descripcion, posicion, lado, cantidad, precio, total)
        for (nota, linea, tipo, categoria, accion, descripcion, posicion, lado,
             cantidad, precio, total) in filas_partidas
    ]
    cursor = conexion.executemany(
        """
        INSERT INTO partidas (id_nota, linea, id_catalogo, tipo_concepto,
                              categoria, accion, descripcion, posicion, lado,
                              cantidad, precio_unitario_centavos, total_centavos)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (id_nota, linea) DO NOTHING
        """,
        con_referencia,
    )
    insertados["partidas"] = cursor.rowcount
    libres = sum(1 for f in con_referencia if f[2] is None)
    log(f"  partidas: {cursor.rowcount} de {len(con_referencia)} insertadas "
        f"({libres} como concepto libre, sin catálogo)")

    return insertados


# `asegurar_admin` vivía aquí; se movió a `arranque.py` para que el arranque
# autónomo del servidor (que también necesita crear el primer administrador,
# sin nadie mirando la terminal) use la misma definición y no dos que se
# puedan ir desalineando. Se reexporta para no romper a quien la importaba de
# `cargar_datos`.
asegurar_admin = arranque.asegurar_admin


# ---------------------------------------------------------------------------
# Validación posterior a la carga
# ---------------------------------------------------------------------------

TOTAL_ESPERADO_CENTAVOS = 38_114_650  # 381,146.50 según la especificación


def validar(conexion: sqlite3.Connection) -> bool:
    """Comprueba las reglas obligatorias. Devuelve True si todo cuadra."""
    log("\n--- Validación ---")
    todo_bien = True

    conteos = {
        tabla: conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
        for tabla in ("clientes", "vehiculos", "notas", "partidas", "catalogo",
                      "categorias", "acciones", "marcas", "usuarios")
    }
    log("  Filas por tabla:")
    for tabla, n in conteos.items():
        log(f"    {tabla:<12} {n:>5}")

    # Integridad referencial declarada (debe salir vacío).
    violaciones = conexion.execute("PRAGMA foreign_key_check").fetchall()
    if violaciones:
        todo_bien = False
        log(f"  [!!] {len(violaciones)} violaciones de llave foránea")
    else:
        log("  [OK] Sin violaciones de llave foránea")

    # Suma global.
    total_partidas = conexion.execute(
        "SELECT COALESCE(SUM(total_centavos), 0) AS t FROM partidas"
    ).fetchone()["t"]
    total_notas = conexion.execute(
        "SELECT COALESCE(SUM(total_centavos), 0) AS t FROM notas"
    ).fetchone()["t"]

    log(f"  Suma de partidas : {db.formato_pesos(total_partidas)}")
    log(f"  Suma de notas    : {db.formato_pesos(total_notas)}")
    log(f"  Esperado (spec)  : {db.formato_pesos(TOTAL_ESPERADO_CENTAVOS)}")

    if total_partidas == total_notas:
        log("  [OK] Las sumas de notas y partidas coinciden")
    else:
        todo_bien = False
        log(f"  [!!] NO coinciden: difieren en "
            f"{db.formato_pesos(abs(total_notas - total_partidas))}")

    if total_partidas == TOTAL_ESPERADO_CENTAVOS:
        log("  [OK] Coincide con el total esperado en la especificación")
    else:
        todo_bien = False
        log(f"  [!!] NO coincide con la especificación: difiere en "
            f"{db.formato_pesos(abs(total_partidas - TOTAL_ESPERADO_CENTAVOS))}")

    # Cada nota contra la suma de sus partidas.
    descuadradas = conexion.execute(
        """
        SELECT n.id_nota, n.total_centavos AS total_nota,
               COALESCE(SUM(p.total_centavos), 0) AS suma_partidas
          FROM notas n
          LEFT JOIN partidas p ON p.id_nota = n.id_nota
         GROUP BY n.id_nota, n.total_centavos
        HAVING n.total_centavos <> COALESCE(SUM(p.total_centavos), 0)
        """
    ).fetchall()
    if descuadradas:
        todo_bien = False
        log(f"  [!!] {len(descuadradas)} notas no cuadran con sus partidas:")
        for fila in descuadradas[:10]:
            log(f"       {fila['id_nota']}: nota="
                f"{db.formato_pesos(fila['total_nota'])} vs partidas="
                f"{db.formato_pesos(fila['suma_partidas'])}")
    else:
        log(f"  [OK] Las {conteos['notas']} notas cuadran con sus partidas")

    # Notas sin partidas: no deberían existir.
    huerfanas = conexion.execute(
        "SELECT COUNT(*) AS n FROM notas n "
        "WHERE NOT EXISTS (SELECT 1 FROM partidas p WHERE p.id_nota = n.id_nota)"
    ).fetchone()["n"]
    if huerfanas:
        todo_bien = False
        log(f"  [!!] {huerfanas} notas sin ninguna partida")
    else:
        log("  [OK] Todas las notas tienen al menos una partida")

    return todo_bien


# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Carga el histórico del Excel a SQLite.")
    parser.add_argument(
        "--reiniciar", action="store_true",
        help="Borra el histórico y lo reimporta desde cero (conserva usuarios).",
    )
    args = parser.parse_args()

    log("=" * 74)
    log("CARGA DE DATOS — SERVICIO BAUTISTA")
    log("=" * 74)

    log("\n--- Esquema ---")
    db.inicializar_esquema()
    log(f"  Base de datos: {db.RUTA_DB.name} (esquema aplicado)")

    clientes, notas, partidas = leer_excel()
    filas_clientes, filas_notas, filas_partidas = normalizar(clientes, notas, partidas)
    filas_catalogo = derivar_catalogo(filas_partidas, filas_notas)

    with db.transaccion() as conexion:
        if args.reiniciar:
            reiniciar_historico(conexion)

        log("\n--- Inserción ---")
        cargar(conexion, filas_clientes, filas_notas, filas_partidas, filas_catalogo)

        credenciales = asegurar_admin(conexion)
        exito = validar(conexion)

    # Aparte de la transacción anterior: las marcas del catálogo general no
    # salen del Excel, se suman a las que el taller ya haya atendido para que
    # al capturar una nota la lista no dependa de si ese coche ya vino antes.
    nuevas = db.sembrar_marcas()
    log(f"\n--- Marcas ---\n  {nuevas} marcas del catálogo general agregadas "
        f"({len(db.listar_marcas())} en total)")

    log()
    log("=" * 74)
    if credenciales:
        usuario, password = credenciales
        log("USUARIO ADMINISTRADOR CREADO — anota estas credenciales:")
        log("")
        log(f"    usuario    : {usuario}")
        log(f"    contraseña : {password}")
        log("")
        log("Esta contraseña no se vuelve a mostrar. Cámbiala desde la app.")
        log("=" * 74)

    if exito:
        log("CARGA COMPLETADA — todas las validaciones pasaron.")
    else:
        log("CARGA COMPLETADA CON ERRORES — revisa las marcas [!!] de arriba.")
    log("=" * 74)

    sys.exit(0 if exito else 1)


if __name__ == "__main__":
    main()
