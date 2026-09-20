"""
Capa de acceso a datos — Servicio Bautista.

Todo el SQL del proyecto vive aquí o en los módulos que este importe; la
interfaz de Streamlit nunca ejecuta SQL directamente.

Reglas que este módulo garantiza:
  * `PRAGMA foreign_keys = ON` en TODAS las conexiones (SQLite lo trae apagado
    por omisión y no es persistente: hay que activarlo cada vez).
  * SQL siempre parametrizado con `?`, nunca concatenación de strings.
  * El dinero se maneja en CENTAVOS como entero. Las funciones de conversión
    son el único punto donde se cruza la frontera entre pesos y centavos.
"""

from __future__ import annotations

import sqlite3
import unicodedata
from contextlib import contextmanager
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Iterator

# Concepto que no vive en el catálogo: la mano de obra cruza 8 categorías con
# precios muy distintos, así que se captura libre y con precio manual.
CONCEPTO_LIBRE = "Mano de obra"

# Rutas relativas a la raíz del proyecto para que todo siga funcionando si la
# carpeta se mueve o se sube a un repositorio.
RAIZ = Path(__file__).resolve().parent

# La base vive fuera del proyecto, en D:, porque el disco C: se quedó sin
# espacio libre y provocó errores de escritura. Si el proyecto corre en otra
# máquina o D: no existe ahí, hay que ajustar esta ruta a mano.
RUTA_DB = Path(r"D:\TallerBautista\taller.db")
RUTA_ESQUEMA = RAIZ / "esquema.sql"


# ---------------------------------------------------------------------------
# Conversión de dinero
# ---------------------------------------------------------------------------
# Los importes se guardan como enteros de centavos. Motivo: la especificación
# exige que la suma del histórico dé exactamente 381,146.50, y con REAL las
# sumas de punto flotante pueden desviarse. Con enteros la aritmética es exacta.

def pesos_a_centavos(pesos: float | str | Decimal | None) -> int | None:
    """Convierte un importe en pesos a centavos como entero."""
    if pesos is None:
        return None
    # Se pasa por str para no arrastrar el error binario del float
    # (Decimal(2100.1) != Decimal("2100.1")).
    valor = Decimal(str(pesos)) * 100
    return int(valor.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def centavos_a_pesos(centavos: int | None) -> Decimal | None:
    """Convierte centavos a pesos como Decimal (no float, para no perder exactitud)."""
    if centavos is None:
        return None
    return (Decimal(centavos) / 100).quantize(Decimal("0.01"))


def formato_fecha(iso: str | None) -> str:
    """
    De `2026-01-21` a `21/01/2026`, que es como se lee la fecha en México.

    La base guarda ISO y así se queda: ordena bien como texto y es lo que
    esperan `date.fromisoformat` y los `CHECK` del esquema. La conversión es
    solo para mostrar, igual que con los centavos.
    """
    if not iso:
        return "—"
    try:
        return date.fromisoformat(iso[:10]).strftime("%d/%m/%Y")
    except ValueError:
        # Si llega algo que no es una fecha ISO, se muestra tal cual en vez
        # de tronar: un dato raro no debe tumbar la pantalla entera.
        return iso


def formato_pesos(centavos: int | None) -> str:
    """Formatea centavos para mostrar en pantalla: 38114650 -> '$381,146.50'."""
    if centavos is None:
        return "—"
    return f"${centavos_a_pesos(centavos):,.2f}"


# ---------------------------------------------------------------------------
# Conexión
# ---------------------------------------------------------------------------

def _preparar(conexion: sqlite3.Connection) -> None:
    """Aplica los PRAGMA que no son persistentes y deben repetirse por conexión."""
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON")
    # WAL permite lecturas concurrentes mientras alguien escribe: necesario
    # porque Streamlit puede atender varias sesiones a la vez.
    conexion.execute("PRAGMA journal_mode = WAL")
    conexion.execute("PRAGMA synchronous = NORMAL")


@contextmanager
def conectar(ruta: Path | None = None) -> Iterator[sqlite3.Connection]:
    """
    Abre una conexión con los PRAGMA aplicados y la cierra al terminar.

    Solo lectura o escrituras sueltas con autocommit. Para varias escrituras
    que deban ser atómicas, usa `transaccion()`.
    """
    ruta = ruta or RUTA_DB
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta, timeout=30.0)
    try:
        _preparar(conexion)
        yield conexion
    finally:
        conexion.close()


@contextmanager
def transaccion(ruta: Path | None = None) -> Iterator[sqlite3.Connection]:
    """
    Conexión dentro de una transacción: confirma al salir sin error, revierte
    si algo falla. Se usa para operaciones que deben ser todo o nada, como
    guardar una nota junto con todas sus partidas.
    """
    ruta = ruta or RUTA_DB
    ruta.parent.mkdir(parents=True, exist_ok=True)
    conexion = sqlite3.connect(ruta, timeout=30.0)
    try:
        _preparar(conexion)
        with conexion:  # confirma o revierte automáticamente
            yield conexion
    finally:
        conexion.close()


def inicializar_esquema(ruta: Path | None = None) -> None:
    """Crea las tablas, triggers e índices si no existen (idempotente)."""
    sql = RUTA_ESQUEMA.read_text(encoding="utf-8")
    with conectar(ruta) as conexion:
        conexion.executescript(sql)
        conexion.commit()


# ---------------------------------------------------------------------------
# Generación de identificadores
# ---------------------------------------------------------------------------

def siguiente_id_nota(conexion: sqlite3.Connection) -> str:
    """
    Devuelve el siguiente folio de nota con el formato original ('N-063').

    Debe llamarse dentro de la misma transacción que inserta la nota, para que
    dos capturas simultáneas no reciban el mismo folio.
    """
    fila = conexion.execute(
        "SELECT MAX(CAST(SUBSTR(id_nota, 3) AS INTEGER)) AS maximo FROM notas"
    ).fetchone()
    siguiente = (fila["maximo"] or 0) + 1
    return f"N-{siguiente:03d}"


def siguiente_linea(conexion: sqlite3.Connection, id_nota: str) -> int:
    """Devuelve el siguiente consecutivo de partida dentro de una nota."""
    fila = conexion.execute(
        "SELECT COALESCE(MAX(linea), 0) AS maximo FROM partidas WHERE id_nota = ?",
        (id_nota,),
    ).fetchone()
    return int(fila["maximo"]) + 1


# ---------------------------------------------------------------------------
# Verificación de integridad
# ---------------------------------------------------------------------------

def verificar_cuadre(ruta: Path | None = None) -> dict:
    """
    Comprueba las igualdades que la especificación marca como obligatorias:
    el total de cada nota contra la suma de sus partidas, y el total global.

    Devuelve un diccionario con los resultados en centavos.
    """
    with conectar(ruta) as conexion:
        total_notas = conexion.execute(
            "SELECT COALESCE(SUM(total_centavos), 0) AS t FROM notas"
        ).fetchone()["t"]
        total_partidas = conexion.execute(
            "SELECT COALESCE(SUM(total_centavos), 0) AS t FROM partidas"
        ).fetchone()["t"]
        descuadradas = conexion.execute(
            """
            SELECT n.id_nota,
                   n.total_centavos AS total_nota,
                   COALESCE(SUM(p.total_centavos), 0) AS suma_partidas
              FROM notas n
              LEFT JOIN partidas p ON p.id_nota = n.id_nota
             GROUP BY n.id_nota, n.total_centavos
            HAVING n.total_centavos <> COALESCE(SUM(p.total_centavos), 0)
            """
        ).fetchall()

    return {
        "total_notas_centavos": total_notas,
        "total_partidas_centavos": total_partidas,
        "coinciden": total_notas == total_partidas,
        "notas_descuadradas": [dict(f) for f in descuadradas],
    }


# ---------------------------------------------------------------------------
# Búsqueda de texto
# ---------------------------------------------------------------------------

def plegar(texto: str | None) -> str:
    """
    Normaliza texto para buscar: minúsculas y sin acentos.

    Se hace en Python y no en SQL porque LOWER() de SQLite solo pliega ASCII:
    'Martín' no coincidiría con 'martin'. A esta escala (decenas de filas)
    filtrar en memoria es instantáneo y da una búsqueda mucho mejor.
    """
    if not texto:
        return ""
    sin_acentos = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in sin_acentos if not unicodedata.combining(c)).lower().strip()


def _coincide(busqueda: str, *campos) -> bool:
    """True si el texto buscado aparece en alguno de los campos."""
    objetivo = plegar(busqueda)
    if not objetivo:
        return True
    return any(objetivo in plegar(campo) for campo in campos)


# ---------------------------------------------------------------------------
# Validación de entrada
# ---------------------------------------------------------------------------

def normalizar_telefono(texto: str | None) -> str | None:
    """
    Deja el teléfono en 10 dígitos, o None si viene vacío.

    Acepta lo que la gente teclea de verdad ('33 2240 7362', '(33) 2240-7362')
    y se queda solo con los dígitos.

    Lanza ValueError si no quedan exactamente 10, que es lo que el CHECK de la
    base exige; hacerlo aquí permite dar un mensaje claro en pantalla en vez de
    dejar que estalle una IntegrityError.
    """
    if texto is None:
        return None
    digitos = "".join(c for c in str(texto) if c.isdigit())
    if not digitos:
        return None
    if len(digitos) != 10:
        raise ValueError(
            f"El teléfono debe tener 10 dígitos; se recibieron {len(digitos)}."
        )
    return digitos


# ---------------------------------------------------------------------------
# Tablas de referencia
# ---------------------------------------------------------------------------

def listar_categorias() -> list[str]:
    with conectar() as c:
        return [f["nombre"] for f in c.execute(
            "SELECT nombre FROM categorias ORDER BY nombre")]


def listar_acciones() -> list[str]:
    with conectar() as c:
        return [f["nombre"] for f in c.execute(
            "SELECT nombre FROM acciones ORDER BY nombre")]


def listar_marcas() -> list[str]:
    with conectar() as c:
        return [f["nombre"] for f in c.execute(
            "SELECT nombre FROM marcas ORDER BY nombre")]


def agregar_marca(nombre: str) -> None:
    """Registra una marca nueva para que pueda usarse en una nota."""
    with conectar() as c:
        c.execute("INSERT INTO marcas (nombre) VALUES (?) ON CONFLICT DO NOTHING",
                  (nombre.strip(),))
        c.commit()


# Marcas de vehículo que se venden o circulan en México, para que la lista no
# dependa de que el taller ya haya atendido esa marca antes.
#
# Todas van con su nombre oficial, incluidas «Mercedes-Benz» y «Kia», que el
# taller tenía escritas como «Mercedes» y «KIA» desde la hoja de Excel. Como
# `marcas.nombre` es la llave primaria a la que apuntan los vehículos, no
# bastó con cambiar esta lista: hubo que renombrar también la llave en la
# base y repuntar los vehículos, o habrían quedado dos entradas para la misma
# marca y el historial partido en dos. `EQUIVALENCIAS_MARCA` en
# `cargar_datos.py` mantiene la corrección si algún día se recarga el Excel.
MARCAS_CONOCIDAS = [
    "Acura", "Alfa Romeo", "Audi", "BAIC", "Bentley", "BMW", "Buick", "BYD",
    "Cadillac", "Changan", "Chevrolet", "Chirey", "Chrysler", "Citroën",
    "Cupra", "Dodge", "FAW", "Fiat", "Ford", "Freightliner", "GAC", "Geely",
    "GMC", "Great Wall", "Hino", "Honda", "Hyundai", "Infiniti",
    "International", "Isuzu", "JAC", "Jaguar", "Jeep", "Jetour", "Kia",
    "Land Rover", "Lexus", "Lincoln", "Mahindra", "Maserati", "Mazda",
    "Mercedes-Benz", "MG", "MINI", "Mitsubishi", "Nissan", "Omoda", "Opel",
    "Peugeot", "Polestar", "Porsche", "RAM", "Renault", "SEAT", "Smart",
    "SsangYong", "Subaru", "Suzuki", "Tesla", "Toyota", "Volkswagen",
    "Volvo", "Zacua",
]


def sembrar_marcas() -> int:
    """
    Agrega las marcas conocidas que falten. Devuelve cuántas se agregaron.

    Es idempotente: las que ya están se quedan como están, con su grafía
    original, porque son la llave a la que apuntan los vehículos ya
    registrados.
    """
    with transaccion() as c:
        antes = c.execute("SELECT COUNT(*) FROM marcas").fetchone()[0]
        c.executemany(
            "INSERT INTO marcas (nombre) VALUES (?) ON CONFLICT DO NOTHING",
            [(m,) for m in MARCAS_CONOCIDAS],
        )
        despues = c.execute("SELECT COUNT(*) FROM marcas").fetchone()[0]
    return despues - antes


# ---------------------------------------------------------------------------
# Clientes
# ---------------------------------------------------------------------------

def listar_clientes(busqueda: str = "") -> list[dict]:
    """
    Devuelve los clientes con su historial resumido.

    `total_facturado_centavos` sale de sus notas; los clientes sin notas
    aparecen con 0 (hay 2 así en el histórico).
    """
    with conectar() as c:
        filas = c.execute(
            """
            SELECT cl.id_cliente, cl.nombre, cl.telefono, cl.creado_en,
                   COUNT(n.id_nota) AS num_notas,
                   COALESCE(SUM(n.total_centavos), 0) AS total_facturado_centavos,
                   MAX(n.fecha) AS ultima_visita
              FROM clientes cl
              LEFT JOIN notas n ON n.id_cliente = cl.id_cliente
             GROUP BY cl.id_cliente, cl.nombre, cl.telefono, cl.creado_en
             ORDER BY cl.id_cliente
            """
        ).fetchall()

    clientes = [dict(f) for f in filas]
    if busqueda:
        clientes = [
            c for c in clientes
            if _coincide(busqueda, c["nombre"], c["telefono"], str(c["id_cliente"]))
        ]
    return clientes


def obtener_cliente(id_cliente: int) -> dict | None:
    with conectar() as c:
        fila = c.execute(
            "SELECT * FROM clientes WHERE id_cliente = ?", (id_cliente,)
        ).fetchone()
    return dict(fila) if fila else None


def buscar_nombres_parecidos(nombre: str, excluir_id: int | None = None) -> list[dict]:
    """
    Busca clientes con un nombre equivalente (sin acentos ni mayúsculas).

    Sirve para advertir de un posible duplicado al dar de alta, sin impedirlo:
    dos personas pueden llamarse igual.
    """
    objetivo = plegar(nombre)
    if not objetivo:
        return []
    with conectar() as c:
        filas = c.execute("SELECT id_cliente, nombre, telefono FROM clientes").fetchall()
    return [
        dict(f) for f in filas
        if plegar(f["nombre"]) == objetivo and f["id_cliente"] != excluir_id
    ]


def buscar_cliente_igual(nombre: str, telefono: str | None,
                         excluir_id: int | None = None) -> dict | None:
    """
    Busca el cliente que ya ES esta persona, no uno que se le parezca.

    La diferencia con `buscar_nombres_parecidos` es el teléfono: dos personas
    pueden llamarse igual —por eso aquel solo advierte—, pero el mismo nombre
    CON el mismo teléfono es la misma persona, y darla de alta otra vez parte
    su historial en dos. Eso es lo que pasó de verdad con un cliente que quedó
    registrado dos veces con dos minutos de diferencia.

    Dos clientes sin teléfono y con el mismo nombre también cuentan como el
    mismo: sin teléfono no hay con qué distinguirlos, y la salida es capturar
    el teléfono de uno de los dos.
    """
    objetivo = plegar(nombre)
    if not objetivo:
        return None
    buscado = normalizar_telefono(telefono)
    for fila in buscar_nombres_parecidos(nombre, excluir_id=excluir_id):
        if fila["telefono"] == buscado:
            return fila
    return None


def crear_cliente(nombre: str, telefono: str | None) -> int:
    """
    Da de alta un cliente. Devuelve su id (el consecutivo de llegada).

    Rechaza el duplicado exacto (mismo nombre y mismo teléfono). La pantalla
    lo comprueba antes para poder ofrecer el registro que ya existe, pero la
    comprobación se repite aquí: es el único punto por el que pasan todas las
    altas, vengan de la pantalla que vengan.
    """
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del cliente es obligatorio.")
    repetido = buscar_cliente_igual(nombre, telefono)
    if repetido:
        raise ValueError(
            f"«{nombre}» ya está registrado como el cliente "
            f"#{repetido['id_cliente']}"
            + (f" con el teléfono {repetido['telefono']}."
               if repetido["telefono"] else " (sin teléfono).")
        )
    with transaccion() as c:
        cursor = c.execute(
            "INSERT INTO clientes (nombre, telefono) VALUES (?, ?)",
            (nombre, normalizar_telefono(telefono)),
        )
        return int(cursor.lastrowid)


def actualizar_cliente(id_cliente: int, nombre: str, telefono: str | None) -> None:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del cliente es obligatorio.")

    # Corregir una ficha no puede convertirla en el duplicado de otra.
    repetido = buscar_cliente_igual(nombre, telefono, excluir_id=id_cliente)
    if repetido:
        raise ValueError(
            f"Esos datos ya son los del cliente #{repetido['id_cliente']} "
            f"({repetido['nombre']}). Si son la misma persona, usa esa ficha."
        )

    with transaccion() as c:
        c.execute(
            "UPDATE clientes SET nombre = ?, telefono = ? WHERE id_cliente = ?",
            (nombre, normalizar_telefono(telefono), id_cliente),
        )


# Singular y plural de cada tipo de registro, para que el mensaje que ve el
# usuario diga «1 nota» y no «1 notas».
_NOMBRES_DEPENDIENTES = {
    "notas": ("nota", "notas"),
    "cotizaciones": ("cotización", "cotizaciones"),
    "diagnosticos": ("diagnóstico", "diagnósticos"),
    "vehiculos": ("vehículo", "vehículos"),
}


def _detalle_dependientes(dependientes: dict[str, int]) -> str:
    """«1 nota, 2 vehículos» a partir del conteo por tipo; vacío si no hay."""
    partes = [
        f"{cuantos} {_NOMBRES_DEPENDIENTES[tipo][0 if cuantos == 1 else 1]}"
        for tipo, cuantos in dependientes.items() if cuantos
    ]
    return ", ".join(partes)


def contar_dependientes_cliente(id_cliente: int) -> dict[str, int]:
    """Cuántos registros cuelgan de un cliente, por tipo."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT (SELECT COUNT(*) FROM notas WHERE id_cliente = :id) AS notas,
                   (SELECT COUNT(*) FROM cotizaciones WHERE id_cliente = :id)
                       AS cotizaciones,
                   (SELECT COUNT(*) FROM diagnosticos WHERE id_cliente = :id)
                       AS diagnosticos,
                   (SELECT COUNT(*) FROM vehiculos WHERE id_cliente = :id)
                       AS vehiculos
            """,
            {"id": id_cliente},
        ).fetchone()
    return {k: fila[k] for k in fila.keys()}


def eliminar_cliente(id_cliente: int) -> None:
    """
    Borra un cliente que no tenga NADA colgando.

    Se comprueba antes en vez de dejar que estalle la llave foránea: ninguna
    de las que apuntan a `clientes` tiene ON DELETE CASCADE —a propósito, el
    historial de facturación no se borra de rebote—, así que sin esto el
    usuario solo vería un «FOREIGN KEY constraint failed» que no explica nada.
    """
    detalle = _detalle_dependientes(contar_dependientes_cliente(id_cliente))
    if detalle:
        raise ValueError(
            f"No se puede eliminar: el cliente todavía tiene {detalle}. "
            f"Bórralos primero, o corrige la ficha en vez de eliminarla."
        )
    with transaccion() as c:
        c.execute("DELETE FROM clientes WHERE id_cliente = ?", (id_cliente,))


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

def listar_catalogo(busqueda: str = "", tipo: str | None = None,
                    categoria: str | None = None,
                    solo_activos: bool = False) -> list[dict]:
    """Conceptos del catálogo con el número de veces que se han usado."""
    condiciones, parametros = [], []
    if tipo:
        condiciones.append("cat.tipo_concepto = ?")
        parametros.append(tipo)
    if categoria:
        condiciones.append("cat.categoria = ?")
        parametros.append(categoria)
    if solo_activos:
        condiciones.append("cat.activo = 1")
    filtro = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT cat.*, COUNT(p.id_partida) AS veces_usado
              FROM catalogo cat
              LEFT JOIN partidas p ON p.id_catalogo = cat.id_catalogo
              {filtro}
             GROUP BY cat.id_catalogo
             ORDER BY cat.descripcion, cat.tipo_concepto
            """,
            parametros,
        ).fetchall()

    conceptos = [dict(f) for f in filas]
    if busqueda:
        conceptos = [
            x for x in conceptos
            if _coincide(busqueda, x["descripcion"], x["categoria"], x["tipo_concepto"])
        ]
    return conceptos


def crear_concepto(descripcion: str, tipo_concepto: str, categoria: str,
                   precio_centavos: int) -> int:
    descripcion = descripcion.strip()
    if not descripcion:
        raise ValueError("La descripción es obligatoria.")
    with transaccion() as c:
        cursor = c.execute(
            """
            INSERT INTO catalogo (descripcion, tipo_concepto, categoria,
                                  precio_actual_centavos)
            VALUES (?, ?, ?, ?)
            """,
            (descripcion, tipo_concepto, categoria, precio_centavos),
        )
        return int(cursor.lastrowid)


def actualizar_concepto(id_catalogo: int, descripcion: str, tipo_concepto: str,
                        categoria: str, precio_centavos: int, activo: bool) -> None:
    """
    Edita un concepto del catálogo.

    Esto NO toca las partidas ya registradas: guardan su propia copia de la
    descripción y del precio, así que el histórico no se mueve.
    """
    with transaccion() as c:
        c.execute(
            """
            UPDATE catalogo
               SET descripcion = ?, tipo_concepto = ?, categoria = ?,
                   precio_actual_centavos = ?, activo = ?,
                   actualizado_en = datetime('now')
             WHERE id_catalogo = ?
            """,
            (descripcion.strip(), tipo_concepto, categoria, precio_centavos,
             1 if activo else 0, id_catalogo),
        )


def cambiar_estado_concepto(id_catalogo: int, activo: bool) -> None:
    """Activa o desactiva un concepto sin tocar nada más."""
    with transaccion() as c:
        c.execute(
            "UPDATE catalogo SET activo = ?, actualizado_en = datetime('now') "
            "WHERE id_catalogo = ?",
            (1 if activo else 0, id_catalogo),
        )


# ---------------------------------------------------------------------------
# Catálogo de productos (lo que se compra y se vende físicamente)
#
# Vive aparte del catálogo de conceptos cobrables: aquel incluye servicios
# (Alineación, Afinación, Mano de obra) que no son productos. Y sus categorías
# también son otro eje: `categorias` clasifica por sistema del carro,
# `categorias_producto` por tipo de producto.
# ---------------------------------------------------------------------------

def listar_categorias_producto() -> list[dict]:
    with conectar() as c:
        return [dict(f) for f in c.execute(
            "SELECT id_cat, nombre FROM categorias_producto ORDER BY id_cat")]


def listar_marcas_producto() -> list[str]:
    with conectar() as c:
        return [f["nombre"] for f in c.execute(
            "SELECT nombre FROM marcas_producto ORDER BY nombre")]


def agregar_marca_producto(nombre: str) -> None:
    with conectar() as c:
        c.execute("INSERT INTO marcas_producto (nombre) VALUES (?) "
                  "ON CONFLICT DO NOTHING", (nombre.strip(),))
        c.commit()


def listar_productos(busqueda: str = "", id_cat: str | None = None,
                     solo_activos: bool = False,
                     bajo_minimo: bool = False) -> list[dict]:
    condiciones, parametros = [], []
    if id_cat:
        condiciones.append("p.id_cat = ?")
        parametros.append(id_cat)
    if solo_activos:
        condiciones.append("p.activo = 1")
    if bajo_minimo:
        condiciones.append("p.stock_actual < p.stock_min")
    filtro = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT p.*, cp.nombre AS categoria
              FROM productos p
              JOIN categorias_producto cp ON cp.id_cat = p.id_cat
              {filtro}
             ORDER BY p.id_producto
            """,
            parametros,
        ).fetchall()

    productos = [dict(f) for f in filas]
    for p in productos:
        # Margen sobre el precio de venta; None si falta alguno de los dos.
        compra, venta = p["precio_compra_centavos"], p["precio_venta_centavos"]
        p["margen_centavos"] = (venta - compra) if (compra and venta) else None
        p["margen_pct"] = ((venta - compra) / venta * 100
                           if (compra and venta) else None)
    if busqueda:
        productos = [
            p for p in productos
            if _coincide(busqueda, p["id_producto"], p["nombre"], p["marca"],
                         p["categoria"], p["presentacion"])
        ]
    return productos


def siguiente_id_producto(prefijo: str = "AB") -> str:
    """Sigue la numeración del prefijo indicado: AB-001, AB-002…"""
    with conectar() as c:
        fila = c.execute(
            "SELECT MAX(CAST(SUBSTR(id_producto, ?) AS INTEGER)) AS maximo "
            "FROM productos WHERE id_producto LIKE ?",
            (len(prefijo) + 2, f"{prefijo}-%"),
        ).fetchone()
    return f"{prefijo}-{(fila['maximo'] or 0) + 1:03d}"


def crear_producto(id_producto: str, id_cat: str, nombre: str,
                   unidad: str | None, presentacion: str | None,
                   contenido: float | None, marca: str | None,
                   precio_compra_centavos: int | None,
                   precio_venta_centavos: int | None,
                   stock_actual: float = 0, stock_min: float = 0) -> str:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del producto es obligatorio.")
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        c.execute(
            """
            INSERT INTO productos (id_producto, id_cat, nombre, unidad,
                                   presentacion, contenido, marca,
                                   precio_compra_centavos, precio_venta_centavos,
                                   stock_actual, stock_min)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_producto.strip(), id_cat, nombre, limpio(unidad),
             limpio(presentacion), contenido, limpio(marca),
             precio_compra_centavos, precio_venta_centavos,
             stock_actual, stock_min),
        )
    return id_producto.strip()


def actualizar_producto(id_producto: str, id_cat: str, nombre: str,
                        unidad: str | None, presentacion: str | None,
                        contenido: float | None, marca: str | None,
                        precio_compra_centavos: int | None,
                        precio_venta_centavos: int | None,
                        stock_actual: float, stock_min: float,
                        activo: bool) -> None:
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        c.execute(
            """
            UPDATE productos
               SET id_cat = ?, nombre = ?, unidad = ?, presentacion = ?,
                   contenido = ?, marca = ?, precio_compra_centavos = ?,
                   precio_venta_centavos = ?, stock_actual = ?, stock_min = ?,
                   activo = ?, actualizado_en = datetime('now')
             WHERE id_producto = ?
            """,
            (id_cat, nombre.strip(), limpio(unidad), limpio(presentacion),
             contenido, limpio(marca), precio_compra_centavos,
             precio_venta_centavos, stock_actual, stock_min,
             1 if activo else 0, id_producto),
        )


# ---------------------------------------------------------------------------
# Notas de servicio
# ---------------------------------------------------------------------------

def listar_notas(busqueda: str = "", desde: str | None = None,
                 hasta: str | None = None) -> list[dict]:
    """Notas con el nombre del cliente y el número de partidas."""
    condiciones, parametros = [], []
    if desde:
        condiciones.append("n.fecha >= ?")
        parametros.append(desde)
    if hasta:
        condiciones.append("n.fecha <= ?")
        parametros.append(hasta)
    filtro = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT n.*, cl.nombre AS cliente,
                   v.marca, v.modelo, v.anio, v.color,
                   n.total_centavos - n.pagado_centavos AS saldo_centavos,
                   COUNT(p.id_partida) AS num_partidas
              FROM notas n
              JOIN clientes cl ON cl.id_cliente = n.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = n.id_vehiculo
              LEFT JOIN partidas p ON p.id_nota = n.id_nota
              {filtro}
             GROUP BY n.id_nota
             ORDER BY n.fecha DESC, n.id_nota DESC
            """,
            parametros,
        ).fetchall()

    notas = [dict(f) for f in filas]
    if busqueda:
        notas = [
            n for n in notas
            if _coincide(busqueda, n["id_nota"], n["cliente"], n["marca"],
                         n["modelo"], n["color"], n["estado"])
        ]
    return notas


def obtener_nota(id_nota: str) -> dict | None:
    """Devuelve la nota con sus partidas en la clave `partidas`."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT n.*, cl.nombre AS cliente, cl.telefono,
                   v.marca, v.modelo, v.anio, v.color, v.placas,
                   n.total_centavos - n.pagado_centavos AS saldo_centavos
              FROM notas n
              JOIN clientes cl ON cl.id_cliente = n.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = n.id_vehiculo
             WHERE n.id_nota = ?
            """,
            (id_nota,),
        ).fetchone()
        if fila is None:
            return None
        partidas = c.execute(
            "SELECT * FROM partidas WHERE id_nota = ? ORDER BY linea", (id_nota,)
        ).fetchall()

    nota = dict(fila)
    nota["partidas"] = [dict(p) for p in partidas]
    return nota


# Tasa de IVA vigente en México. Se usa como valor por omisión al ofrecer el
# impuesto; la nota guarda la suya, así que una tasa histórica no se altera si
# el día de mañana cambia la ley.
TASA_IVA = 0.16


def crear_nota(id_cliente: int, fecha: str, id_vehiculo: int | None,
               partidas: list[dict], estado: str = "Recibido",
               pagado_centavos: int = 0, tasa_iva: float = 0.0) -> str:
    """
    Crea una nota con todas sus partidas en una sola transacción.

    `partidas` es una lista de diccionarios con las claves: tipo_concepto,
    categoria, accion, descripcion, posicion, lado, cantidad,
    precio_unitario_centavos y, opcionalmente, id_catalogo.

    El total de la nota NO se pasa: lo calculan los triggers a partir de las
    partidas, que es justo lo que la especificación pide.
    """
    if not partidas:
        raise ValueError("La nota necesita al menos una partida.")

    with transaccion() as c:
        # El folio se genera dentro de la transacción para que dos capturas
        # simultáneas no puedan recibir el mismo.
        id_nota = siguiente_id_nota(c)
        c.execute(
            """
            INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha,
                               estado, pagado_centavos, tasa_iva)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (id_nota, id_cliente, id_vehiculo, fecha, estado, pagado_centavos,
             float(tasa_iva)),
        )

        for linea, p in enumerate(partidas, start=1):
            cantidad = int(p["cantidad"])
            precio = int(p["precio_unitario_centavos"])
            c.execute(
                """
                INSERT INTO partidas (id_nota, linea, id_catalogo, tipo_concepto,
                                      categoria, accion, descripcion, posicion, lado,
                                      cantidad, precio_unitario_centavos,
                                      total_centavos, notas, id_producto,
                                      costo_unitario_centavos)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (id_nota, linea, p.get("id_catalogo"), p["tipo_concepto"],
                 p["categoria"], p.get("accion"), p["descripcion"].strip(),
                 p.get("posicion"), p.get("lado"), cantidad, precio,
                 cantidad * precio, (p.get("notas") or "").strip() or None,
                 p.get("id_producto"), p.get("costo_unitario_centavos")),
            )

    return id_nota


def eliminar_nota(id_nota: str) -> None:
    """
    Borra una nota y, en cascada, sus partidas.

    Si la nota vino de convertir una cotización, esa cotización vuelve a
    quedar Pendiente en vez de bloquear el borrado (por la llave foránea de
    `id_nota_generada`) o dejar una referencia rota a un folio que ya no
    existe. Así el presupuesto se puede volver a convertir más adelante si
    hizo falta corregir la nota.
    """
    with transaccion() as c:
        c.execute(
            "UPDATE cotizaciones SET estado = 'Pendiente', "
            "id_nota_generada = NULL WHERE id_nota_generada = ?", (id_nota,))
        c.execute("DELETE FROM notas WHERE id_nota = ?", (id_nota,))


def actualizar_nota(id_nota: str, id_cliente: int, fecha: str,
                    id_vehiculo: int | None) -> None:
    """
    Edita la cabecera de una nota: cliente, fecha y vehículo atendido.

    No toca las partidas ni el total; el total lo siguen manteniendo los
    triggers a partir de los renglones. El estado y el pago se cambian con sus
    propias funciones, porque son acciones distintas de "corregir la ficha".
    """
    with transaccion() as c:
        c.execute(
            """
            UPDATE notas
               SET id_cliente = ?, fecha = ?, id_vehiculo = ?
             WHERE id_nota = ?
            """,
            (id_cliente, fecha, id_vehiculo, id_nota),
        )


ESTADOS = ["Recibido", "En proceso", "Esperando refacción", "Terminado",
           "Entregado"]


def cambiar_estado(id_nota: str, estado: str) -> None:
    """
    Mueve la nota en el flujo del taller.

    Al pasar a «Entregado» se marca como pagada por completo: el taller no
    entrega un carro sin cobrarlo, así que exigir el registro manual del pago
    cada vez era un paso de más. Va aquí y no en la pantalla para que valga
    sin importar desde dónde se llame. Mover la nota a cualquier OTRO estado
    no toca el pago — un abono ya registrado no debe desaparecer solo porque
    el estado cambió de nuevo.
    """
    if estado not in ESTADOS:
        raise ValueError(f"Estado desconocido: {estado}")
    with transaccion() as c:
        if estado == "Entregado":
            c.execute(
                "UPDATE notas SET estado = ?, pagado_centavos = total_centavos "
                "WHERE id_nota = ?",
                (estado, id_nota))
        else:
            c.execute("UPDATE notas SET estado = ? WHERE id_nota = ?",
                      (estado, id_nota))


def cambiar_tasa_iva(id_nota: str, tasa_iva: float) -> None:
    """
    Aplica o quita el IVA de una nota.

    Solo se guarda la tasa: el importe y el total los recalcula el trigger
    desde el subtotal, así que nunca queda un impuesto que no corresponda a
    lo cobrado.
    """
    tasa = float(tasa_iva)
    if not 0 <= tasa <= 1:
        raise ValueError("La tasa de IVA debe estar entre 0 y 1 (0.16 = 16%).")
    with transaccion() as c:
        c.execute("UPDATE notas SET tasa_iva = ? WHERE id_nota = ?",
                  (tasa, id_nota))


def registrar_pago(id_nota: str, pagado_centavos: int) -> None:
    """
    Fija cuánto lleva pagado la nota.

    Se valida aquí y no en la base: al crear una nota el total todavía vale
    cero porque los triggers lo llenan al insertar las partidas, así que una
    restricción `pagado <= total` en el esquema rechazaría capturas legítimas.
    """
    pagado_centavos = int(pagado_centavos)
    if pagado_centavos < 0:
        raise ValueError("El pago no puede ser negativo.")
    with transaccion() as c:
        total = c.execute(
            "SELECT total_centavos FROM notas WHERE id_nota = ?", (id_nota,)
        ).fetchone()
        if total is None:
            raise ValueError(f"No existe la nota {id_nota}.")
        if pagado_centavos > total["total_centavos"]:
            raise ValueError(
                f"El pago ({formato_pesos(pagado_centavos)}) supera el total "
                f"de la nota ({formato_pesos(total['total_centavos'])})."
            )
        c.execute("UPDATE notas SET pagado_centavos = ? WHERE id_nota = ?",
                  (pagado_centavos, id_nota))


# ---------------------------------------------------------------------------
# Vehículos
# ---------------------------------------------------------------------------

def listar_vehiculos(busqueda: str = "", id_cliente: int | None = None,
                     solo_activos: bool = False) -> list[dict]:
    """Vehículos con su dueño y el resumen de servicios recibidos."""
    condiciones, parametros = [], []
    if id_cliente is not None:
        condiciones.append("v.id_cliente = ?")
        parametros.append(id_cliente)
    if solo_activos:
        condiciones.append("v.activo = 1")
    filtro = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with conectar() as c:
        # LEFT JOIN al cliente: un vehículo puede estar en el padrón sin dueño
        # registrado, y con un JOIN normal esos carros desaparecerían de la
        # lista sin avisar.
        filas = c.execute(
            f"""
            SELECT v.*, cl.nombre AS cliente, cl.telefono,
                   COUNT(n.id_nota) AS num_notas,
                   COALESCE(SUM(n.total_centavos), 0) AS total_centavos,
                   MAX(n.fecha) AS ultimo_servicio,
                   (SELECT cl2.nombre
                      FROM notas n2
                      JOIN clientes cl2 ON cl2.id_cliente = n2.id_cliente
                     WHERE n2.id_vehiculo = v.id_vehiculo
                     ORDER BY n2.fecha DESC LIMIT 1) AS ultimo_cliente
              FROM vehiculos v
              LEFT JOIN clientes cl ON cl.id_cliente = v.id_cliente
              LEFT JOIN notas n ON n.id_vehiculo = v.id_vehiculo
              {filtro}
             GROUP BY v.id_vehiculo
             ORDER BY v.marca, v.modelo, v.anio
            """,
            parametros,
        ).fetchall()

    vehiculos = [dict(f) for f in filas]
    if busqueda:
        vehiculos = [
            v for v in vehiculos
            if _coincide(busqueda, v["marca"], v["modelo"], v["color"],
                         v["placas"], v["cliente"], str(v["anio"] or ""))
        ]
    return vehiculos


def obtener_vehiculo(id_vehiculo: int) -> dict | None:
    """El vehículo con su historial de servicios en la clave `historial`."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT v.*, cl.nombre AS cliente, cl.telefono
              FROM vehiculos v
              LEFT JOIN clientes cl ON cl.id_cliente = v.id_cliente
             WHERE v.id_vehiculo = ?
            """,
            (id_vehiculo,),
        ).fetchone()
        if fila is None:
            return None
        # El historial trae el cliente de CADA servicio: el carro pudo cambiar
        # de manos, y quien lo trajo esa vez lo dice la nota, no la ficha.
        historial = c.execute(
            """
            SELECT n.id_nota, n.fecha, n.estado, n.total_centavos,
                   n.pagado_centavos, cl.nombre AS cliente,
                   COUNT(p.id_partida) AS num_partidas
              FROM notas n
              JOIN clientes cl ON cl.id_cliente = n.id_cliente
              LEFT JOIN partidas p ON p.id_nota = n.id_nota
             WHERE n.id_vehiculo = ?
             GROUP BY n.id_nota
             ORDER BY n.fecha DESC
            """,
            (id_vehiculo,),
        ).fetchall()
        conceptos = c.execute(
            """
            SELECT p.categoria, COUNT(*) AS veces,
                   SUM(p.total_centavos) AS importe_centavos
              FROM partidas p
              JOIN notas n ON n.id_nota = p.id_nota
             WHERE n.id_vehiculo = ?
             GROUP BY p.categoria
             ORDER BY importe_centavos DESC
            """,
            (id_vehiculo,),
        ).fetchall()

    vehiculo = dict(fila)
    vehiculo["historial"] = [dict(h) for h in historial]
    vehiculo["por_categoria"] = [dict(x) for x in conceptos]
    return vehiculo


def descripcion_vehiculo(vehiculo: dict) -> str:
    """El carro en una línea: «Chevrolet Camaro 2018 · NND-NND-1»."""
    partes = [vehiculo.get("marca"), vehiculo.get("modelo"),
              str(vehiculo["anio"]) if vehiculo.get("anio") else None]
    texto = " ".join(p for p in partes if p)
    if vehiculo.get("placas"):
        texto += f" · {vehiculo['placas']}"
    return texto or "sin datos"


def normalizar_placas(placas: str | None) -> str | None:
    """
    Deja la placa en mayúsculas y sin espacios sobrantes, o None si va vacía.

    Se normaliza al guardar, no solo al comparar: si una placa entrara como
    'abc123' y otra como 'ABC-123 ', serían el mismo carro para cualquiera
    menos para la base. El índice único del esquema compara con
    `upper(trim(placas))`, así que guardarlas ya normalizadas es lo que hace
    que la app y la base entiendan lo mismo por «la misma placa».
    """
    return (placas or "").strip().upper() or None


def buscar_vehiculo_igual(id_cliente: int, marca: str, modelo: str | None,
                          anio: int | None, color: str | None,
                          placas: str | None = None,
                          excluir_id: int | None = None) -> dict | None:
    """
    Busca el vehículo que ya ES este carro.

    Dos reglas, porque un taller sí atiende carros idénticos:

      * CON placa, la placa manda y vale para todo el padrón: no existen dos
        carros con la misma placa, aunque estén a nombre de personas
        distintas (un cambio de dueño se corrige editando la ficha, no
        registrando el carro otra vez).
      * SIN placa no hay con qué distinguir, así que cuenta como repetido el
        mismo dueño con la misma marca, tipo, año y color. Es exactamente el
        caso real de los seis Camaro idénticos del mismo cliente. La salida
        para dos carros de verdad iguales es capturar su placa.
    """
    placa = normalizar_placas(placas)
    with conectar() as c:
        if placa:
            fila = c.execute(
                """
                SELECT v.*, cl.nombre AS cliente
                  FROM vehiculos v
                  JOIN clientes cl ON cl.id_cliente = v.id_cliente
                 WHERE upper(trim(v.placas)) = ? AND v.id_vehiculo IS NOT ?
                 LIMIT 1
                """,
                (placa, excluir_id),
            ).fetchone()
            return dict(fila) if fila else None

        filas = c.execute(
            """
            SELECT v.*, cl.nombre AS cliente
              FROM vehiculos v
              JOIN clientes cl ON cl.id_cliente = v.id_cliente
             WHERE v.id_cliente = ?
               AND (v.placas IS NULL OR trim(v.placas) = '')
               AND v.id_vehiculo IS NOT ?
            """,
            (id_cliente, excluir_id),
        ).fetchall()

    for fila in filas:
        if (plegar(fila["marca"]) == plegar(marca)
                and plegar(fila["modelo"]) == plegar(modelo)
                and (fila["anio"] or None) == (anio or None)
                and plegar(fila["color"]) == plegar(color)):
            return dict(fila)
    return None


def crear_vehiculo(id_cliente: int, marca: str, modelo: str | None,
                   anio: int | None, color: str | None,
                   placas: str | None = None, vin: str | None = None,
                   observaciones: str | None = None) -> int:
    # Un carro siempre llega con dueño; se valida aquí para dar un mensaje
    # claro en vez de dejar que estalle la restricción de la base.
    if id_cliente is None:
        raise ValueError("El vehículo necesita un dueño.")

    # Igual que en `crear_cliente`: la pantalla ya lo comprueba para ofrecer el
    # registro existente, pero este es el único punto por el que pasan todas
    # las altas de vehículo de la app.
    repetido = buscar_vehiculo_igual(id_cliente, marca, modelo, anio, color,
                                     placas)
    if repetido:
        raise ValueError(
            f"Ese vehículo ya está registrado como #{repetido['id_vehiculo']}: "
            f"{descripcion_vehiculo(repetido)} (dueño: {repetido['cliente']})."
        )

    with transaccion() as c:
        cursor = c.execute(
            """
            INSERT INTO vehiculos (id_cliente, marca, modelo, anio, color,
                                   placas, vin, observaciones)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_cliente, marca, (modelo or "").strip() or None, anio,
             (color or "").strip() or None, normalizar_placas(placas),
             (vin or "").strip() or None, (observaciones or "").strip() or None),
        )
        return int(cursor.lastrowid)


def actualizar_vehiculo(id_vehiculo: int, id_cliente: int, marca: str,
                        modelo: str | None, anio: int | None,
                        color: str | None, placas: str | None,
                        vin: str | None, observaciones: str | None,
                        activo: bool) -> None:
    if id_cliente is None:
        raise ValueError("El vehículo necesita un dueño.")

    # Corregir una ficha no puede convertirla en el gemelo de otra que ya
    # existe; `excluir_id` deja fuera de la comparación al propio vehículo.
    repetido = buscar_vehiculo_igual(id_cliente, marca, modelo, anio, color,
                                     placas, excluir_id=id_vehiculo)
    if repetido:
        raise ValueError(
            f"Esos datos ya son los del vehículo #{repetido['id_vehiculo']}: "
            f"{descripcion_vehiculo(repetido)} (dueño: {repetido['cliente']})."
        )

    with transaccion() as c:
        c.execute(
            """
            UPDATE vehiculos
               SET id_cliente = ?, marca = ?, modelo = ?, anio = ?, color = ?,
                   placas = ?, vin = ?, observaciones = ?, activo = ?
             WHERE id_vehiculo = ?
            """,
            (id_cliente, marca, (modelo or "").strip() or None, anio,
             (color or "").strip() or None, normalizar_placas(placas),
             (vin or "").strip() or None, (observaciones or "").strip() or None,
             1 if activo else 0, id_vehiculo),
        )


def contar_dependientes_vehiculo(id_vehiculo: int) -> dict[str, int]:
    """Cuántos documentos cuelgan de un vehículo, por tipo."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT (SELECT COUNT(*) FROM notas WHERE id_vehiculo = :id) AS notas,
                   (SELECT COUNT(*) FROM cotizaciones WHERE id_vehiculo = :id)
                       AS cotizaciones,
                   (SELECT COUNT(*) FROM diagnosticos WHERE id_vehiculo = :id)
                       AS diagnosticos
            """,
            {"id": id_vehiculo},
        ).fetchone()
    return {k: fila[k] for k in fila.keys()}


def eliminar_vehiculo(id_vehiculo: int) -> None:
    """
    Borra un vehículo que no tenga documentos asociados.

    Mismo criterio que `eliminar_cliente`: se comprueba antes para dar un
    mensaje legible. Para un carro que SÍ tiene historial y ya no viene al
    taller, lo correcto no es borrarlo —se perdería de qué carro era cada
    nota— sino desactivarlo (`activo = 0`), que ya lo saca de las listas de
    captura.
    """
    detalle = _detalle_dependientes(contar_dependientes_vehiculo(id_vehiculo))
    if detalle:
        raise ValueError(
            f"No se puede eliminar: el vehículo tiene {detalle}. "
            f"Si ya no viene al taller, desactívalo en vez de borrarlo."
        )
    with transaccion() as c:
        c.execute("DELETE FROM vehiculos WHERE id_vehiculo = ?", (id_vehiculo,))


# ---------------------------------------------------------------------------
# Diagnósticos con escáner — reporte de códigos de falla (DTC).
#
# No maneja dinero ni catálogo: es la lectura del escáner (folio, cliente,
# vehículo, códigos por sistema) tal como se entrega hoy en papel. El técnico
# llena los códigos y el resumen a mano, igual que en el formato impreso.
# ---------------------------------------------------------------------------

GRAVEDADES = ["ALTA", "MEDIA", "BAJA", "INFO"]


def siguiente_id_diagnostico(conexion: sqlite3.Connection) -> str:
    """Folio propio, 'DX-001', para no confundirse con notas ni cotizaciones."""
    fila = conexion.execute(
        "SELECT MAX(CAST(SUBSTR(id_diagnostico, 4) AS INTEGER)) AS maximo "
        "FROM diagnosticos"
    ).fetchone()
    siguiente = (fila["maximo"] or 0) + 1
    return f"DX-{siguiente:03d}"


def listar_diagnosticos(busqueda: str = "") -> list[dict]:
    """Diagnósticos con el nombre del cliente, el vehículo y el total de códigos."""
    with conectar() as c:
        filas = c.execute(
            """
            SELECT d.*, cl.nombre AS cliente,
                   v.marca, v.modelo, v.anio, v.color,
                   COUNT(cod.id_item) AS num_codigos
              FROM diagnosticos d
              JOIN clientes cl ON cl.id_cliente = d.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = d.id_vehiculo
              LEFT JOIN diagnostico_codigos cod
                     ON cod.id_diagnostico = d.id_diagnostico
             GROUP BY d.id_diagnostico
             ORDER BY d.fecha DESC, d.id_diagnostico DESC
            """
        ).fetchall()

    diagnosticos = [dict(f) for f in filas]
    if busqueda:
        diagnosticos = [
            d for d in diagnosticos
            if _coincide(busqueda, d["id_diagnostico"], d["cliente"],
                        d["marca"], d["modelo"], d["color"], d["tecnico"])
        ]
    return diagnosticos


def obtener_diagnostico(id_diagnostico: str) -> dict | None:
    """Devuelve el diagnóstico con sus códigos en la clave `codigos`."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT d.*, cl.nombre AS cliente, cl.telefono,
                   v.marca, v.modelo, v.anio, v.color, v.placas
              FROM diagnosticos d
              JOIN clientes cl ON cl.id_cliente = d.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = d.id_vehiculo
             WHERE d.id_diagnostico = ?
            """,
            (id_diagnostico,),
        ).fetchone()
        if fila is None:
            return None
        codigos = c.execute(
            "SELECT * FROM diagnostico_codigos WHERE id_diagnostico = ? "
            "ORDER BY linea",
            (id_diagnostico,),
        ).fetchall()

    diagnostico = dict(fila)
    diagnostico["codigos"] = [dict(x) for x in codigos]
    return diagnostico


def crear_diagnostico(id_cliente: int, id_vehiculo: int, fecha: str,
                      codigos: list[dict], tecnico: str | None = None,
                      num_modulos: int | None = None,
                      otros_modulos: str | None = None,
                      resumen: str | None = None) -> str:
    """
    Crea un diagnóstico con todos sus códigos en una sola transacción.

    `codigos` es una lista de diccionarios con las claves: sistema,
    sistema_nota (opcional), codigo, descripcion, significado y gravedad.
    """
    if not codigos:
        raise ValueError("El diagnóstico necesita al menos un código.")

    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        id_diagnostico = siguiente_id_diagnostico(c)
        c.execute(
            """
            INSERT INTO diagnosticos (id_diagnostico, id_cliente, id_vehiculo,
                                      fecha, tecnico, num_modulos,
                                      otros_modulos, resumen)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_diagnostico, id_cliente, id_vehiculo, fecha, limpio(tecnico),
             num_modulos, limpio(otros_modulos), limpio(resumen)),
        )

        for linea, cod in enumerate(codigos, start=1):
            c.execute(
                """
                INSERT INTO diagnostico_codigos
                    (id_diagnostico, linea, sistema, sistema_nota, codigo,
                     descripcion, significado, gravedad)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (id_diagnostico, linea, cod["sistema"].strip(),
                 limpio(cod.get("sistema_nota")), cod["codigo"].strip(),
                 cod["descripcion"].strip(), cod["significado"].strip(),
                 cod.get("gravedad") or "MEDIA"),
            )

    return id_diagnostico


def actualizar_diagnostico(id_diagnostico: str, id_cliente: int,
                           id_vehiculo: int, fecha: str,
                           tecnico: str | None = None,
                           num_modulos: int | None = None,
                           otros_modulos: str | None = None,
                           resumen: str | None = None) -> None:
    """Edita la cabecera de un diagnóstico: no toca sus códigos."""
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        c.execute(
            """
            UPDATE diagnosticos
               SET id_cliente = ?, id_vehiculo = ?, fecha = ?, tecnico = ?,
                   num_modulos = ?, otros_modulos = ?, resumen = ?
             WHERE id_diagnostico = ?
            """,
            (id_cliente, id_vehiculo, fecha, limpio(tecnico), num_modulos,
             limpio(otros_modulos), limpio(resumen), id_diagnostico),
        )


def siguiente_linea_diagnostico(conexion: sqlite3.Connection,
                                id_diagnostico: str) -> int:
    """Devuelve el siguiente consecutivo de código dentro de un diagnóstico."""
    fila = conexion.execute(
        "SELECT COALESCE(MAX(linea), 0) AS maximo FROM diagnostico_codigos "
        "WHERE id_diagnostico = ?",
        (id_diagnostico,),
    ).fetchone()
    return int(fila["maximo"]) + 1


def _renumerar_lineas_diagnostico(conexion: sqlite3.Connection,
                                  id_diagnostico: str) -> None:
    """Igual que `_renumerar_lineas`, pero para `diagnostico_codigos`."""
    conexion.execute(
        "UPDATE diagnostico_codigos SET linea = linea + 100000 "
        "WHERE id_diagnostico = ?", (id_diagnostico,)
    )
    filas = conexion.execute(
        "SELECT id_item FROM diagnostico_codigos WHERE id_diagnostico = ? "
        "ORDER BY linea",
        (id_diagnostico,),
    ).fetchall()
    for numero, fila in enumerate(filas, start=1):
        conexion.execute(
            "UPDATE diagnostico_codigos SET linea = ? WHERE id_item = ?",
            (numero, fila["id_item"]),
        )


def agregar_diagnostico_codigo(id_diagnostico: str, codigo: dict) -> int:
    """Agrega un código al final de un diagnóstico existente."""
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        linea = siguiente_linea_diagnostico(c, id_diagnostico)
        cursor = c.execute(
            """
            INSERT INTO diagnostico_codigos
                (id_diagnostico, linea, sistema, sistema_nota, codigo,
                 descripcion, significado, gravedad)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_diagnostico, linea, codigo["sistema"].strip(),
             limpio(codigo.get("sistema_nota")), codigo["codigo"].strip(),
             codigo["descripcion"].strip(), codigo["significado"].strip(),
             codigo.get("gravedad") or "MEDIA"),
        )
        return int(cursor.lastrowid)


def actualizar_diagnostico_codigo(id_item: int, codigo: str, descripcion: str,
                                  significado: str, gravedad: str,
                                  sistema: str | None = None,
                                  sistema_nota: str | None = None) -> None:
    """
    Cambia los datos de un código ya capturado.

    `sistema` normalmente no cambia al editar un renglón suelto —cambiarlo
    significaría moverlo a otro grupo del reporte—, así que es opcional: si no
    se da, se deja el que ya tenía.
    """
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        if sistema is None:
            fila = c.execute(
                "SELECT sistema FROM diagnostico_codigos WHERE id_item = ?",
                (id_item,),
            ).fetchone()
            if fila is None:
                raise ValueError("El código ya no existe.")
            sistema = fila["sistema"]
        c.execute(
            """
            UPDATE diagnostico_codigos
               SET sistema = ?, sistema_nota = ?, codigo = ?, descripcion = ?,
                   significado = ?, gravedad = ?
             WHERE id_item = ?
            """,
            (sistema.strip(), limpio(sistema_nota), codigo.strip(),
             descripcion.strip(), significado.strip(), gravedad, id_item),
        )


def eliminar_diagnostico_codigo(id_item: int) -> None:
    """Borra un código y renumera los que quedan."""
    with transaccion() as c:
        fila = c.execute(
            "SELECT id_diagnostico FROM diagnostico_codigos WHERE id_item = ?",
            (id_item,),
        ).fetchone()
        if fila is None:
            raise ValueError("El código ya no existe.")
        id_diagnostico = fila["id_diagnostico"]

        cuantos = c.execute(
            "SELECT COUNT(*) AS n FROM diagnostico_codigos "
            "WHERE id_diagnostico = ?", (id_diagnostico,)
        ).fetchone()["n"]
        if cuantos <= 1:
            raise ValueError(
                "Un diagnóstico no puede quedarse sin códigos. "
                "Si quieres deshacerlo, elimina el diagnóstico completo."
            )

        c.execute("DELETE FROM diagnostico_codigos WHERE id_item = ?", (id_item,))
        _renumerar_lineas_diagnostico(c, id_diagnostico)


def eliminar_diagnostico(id_diagnostico: str) -> None:
    """Borra un diagnóstico y, en cascada, sus códigos."""
    with transaccion() as c:
        c.execute("DELETE FROM diagnosticos WHERE id_diagnostico = ?",
                  (id_diagnostico,))


# ---------------------------------------------------------------------------
# Datos del taller
# ---------------------------------------------------------------------------

def obtener_taller() -> dict:
    """Los datos del negocio que salen en la nota impresa."""
    with conectar() as c:
        fila = c.execute("SELECT * FROM taller WHERE id = 1").fetchone()
    if fila is None:
        return {"nombre": "Auto Servicio Bautista", "subtitulo": "Nota de servicio",
                "direccion": None, "telefono": None, "correo": None,
                "rfc": None, "pie_nota": None}
    return dict(fila)


def actualizar_taller(nombre: str, subtitulo: str | None, direccion: str | None,
                      telefono: str | None, correo: str | None, rfc: str | None,
                      pie_nota: str | None) -> None:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre del taller es obligatorio.")
    limpio = lambda v: (v or "").strip() or None  # noqa: E731
    with transaccion() as c:
        c.execute(
            """
            INSERT INTO taller (id, nombre, subtitulo, direccion, telefono,
                                correo, rfc, pie_nota, actualizado_en)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT (id) DO UPDATE SET
                nombre = excluded.nombre,
                subtitulo = excluded.subtitulo,
                direccion = excluded.direccion,
                telefono = excluded.telefono,
                correo = excluded.correo,
                rfc = excluded.rfc,
                pie_nota = excluded.pie_nota,
                actualizado_en = excluded.actualizado_en
            """,
            (nombre, limpio(subtitulo), limpio(direccion), limpio(telefono),
             limpio(correo), limpio(rfc), limpio(pie_nota)),
        )


# ---------------------------------------------------------------------------
# Usuarios (para la pantalla de configuración)
# ---------------------------------------------------------------------------

def listar_usuarios() -> list[dict]:
    with conectar() as c:
        filas = c.execute(
            """
            SELECT id_usuario, usuario, rol, activo, creado_en, ultimo_acceso
              FROM usuarios ORDER BY id_usuario
            """
        ).fetchall()
    return [dict(f) for f in filas]


def cambiar_estado_usuario(id_usuario: int, activo: bool) -> None:
    """
    Activa o desactiva un usuario.

    Se impide desactivar al último administrador activo: dejaría la aplicación
    sin nadie que pueda administrarla.
    """
    with transaccion() as c:
        if not activo:
            admins = c.execute(
                "SELECT COUNT(*) n FROM usuarios WHERE rol = 'admin' AND activo = 1"
            ).fetchone()["n"]
            era_admin = c.execute(
                "SELECT rol FROM usuarios WHERE id_usuario = ?", (id_usuario,)
            ).fetchone()
            if era_admin and era_admin["rol"] == "admin" and admins <= 1:
                raise ValueError(
                    "No puedes desactivar al único administrador activo."
                )
        c.execute("UPDATE usuarios SET activo = ? WHERE id_usuario = ?",
                  (1 if activo else 0, id_usuario))


def cambiar_rol_usuario(id_usuario: int, rol: str) -> None:
    if rol not in ("admin", "operador"):
        raise ValueError(f"Rol desconocido: {rol}")
    with transaccion() as c:
        if rol != "admin":
            admins = c.execute(
                "SELECT COUNT(*) n FROM usuarios WHERE rol = 'admin' AND activo = 1"
            ).fetchone()["n"]
            actual = c.execute(
                "SELECT rol, activo FROM usuarios WHERE id_usuario = ?",
                (id_usuario,),
            ).fetchone()
            if actual and actual["rol"] == "admin" and actual["activo"] and admins <= 1:
                raise ValueError(
                    "No puedes quitarle el rol al único administrador activo."
                )
        c.execute("UPDATE usuarios SET rol = ? WHERE id_usuario = ?",
                  (rol, id_usuario))


def _renumerar_lineas(conexion: sqlite3.Connection, id_nota: str) -> None:
    """
    Deja las líneas de una nota como 1..n sin huecos.

    Se hace en dos pasos porque `UNIQUE (id_nota, linea)` se valida fila por
    fila: si se reasignara directo, una fila intermedia chocaría con otra que
    todavía no se ha movido. Primero se desplazan todas fuera de rango y luego
    se reasignan en orden.
    """
    conexion.execute(
        "UPDATE partidas SET linea = linea + 100000 WHERE id_nota = ?", (id_nota,)
    )
    filas = conexion.execute(
        "SELECT id_partida FROM partidas WHERE id_nota = ? ORDER BY linea",
        (id_nota,),
    ).fetchall()
    for numero, fila in enumerate(filas, start=1):
        conexion.execute(
            "UPDATE partidas SET linea = ? WHERE id_partida = ?",
            (numero, fila["id_partida"]),
        )


def agregar_partida(id_nota: str, partida: dict) -> int:
    """Agrega un renglón al final de una nota existente."""
    with transaccion() as c:
        linea = siguiente_linea(c, id_nota)
        cantidad = int(partida["cantidad"])
        precio = int(partida["precio_unitario_centavos"])
        cursor = c.execute(
            """
            INSERT INTO partidas (id_nota, linea, id_catalogo, tipo_concepto,
                                  categoria, accion, descripcion, posicion, lado,
                                  cantidad, precio_unitario_centavos,
                                  total_centavos, notas, id_producto,
                                  costo_unitario_centavos)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_nota, linea, partida.get("id_catalogo"), partida["tipo_concepto"],
             partida["categoria"], partida.get("accion"),
             partida["descripcion"].strip(), partida.get("posicion"),
             partida.get("lado"), cantidad, precio, cantidad * precio,
             (partida.get("notas") or "").strip() or None,
             partida.get("id_producto"), partida.get("costo_unitario_centavos")),
        )
        return int(cursor.lastrowid)


def actualizar_partida(id_partida: int, cantidad: int,
                       precio_unitario_centavos: int) -> None:
    """
    Cambia la cantidad o el precio de un renglón.

    El total se recalcula aquí para no violar el CHECK, y el trigger se encarga
    de actualizar el total de la nota.
    """
    cantidad = int(cantidad)
    precio = int(precio_unitario_centavos)
    with transaccion() as c:
        c.execute(
            """
            UPDATE partidas
               SET cantidad = ?, precio_unitario_centavos = ?, total_centavos = ?
             WHERE id_partida = ?
            """,
            (cantidad, precio, cantidad * precio, id_partida),
        )


def eliminar_partida(id_partida: int) -> None:
    """
    Borra un renglón y renumera los que quedan.

    Se impide dejar una nota sin partidas: su total quedaría en cero y la
    especificación exige que el total de la nota sea la suma de sus renglones.
    """
    with transaccion() as c:
        fila = c.execute(
            "SELECT id_nota FROM partidas WHERE id_partida = ?", (id_partida,)
        ).fetchone()
        if fila is None:
            raise ValueError("La partida ya no existe.")
        id_nota = fila["id_nota"]

        cuantas = c.execute(
            "SELECT COUNT(*) AS n FROM partidas WHERE id_nota = ?", (id_nota,)
        ).fetchone()["n"]
        if cuantas <= 1:
            raise ValueError(
                "Una nota no puede quedarse sin partidas. "
                "Si quieres deshacerla, elimina la nota completa."
            )

        c.execute("DELETE FROM partidas WHERE id_partida = ?", (id_partida,))
        _renumerar_lineas(c, id_nota)


# ---------------------------------------------------------------------------
# Cotizaciones — el mismo formulario que una nota, pero sin folio de servicio.
#
# El cliente y el vehículo SÍ se guardan de forma normal en sus tablas (si son
# nuevos, quedan dados de alta) para que al convertir la cotización en nota no
# haya que volver a capturarlos. No aparecen en el dashboard ni en los
# reportes de facturación: no representan trabajo realizado, solo un
# presupuesto que todavía puede no concretarse.
# ---------------------------------------------------------------------------

ESTADOS_COTIZACION = ["Pendiente", "Convertida", "Rechazada"]


def siguiente_id_cotizacion(conexion: sqlite3.Connection) -> str:
    """
    Folio propio, 'COT-001', deliberadamente distinguible de 'N-001': una
    cotización nunca debe confundirse con una nota ya realizada.
    """
    fila = conexion.execute(
        "SELECT MAX(CAST(SUBSTR(id_cotizacion, 5) AS INTEGER)) AS maximo "
        "FROM cotizaciones"
    ).fetchone()
    siguiente = (fila["maximo"] or 0) + 1
    return f"COT-{siguiente:03d}"


def listar_cotizaciones(busqueda: str = "",
                        estado: str | None = None) -> list[dict]:
    """Cotizaciones con el nombre del cliente y los datos del vehículo."""
    condiciones, parametros = [], []
    if estado:
        condiciones.append("co.estado = ?")
        parametros.append(estado)
    filtro = f"WHERE {' AND '.join(condiciones)}" if condiciones else ""

    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT co.*, cl.nombre AS cliente,
                   v.marca, v.modelo, v.anio, v.color,
                   COUNT(i.id_item) AS num_partidas
              FROM cotizaciones co
              JOIN clientes cl ON cl.id_cliente = co.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = co.id_vehiculo
              LEFT JOIN cotizacion_partidas i ON i.id_cotizacion = co.id_cotizacion
              {filtro}
             GROUP BY co.id_cotizacion
             ORDER BY co.fecha DESC, co.id_cotizacion DESC
            """,
            parametros,
        ).fetchall()

    cotizaciones = [dict(f) for f in filas]
    if busqueda:
        cotizaciones = [
            co for co in cotizaciones
            if _coincide(busqueda, co["id_cotizacion"], co["cliente"],
                        co["marca"], co["modelo"], co["color"])
        ]
    return cotizaciones


def obtener_cotizacion(id_cotizacion: str) -> dict | None:
    """Devuelve la cotización con sus renglones en la clave `partidas`."""
    with conectar() as c:
        fila = c.execute(
            """
            SELECT co.*, cl.nombre AS cliente, cl.telefono,
                   v.marca, v.modelo, v.anio, v.color, v.placas
              FROM cotizaciones co
              JOIN clientes cl ON cl.id_cliente = co.id_cliente
              LEFT JOIN vehiculos v ON v.id_vehiculo = co.id_vehiculo
             WHERE co.id_cotizacion = ?
            """,
            (id_cotizacion,),
        ).fetchone()
        if fila is None:
            return None
        partidas = c.execute(
            "SELECT * FROM cotizacion_partidas WHERE id_cotizacion = ? "
            "ORDER BY linea",
            (id_cotizacion,),
        ).fetchall()

    cotizacion = dict(fila)
    cotizacion["partidas"] = [dict(p) for p in partidas]
    return cotizacion


def crear_cotizacion(id_cliente: int, id_vehiculo: int, fecha: str,
                     partidas: list[dict], tasa_iva: float = 0.0) -> str:
    """
    Crea una cotización con todos sus renglones en una sola transacción.

    Misma forma que `crear_nota`, pero escribiendo en `cotizaciones` /
    `cotizacion_partidas` en vez de `notas` / `partidas`, y sin exigir estado
    ni anticipo: una cotización todavía no es un trabajo en curso.
    """
    if not partidas:
        raise ValueError("La cotización necesita al menos una partida.")

    with transaccion() as c:
        id_cotizacion = siguiente_id_cotizacion(c)
        c.execute(
            """
            INSERT INTO cotizaciones (id_cotizacion, id_cliente, id_vehiculo,
                                      fecha, tasa_iva)
            VALUES (?, ?, ?, ?, ?)
            """,
            (id_cotizacion, id_cliente, id_vehiculo, fecha, float(tasa_iva)),
        )

        for linea, p in enumerate(partidas, start=1):
            cantidad = int(p["cantidad"])
            precio = int(p["precio_unitario_centavos"])
            c.execute(
                """
                INSERT INTO cotizacion_partidas
                    (id_cotizacion, linea, id_catalogo, tipo_concepto,
                     categoria, accion, descripcion, posicion, lado,
                     cantidad, precio_unitario_centavos, total_centavos,
                     notas, id_producto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (id_cotizacion, linea, p.get("id_catalogo"), p["tipo_concepto"],
                 p["categoria"], p.get("accion"), p["descripcion"].strip(),
                 p.get("posicion"), p.get("lado"), cantidad, precio,
                 cantidad * precio, (p.get("notas") or "").strip() or None,
                 p.get("id_producto")),
            )

    return id_cotizacion


def rechazar_cotizacion(id_cotizacion: str) -> None:
    """Marca una cotización como rechazada. No se puede deshacer desde aquí."""
    with transaccion() as c:
        fila = c.execute(
            "SELECT estado FROM cotizaciones WHERE id_cotizacion = ?",
            (id_cotizacion,),
        ).fetchone()
        if fila is None:
            raise ValueError(f"No existe la cotización {id_cotizacion}.")
        if fila["estado"] == "Convertida":
            raise ValueError(
                "Esta cotización ya se convirtió en nota; no se puede rechazar."
            )
        c.execute(
            "UPDATE cotizaciones SET estado = 'Rechazada' "
            "WHERE id_cotizacion = ?", (id_cotizacion,))


def actualizar_cotizacion(id_cotizacion: str, id_cliente: int, fecha: str,
                          id_vehiculo: int) -> None:
    """
    Edita la cabecera de una cotización: cliente, fecha y vehículo.

    Solo tiene sentido para una cotización `Pendiente`: una ya `Convertida` es
    historial de que ese presupuesto se aceptó (y su nota ya tiene su propia
    cabecera, independiente), y una `Rechazada` ya se cerró.
    """
    with transaccion() as c:
        fila = c.execute(
            "SELECT estado FROM cotizaciones WHERE id_cotizacion = ?",
            (id_cotizacion,),
        ).fetchone()
        if fila is None:
            raise ValueError(f"No existe la cotización {id_cotizacion}.")
        if fila["estado"] != "Pendiente":
            raise ValueError(
                f"Esta cotización ya está «{fila['estado']}»; solo una "
                f"cotización Pendiente se puede editar."
            )
        c.execute(
            """
            UPDATE cotizaciones
               SET id_cliente = ?, fecha = ?, id_vehiculo = ?
             WHERE id_cotizacion = ?
            """,
            (id_cliente, fecha, id_vehiculo, id_cotizacion),
        )


def siguiente_linea_cotizacion(conexion: sqlite3.Connection,
                               id_cotizacion: str) -> int:
    """Devuelve el siguiente consecutivo de renglón dentro de una cotización."""
    fila = conexion.execute(
        "SELECT COALESCE(MAX(linea), 0) AS maximo FROM cotizacion_partidas "
        "WHERE id_cotizacion = ?",
        (id_cotizacion,),
    ).fetchone()
    return int(fila["maximo"]) + 1


def _renumerar_lineas_cotizacion(conexion: sqlite3.Connection,
                                 id_cotizacion: str) -> None:
    """Igual que `_renumerar_lineas`, pero para `cotizacion_partidas`."""
    conexion.execute(
        "UPDATE cotizacion_partidas SET linea = linea + 100000 "
        "WHERE id_cotizacion = ?", (id_cotizacion,)
    )
    filas = conexion.execute(
        "SELECT id_item FROM cotizacion_partidas WHERE id_cotizacion = ? "
        "ORDER BY linea",
        (id_cotizacion,),
    ).fetchall()
    for numero, fila in enumerate(filas, start=1):
        conexion.execute(
            "UPDATE cotizacion_partidas SET linea = ? WHERE id_item = ?",
            (numero, fila["id_item"]),
        )


def _cotizacion_editable(c: sqlite3.Connection, id_cotizacion: str) -> None:
    """Lanza si la cotización no existe o ya no está Pendiente."""
    fila = c.execute(
        "SELECT estado FROM cotizaciones WHERE id_cotizacion = ?",
        (id_cotizacion,),
    ).fetchone()
    if fila is None:
        raise ValueError(f"No existe la cotización {id_cotizacion}.")
    if fila["estado"] != "Pendiente":
        raise ValueError(
            f"Esta cotización ya está «{fila['estado']}»; solo una "
            f"cotización Pendiente se puede editar."
        )


def agregar_cotizacion_partida(id_cotizacion: str, partida: dict) -> int:
    """Agrega un renglón al final de una cotización existente."""
    with transaccion() as c:
        _cotizacion_editable(c, id_cotizacion)
        linea = siguiente_linea_cotizacion(c, id_cotizacion)
        cantidad = int(partida["cantidad"])
        precio = int(partida["precio_unitario_centavos"])
        cursor = c.execute(
            """
            INSERT INTO cotizacion_partidas
                (id_cotizacion, linea, id_catalogo, tipo_concepto, categoria,
                 accion, descripcion, posicion, lado, cantidad,
                 precio_unitario_centavos, total_centavos, notas, id_producto)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (id_cotizacion, linea, partida.get("id_catalogo"),
             partida["tipo_concepto"], partida["categoria"],
             partida.get("accion"), partida["descripcion"].strip(),
             partida.get("posicion"), partida.get("lado"), cantidad, precio,
             cantidad * precio, (partida.get("notas") or "").strip() or None,
             partida.get("id_producto")),
        )
        return int(cursor.lastrowid)


def actualizar_cotizacion_partida(id_item: int, cantidad: int,
                                  precio_unitario_centavos: int) -> None:
    """Cambia la cantidad o el precio de un renglón de cotización."""
    cantidad = int(cantidad)
    precio = int(precio_unitario_centavos)
    with transaccion() as c:
        fila = c.execute(
            "SELECT id_cotizacion FROM cotizacion_partidas WHERE id_item = ?",
            (id_item,),
        ).fetchone()
        if fila is None:
            raise ValueError("El renglón ya no existe.")
        _cotizacion_editable(c, fila["id_cotizacion"])
        c.execute(
            """
            UPDATE cotizacion_partidas
               SET cantidad = ?, precio_unitario_centavos = ?, total_centavos = ?
             WHERE id_item = ?
            """,
            (cantidad, precio, cantidad * precio, id_item),
        )


def eliminar_cotizacion_partida(id_item: int) -> None:
    """Borra un renglón de cotización y renumera los que quedan."""
    with transaccion() as c:
        fila = c.execute(
            "SELECT id_cotizacion FROM cotizacion_partidas WHERE id_item = ?",
            (id_item,),
        ).fetchone()
        if fila is None:
            raise ValueError("El renglón ya no existe.")
        id_cotizacion = fila["id_cotizacion"]
        _cotizacion_editable(c, id_cotizacion)

        cuantas = c.execute(
            "SELECT COUNT(*) AS n FROM cotizacion_partidas "
            "WHERE id_cotizacion = ?", (id_cotizacion,)
        ).fetchone()["n"]
        if cuantas <= 1:
            raise ValueError(
                "Una cotización no puede quedarse sin renglones. "
                "Si quieres deshacerla, elimina la cotización completa."
            )

        c.execute("DELETE FROM cotizacion_partidas WHERE id_item = ?", (id_item,))
        _renumerar_lineas_cotizacion(c, id_cotizacion)


def eliminar_cotizacion(id_cotizacion: str) -> None:
    """
    Borra una cotización y sus renglones.

    Solo tiene sentido para presupuestos que nunca se concretaron: una
    cotización Convertida es historial de que ese presupuesto sí se aceptó, y
    borrarla perdería esa trazabilidad sin borrar la nota que generó.
    """
    with transaccion() as c:
        fila = c.execute(
            "SELECT estado FROM cotizaciones WHERE id_cotizacion = ?",
            (id_cotizacion,),
        ).fetchone()
        if fila is None:
            raise ValueError(f"No existe la cotización {id_cotizacion}.")
        if fila["estado"] == "Convertida":
            raise ValueError(
                "No se puede borrar una cotización ya convertida en nota."
            )
        c.execute("DELETE FROM cotizaciones WHERE id_cotizacion = ?",
                  (id_cotizacion,))


def convertir_cotizacion_a_nota(id_cotizacion: str,
                                estado_inicial: str = "Recibido",
                                fecha: str | None = None) -> str:
    """
    Convierte una cotización aceptada en una nota real, con folio propio.

    Reusa el cliente, el vehículo, los renglones y la tasa de IVA ya
    capturados —es justo lo que evita volver a teclearlos cuando el cliente
    dice que sí— y dentro de la MISMA transacción marca la cotización como
    Convertida, apuntando al folio resultante.

    `fecha` es la fecha de la NOTA (el día en que el trabajo arranca), no la de
    la cotización original; por omisión es hoy.
    """
    with transaccion() as c:
        fila = c.execute(
            "SELECT * FROM cotizaciones WHERE id_cotizacion = ?",
            (id_cotizacion,),
        ).fetchone()
        if fila is None:
            raise ValueError(f"No existe la cotización {id_cotizacion}.")
        if fila["estado"] != "Pendiente":
            raise ValueError(
                f"Esta cotización ya está «{fila['estado']}»; "
                f"solo una cotización Pendiente se puede convertir."
            )

        partidas = c.execute(
            "SELECT * FROM cotizacion_partidas WHERE id_cotizacion = ? "
            "ORDER BY linea",
            (id_cotizacion,),
        ).fetchall()

        id_nota = siguiente_id_nota(c)
        c.execute(
            """
            INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha,
                               estado, tasa_iva)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (id_nota, fila["id_cliente"], fila["id_vehiculo"],
             fecha or date.today().isoformat(), estado_inicial,
             fila["tasa_iva"]),
        )
        for linea, p in enumerate(partidas, start=1):
            c.execute(
                """
                INSERT INTO partidas (id_nota, linea, id_catalogo, tipo_concepto,
                                      categoria, accion, descripcion, posicion,
                                      lado, cantidad, precio_unitario_centavos,
                                      total_centavos, notas, id_producto)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (id_nota, linea, p["id_catalogo"], p["tipo_concepto"],
                 p["categoria"], p["accion"], p["descripcion"], p["posicion"],
                 p["lado"], p["cantidad"], p["precio_unitario_centavos"],
                 p["total_centavos"], p["notas"], p["id_producto"]),
            )

        c.execute(
            "UPDATE cotizaciones SET estado = 'Convertida', "
            "id_nota_generada = ? WHERE id_cotizacion = ?",
            (id_nota, id_cotizacion),
        )

    return id_nota


# ---------------------------------------------------------------------------
# Consultas del dashboard
#
# Todas aceptan el mismo rango de fechas para que un solo filtro gobierne el
# tablero completo. Los importes se devuelven en centavos.
# ---------------------------------------------------------------------------

def _filtro_fechas(desde: str | None, hasta: str | None,
                   alias: str = "n") -> tuple[str, list]:
    """
    Arma la condición de fecha y sus parámetros.

    `alias` lo fija el código de este módulo, nunca la entrada del usuario;
    los valores de fecha sí van parametrizados con `?`.
    """
    condiciones, parametros = [], []
    if desde:
        condiciones.append(f"{alias}.fecha >= ?")
        parametros.append(desde)
    if hasta:
        condiciones.append(f"{alias}.fecha <= ?")
        parametros.append(hasta)
    return (" AND ".join(condiciones) or "1=1"), parametros


def rango_fechas() -> tuple[str | None, str | None]:
    """Primera y última fecha con notas registradas."""
    with conectar() as c:
        fila = c.execute(
            "SELECT MIN(fecha) AS minimo, MAX(fecha) AS maximo FROM notas"
        ).fetchone()
    return fila["minimo"], fila["maximo"]


def kpis(desde: str | None = None, hasta: str | None = None) -> dict:
    """Indicadores de cabecera del tablero."""
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        fila = c.execute(
            f"""
            SELECT COALESCE(SUM(n.total_centavos), 0) AS ingreso_centavos,
                   COALESCE(SUM(n.pagado_centavos), 0) AS cobrado_centavos,
                   COUNT(*) AS num_notas,
                   COUNT(DISTINCT n.id_cliente) AS clientes_atendidos,
                   COUNT(DISTINCT n.id_vehiculo) AS vehiculos_atendidos,
                   SUM(CASE WHEN n.estado <> 'Entregado' THEN 1 ELSE 0 END)
                       AS notas_abiertas
              FROM notas n
             WHERE {filtro}
            """,
            parametros,
        ).fetchone()

        recurrentes = c.execute(
            f"""
            SELECT COUNT(*) AS n FROM (
                SELECT n.id_cliente
                  FROM notas n
                 WHERE {filtro}
                 GROUP BY n.id_cliente
                HAVING COUNT(*) > 1
            )
            """,
            parametros,
        ).fetchone()["n"]

    num_notas = fila["num_notas"]
    return {
        "ingreso_centavos": fila["ingreso_centavos"],
        "cobrado_centavos": fila["cobrado_centavos"],
        # Lo que el taller tiene por cobrar dentro del rango elegido.
        "por_cobrar_centavos": fila["ingreso_centavos"] - fila["cobrado_centavos"],
        "num_notas": num_notas,
        "notas_abiertas": fila["notas_abiertas"] or 0,
        "clientes_atendidos": fila["clientes_atendidos"],
        "vehiculos_atendidos": fila["vehiculos_atendidos"],
        "clientes_recurrentes": recurrentes,
        "ticket_promedio_centavos": (
            fila["ingreso_centavos"] // num_notas if num_notas else 0
        ),
    }


def ingresos_por_mes(desde: str | None = None, hasta: str | None = None) -> list[dict]:
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT strftime('%Y-%m', n.fecha) AS mes,
                   SUM(n.total_centavos) AS ingreso_centavos,
                   COUNT(*) AS num_notas
              FROM notas n
             WHERE {filtro}
             GROUP BY mes
             ORDER BY mes
            """,
            parametros,
        ).fetchall()
    return [dict(f) for f in filas]


def ingresos_por_categoria(desde: str | None = None,
                           hasta: str | None = None) -> list[dict]:
    """Ingresos agregados por categoría de servicio, desde las partidas."""
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT p.categoria,
                   SUM(p.total_centavos) AS ingreso_centavos,
                   COUNT(*) AS num_partidas
              FROM partidas p
              JOIN notas n ON n.id_nota = p.id_nota
             WHERE {filtro}
             GROUP BY p.categoria
             ORDER BY ingreso_centavos DESC
            """,
            parametros,
        ).fetchall()
    return [dict(f) for f in filas]


def mix_tipo_concepto(desde: str | None = None,
                      hasta: str | None = None) -> list[dict]:
    """Reparto del ingreso entre Producto y Servicio."""
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT p.tipo_concepto,
                   SUM(p.total_centavos) AS ingreso_centavos,
                   COUNT(*) AS num_partidas
              FROM partidas p
              JOIN notas n ON n.id_nota = p.id_nota
             WHERE {filtro}
             GROUP BY p.tipo_concepto
             ORDER BY ingreso_centavos DESC
            """,
            parametros,
        ).fetchall()
    return [dict(f) for f in filas]


def marcas_mas_atendidas(desde: str | None = None, hasta: str | None = None,
                         limite: int = 10) -> list[dict]:
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT v.marca,
                   COUNT(*) AS num_notas,
                   SUM(n.total_centavos) AS ingreso_centavos
              FROM notas n
              JOIN vehiculos v ON v.id_vehiculo = n.id_vehiculo
             WHERE {filtro}
             GROUP BY v.marca
             ORDER BY num_notas DESC, ingreso_centavos DESC
             LIMIT ?
            """,
            [*parametros, limite],
        ).fetchall()
    return [dict(f) for f in filas]


def top_clientes(desde: str | None = None, hasta: str | None = None,
                 limite: int = 10) -> list[dict]:
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT cl.id_cliente, cl.nombre,
                   COUNT(n.id_nota) AS num_notas,
                   SUM(n.total_centavos) AS ingreso_centavos
              FROM notas n
              JOIN clientes cl ON cl.id_cliente = n.id_cliente
             WHERE {filtro}
             GROUP BY cl.id_cliente, cl.nombre
             ORDER BY ingreso_centavos DESC
             LIMIT ?
            """,
            [*parametros, limite],
        ).fetchall()
    return [dict(f) for f in filas]


def ticket_por_marca(desde: str | None = None, hasta: str | None = None,
                     minimo_notas: int = 2) -> list[dict]:
    """
    Ticket promedio por marca.

    Se exige un mínimo de notas porque un promedio sobre una sola nota no dice
    nada y desordenaría la gráfica.
    """
    filtro, parametros = _filtro_fechas(desde, hasta)
    with conectar() as c:
        filas = c.execute(
            f"""
            SELECT v.marca,
                   COUNT(*) AS num_notas,
                   SUM(n.total_centavos) / COUNT(*) AS ticket_centavos
              FROM notas n
              JOIN vehiculos v ON v.id_vehiculo = n.id_vehiculo
             WHERE {filtro}
             GROUP BY v.marca
            HAVING COUNT(*) >= ?
             ORDER BY ticket_centavos DESC
            """,
            [*parametros, minimo_notas],
        ).fetchall()
    return [dict(f) for f in filas]
