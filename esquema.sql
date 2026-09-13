-- ============================================================================
-- Esquema de la base de datos — Servicio Bautista
--
-- Decisiones de diseño (todas derivadas de la inspección del Paso 0):
--
--  * DINERO EN CENTAVOS (INTEGER). Se verificó que los 246 importes del
--    histórico caben exactos en centavos (máx. 1 decimal). Con enteros la
--    validación "total = cantidad x precio" es EXACTA, sin tolerancias.
--    Nombre explícito `_centavos` para que nadie los confunda con pesos.
--
--  * PKs ORIGINALES CONSERVADAS en clientes y notas. `id_cliente` es el
--    consecutivo de llegada al taller (1..62 con huecos) y `id_nota` mantiene
--    el formato 'N-001'. Reasignarlas rompería la trazabilidad con el papel.
--
--  * `id_partida` REGENERADA. El ID_SA del Excel es un contador global con 23
--    nulos y sin significado de negocio. Se sustituye por AUTOINCREMENT y se
--    añade `linea`, el consecutivo 1..n dentro de cada nota (lo que se imprime).
--
--  * HISTÓRICO INMUTABLE. Las partidas guardan descripción, categoría y precio
--    en duro, no solo el FK al catálogo. Editar un precio del catálogo no
--    puede alterar una nota pasada. `id_catalogo` es NULLABLE: cuando es NULL
--    se trata de un concepto libre (la mano de obra).
--
--  * NOTA: `PRAGMA foreign_keys = ON` NO es persistente; se activa en cada
--    conexión desde db.py. Este archivo solo define la estructura.
-- ============================================================================

-- ---------------------------------------------------------------------------
-- Tablas de referencia: conjuntos cerrados que alimentan los desplegables y
-- los agrupamientos del dashboard. Como FK impiden que un typo ("Suspención")
-- parta las gráficas en dos categorías distintas.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias (
    nombre TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS acciones (
    nombre TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS marcas (
    nombre TEXT PRIMARY KEY
);

-- ---------------------------------------------------------------------------
-- clientes
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS clientes (
    id_cliente INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT NOT NULL,
    -- Texto, nunca número: 16 clientes no tienen teléfono y guardarlo como
    -- número lo convertiría en 5550100001.0 y perdería ceros a la izquierda.
    telefono   TEXT,
    creado_en  TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (length(trim(nombre)) > 0),
    CHECK (telefono IS NULL
           OR (length(telefono) = 10 AND telefono NOT GLOB '*[^0-9]*'))
);

-- ---------------------------------------------------------------------------
-- vehiculos — el carro como entidad propia.
--
-- Antes la marca, el modelo, el año y el color vivían dentro de cada nota,
-- repetidos. Eso hacía imposible la pregunta que más se hace en un taller:
-- "¿qué le hemos hecho a este carro?". Y escondía errores: la misma Saveiro
-- de un cliente aparecía como 2012 en una nota y como 2014 en otra.
--
-- Estos datos NO se copian a la nota: a diferencia de un precio, el año de un
-- carro no cambia con el tiempo. Si dos notas no coinciden es un error de
-- captura, no historia, y corregirlo debe verse en todas.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS vehiculos (
    id_vehiculo INTEGER PRIMARY KEY AUTOINCREMENT,
    -- Obligatorio: un carro siempre llega con dueño. Nunca se da de alta uno
    -- suelto, así que la ficha no existe sin cliente. Quién trajo el carro a
    -- CADA servicio lo guarda la nota, que lleva cliente y vehículo por
    -- separado, de modo que un cambio de dueño no borra el historial.
    id_cliente  INTEGER NOT NULL REFERENCES clientes(id_cliente),
    marca       TEXT NOT NULL REFERENCES marcas(nombre),
    -- En el Excel la columna se llamaba 'Tipo' pero contiene el MODELO
    -- (Patriot, Mazda-3, C-200). TEXT y no INTEGER porque hay modelos
    -- numéricos: el Chrysler 300 de la nota N-026.
    modelo      TEXT,
    anio        INTEGER,
    color       TEXT,
    placas      TEXT,
    vin         TEXT,
    observaciones TEXT,
    activo      INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en   TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (anio IS NULL OR anio BETWEEN 1900 AND 2100)
);

-- ---------------------------------------------------------------------------
-- notas — una por servicio
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS notas (
    id_nota    TEXT PRIMARY KEY,
    id_cliente INTEGER NOT NULL REFERENCES clientes(id_cliente),
    -- El vehículo atendido. Se conserva el cliente además del vehículo porque
    -- un carro puede cambiar de dueño y la nota debe recordar a quién se le
    -- cobró.
    id_vehiculo INTEGER REFERENCES vehiculos(id_vehiculo),
    fecha      TEXT NOT NULL,               -- ISO-8601 'YYYY-MM-DD'

    -- Flujo de trabajo del taller.
    estado     TEXT NOT NULL DEFAULT 'Recibido'
               CHECK (estado IN ('Recibido', 'En proceso', 'Esperando refacción',
                                 'Terminado', 'Entregado')),

    -- Suma de las partidas, mantenida por triggers (ver más abajo).
    subtotal_centavos INTEGER NOT NULL DEFAULT 0
        CHECK (subtotal_centavos >= 0),
    -- Impuesto por nota: 0 = sin IVA. Se guarda la TASA y no el importe para
    -- que el total siempre se pueda recalcular desde las partidas y nunca
    -- quede un impuesto congelado que no corresponda a lo cobrado.
    tasa_iva REAL NOT NULL DEFAULT 0 CHECK (tasa_iva >= 0 AND tasa_iva <= 1),
    -- Total FINAL que paga el cliente: subtotal + IVA. También por triggers.
    total_centavos INTEGER NOT NULL DEFAULT 0 CHECK (total_centavos >= 0),
    -- Cuánto ha pagado el cliente. El saldo se calcula: total - pagado.
    -- No se restringe contra el total en la base porque al crear la nota el
    -- total todavía vale cero: los triggers lo llenan al insertar las
    -- partidas. La aplicación es la que valida que no se pague de más.
    pagado_centavos INTEGER NOT NULL DEFAULT 0 CHECK (pagado_centavos >= 0),

    creado_en  TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (id_nota GLOB 'N-[0-9][0-9][0-9]*'),
    CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]')
);

-- ---------------------------------------------------------------------------
-- cotizaciones — presupuesto antes de que el cliente diga sí.
--
-- Mismo formulario que una nota (cliente, vehículo, renglones, IVA), pero SIN
-- folio de servicio: no es un trabajo realizado, así que no debe contarse en
-- el dashboard ni en los reportes de facturación. El cliente y el vehículo SÍ
-- se guardan de forma normal en sus tablas — si son nuevos, quedan dados de
-- alta — para que al convertirla en nota no haya que volver a capturarlos.
--
-- `id_nota_generada` se llena cuando el cliente acepta y la cotización se
-- convierte en una nota real; a partir de ahí la cotización queda como
-- registro histórico de que ese presupuesto SÍ se concretó.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS cotizaciones (
    id_cotizacion TEXT PRIMARY KEY,          -- 'COT-001', folio propio y
                                              -- distinguible de 'N-001'
    id_cliente    INTEGER NOT NULL REFERENCES clientes(id_cliente),
    id_vehiculo   INTEGER NOT NULL REFERENCES vehiculos(id_vehiculo),
    fecha         TEXT NOT NULL,

    subtotal_centavos INTEGER NOT NULL DEFAULT 0
        CHECK (subtotal_centavos >= 0),
    tasa_iva      REAL NOT NULL DEFAULT 0 CHECK (tasa_iva >= 0 AND tasa_iva <= 1),
    total_centavos INTEGER NOT NULL DEFAULT 0 CHECK (total_centavos >= 0),

    estado        TEXT NOT NULL DEFAULT 'Pendiente'
                  CHECK (estado IN ('Pendiente', 'Convertida', 'Rechazada')),
    -- NULL hasta que se convierte; a partir de ahí guarda el folio resultante.
    id_nota_generada TEXT REFERENCES notas(id_nota),

    creado_en     TEXT NOT NULL DEFAULT (datetime('now')),

    CHECK (id_cotizacion GLOB 'COT-[0-9][0-9][0-9]*'),
    CHECK (fecha GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    -- Solo una cotización Convertida puede (y debe) traer su folio resultante.
    CHECK ((estado = 'Convertida') = (id_nota_generada IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS cotizacion_partidas (
    id_item       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_cotizacion TEXT NOT NULL REFERENCES cotizaciones(id_cotizacion)
                      ON DELETE CASCADE ON UPDATE CASCADE,
    linea         INTEGER NOT NULL CHECK (linea > 0),
    id_catalogo   INTEGER REFERENCES catalogo(id_catalogo),
    id_producto   TEXT REFERENCES productos(id_producto),

    tipo_concepto TEXT NOT NULL CHECK (tipo_concepto IN ('Producto', 'Servicio')),
    categoria     TEXT NOT NULL REFERENCES categorias(nombre),
    accion        TEXT REFERENCES acciones(nombre),
    descripcion   TEXT NOT NULL,
    posicion      TEXT CHECK (posicion IS NULL OR posicion IN ('Anterior', 'Posterior')),
    lado          TEXT CHECK (lado IS NULL OR lado IN ('Derecho', 'Izquierdo', 'Par', 'Centro')),

    cantidad      INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario_centavos INTEGER NOT NULL CHECK (precio_unitario_centavos >= 0),
    total_centavos           INTEGER NOT NULL,
    notas         TEXT,

    UNIQUE (id_cotizacion, linea),
    CHECK (total_centavos = cantidad * precio_unitario_centavos),
    CHECK ((tipo_concepto = 'Servicio' AND accion IS NOT NULL)
        OR (tipo_concepto = 'Producto' AND accion IS NULL))
);

-- Mismo mecanismo que en notas/partidas: el subtotal y el total de la
-- cotización se recalculan enteros desde sus renglones, nunca sumando
-- diferencias.
CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_insert
AFTER INSERT ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = NEW.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = NEW.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = NEW.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_delete
AFTER DELETE ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = OLD.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = OLD.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = OLD.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = OLD.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizacion_partidas_update
AFTER UPDATE ON cotizacion_partidas
BEGIN
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = OLD.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = OLD.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = OLD.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = OLD.id_cotizacion;
    UPDATE cotizaciones
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM cotizacion_partidas
                                 WHERE id_cotizacion = NEW.id_cotizacion),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM cotizacion_partidas
                              WHERE id_cotizacion = NEW.id_cotizacion)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM cotizacion_partidas
                                         WHERE id_cotizacion = NEW.id_cotizacion)
                                       * tasa_iva) AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

CREATE TRIGGER IF NOT EXISTS trg_cotizaciones_iva
AFTER UPDATE OF tasa_iva ON cotizaciones
BEGIN
    UPDATE cotizaciones
       SET total_centavos = NEW.subtotal_centavos
                          + CAST(ROUND(NEW.subtotal_centavos * NEW.tasa_iva)
                                 AS INTEGER)
     WHERE id_cotizacion = NEW.id_cotizacion;
END;

-- ---------------------------------------------------------------------------
-- taller — datos del negocio, una sola fila.
--
-- Los usa la nota impresa. Antes el nombre estaba escrito en el código y no
-- había dónde poner dirección, teléfono ni RFC, que una nota real necesita.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS taller (
    id        INTEGER PRIMARY KEY CHECK (id = 1),
    nombre    TEXT NOT NULL,
    subtitulo TEXT,
    direccion TEXT,
    telefono  TEXT,
    correo    TEXT,
    rfc       TEXT,
    -- Línea de servicios del membrete impreso.
    especialidades TEXT,
    -- Ruta al archivo del logo, relativa a la raíz del proyecto.
    logo      TEXT,
    pie_nota  TEXT,
    actualizado_en TEXT
);

-- ---------------------------------------------------------------------------
-- catalogo — derivado del histórico, editable desde la app.
--
-- Llave natural (descripcion, tipo_concepto): se verificó que con esa llave
-- NINGÚN concepto cruza categorías. 'Balero', 'Gasolina' y 'Rotula' existen
-- como Producto y como Servicio porque son cosas distintas (la refacción vs.
-- la mano de obra de instalarla), y esta llave las separa correctamente.
--
-- La mano de obra NO vive aquí: cruza 8 categorías con precios de 150 a 8,490,
-- así que se captura como concepto libre con precio manual en cada nota.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS catalogo (
    id_catalogo   INTEGER PRIMARY KEY AUTOINCREMENT,
    descripcion   TEXT NOT NULL,
    tipo_concepto TEXT NOT NULL CHECK (tipo_concepto IN ('Producto', 'Servicio')),
    categoria     TEXT NOT NULL REFERENCES categorias(nombre),
    precio_actual_centavos INTEGER NOT NULL CHECK (precio_actual_centavos >= 0),
    activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en     TEXT NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT,

    UNIQUE (descripcion, tipo_concepto),
    CHECK (length(trim(descripcion)) > 0)
);

-- ---------------------------------------------------------------------------
-- Catálogo de productos — lo que el taller compra y vende físicamente.
--
-- Convive con `catalogo` y NO lo reemplaza: aquel guarda los conceptos
-- cobrables, entre ellos ~30 servicios (Alineación, Afinación, Rectificados,
-- Mano de obra) que son el grueso de la facturación y no son artículos de
-- almacén.
--
-- Lo mismo con las categorías, que son dos ejes distintos:
--   `categorias`           → sistema del carro (Suspensión, Motor, Frenos)
--   `categorias_producto`  → tipo de producto (Aceites, Pintura, Lubricantes)
-- Un cambio de aceite es producto «Aceites» y sistema «Motor» a la vez.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS categorias_producto (
    id_cat TEXT PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    CHECK (id_cat GLOB 'C-[0-9][0-9]')
);

-- Marca del producto en su propia tabla, igual que las marcas de vehículo:
-- como texto libre acabarías con «Wurth» y «Würth» como dos proveedores.
CREATE TABLE IF NOT EXISTS marcas_producto (
    nombre TEXT PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS productos (
    id_producto  TEXT PRIMARY KEY,
    id_cat       TEXT NOT NULL REFERENCES categorias_producto(id_cat),
    nombre       TEXT NOT NULL,
    unidad       TEXT,                       -- ml, L, pza…
    presentacion TEXT,                       -- Aerosol, Galón, Botella…
    contenido    REAL,                       -- 500 (ml), 3.7 (L)…
    marca        TEXT REFERENCES marcas_producto(nombre),

    precio_compra_centavos INTEGER,
    precio_venta_centavos  INTEGER,

    -- Sin existencias, un mínimo no puede disparar ninguna alerta.
    stock_actual REAL NOT NULL DEFAULT 0,
    stock_min    REAL NOT NULL DEFAULT 0,

    activo       INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en    TEXT NOT NULL DEFAULT (datetime('now')),
    actualizado_en TEXT,

    CHECK (length(trim(nombre)) > 0),
    CHECK (precio_compra_centavos IS NULL OR precio_compra_centavos >= 0),
    CHECK (precio_venta_centavos IS NULL OR precio_venta_centavos >= 0),
    CHECK (stock_actual >= 0 AND stock_min >= 0)
);

-- ---------------------------------------------------------------------------
-- partidas — los renglones de cada nota
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS partidas (
    id_partida INTEGER PRIMARY KEY AUTOINCREMENT,
    id_nota    TEXT NOT NULL REFERENCES notas(id_nota)
                   ON DELETE CASCADE ON UPDATE CASCADE,
    -- Consecutivo dentro de la nota (1, 2, 3...), el que se imprime.
    linea      INTEGER NOT NULL CHECK (linea > 0),
    -- NULL = concepto libre (mano de obra). No se borra en cascada a propósito:
    -- desactivar un concepto del catálogo no debe tocar el histórico.
    id_catalogo INTEGER REFERENCES catalogo(id_catalogo),

    tipo_concepto TEXT NOT NULL CHECK (tipo_concepto IN ('Producto', 'Servicio')),
    categoria   TEXT NOT NULL REFERENCES categorias(nombre),
    accion      TEXT REFERENCES acciones(nombre),
    descripcion TEXT NOT NULL,
    posicion    TEXT CHECK (posicion IS NULL OR posicion IN ('Anterior', 'Posterior')),
    lado        TEXT CHECK (lado IS NULL OR lado IN ('Derecho', 'Izquierdo', 'Par', 'Centro')),

    cantidad    INTEGER NOT NULL CHECK (cantidad > 0),
    precio_unitario_centavos INTEGER NOT NULL CHECK (precio_unitario_centavos >= 0),
    total_centavos           INTEGER NOT NULL,
    -- Observación libre del renglón; es la columna «Notas» de la hoja TSA.
    notas       TEXT,
    -- Si el renglón salió del almacén, de qué producto y cuánto costó ENTONCES.
    -- El costo se copia porque el precio de compra cambia con el tiempo:
    -- recalcular el margen de una nota vieja con el costo de hoy daría un
    -- número falso.
    id_producto TEXT REFERENCES productos(id_producto),
    costo_unitario_centavos INTEGER
        CHECK (costo_unitario_centavos IS NULL OR costo_unitario_centavos >= 0),

    UNIQUE (id_nota, linea),

    -- Exacto gracias a la aritmética entera: sin tolerancias de punto flotante.
    CHECK (total_centavos = cantidad * precio_unitario_centavos),

    -- Regla de negocio verificada en las 246 filas del histórico, sin una sola
    -- excepción: un Servicio SIEMPRE lleva acción, un Producto NUNCA.
    CHECK ((tipo_concepto = 'Servicio' AND accion IS NOT NULL)
        OR (tipo_concepto = 'Producto' AND accion IS NULL))
);

-- ---------------------------------------------------------------------------
-- usuarios — autenticación. Contraseñas con PBKDF2-HMAC-SHA256 + salt único.
-- Se guarda el número de iteraciones por fila para poder subirlo en el futuro
-- sin invalidar las contraseñas ya existentes.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario    INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario       TEXT NOT NULL UNIQUE,
    hash_password TEXT NOT NULL,          -- hex del derivado PBKDF2
    salt          TEXT NOT NULL,          -- hex, único por usuario
    iteraciones   INTEGER NOT NULL,
    rol           TEXT NOT NULL CHECK (rol IN ('admin', 'operador')),
    activo        INTEGER NOT NULL DEFAULT 1 CHECK (activo IN (0, 1)),
    creado_en     TEXT NOT NULL DEFAULT (datetime('now')),
    ultimo_acceso TEXT,

    CHECK (length(trim(usuario)) > 0)
);

-- ---------------------------------------------------------------------------
-- Triggers: mantienen notas.total_centavos igual a la suma de sus partidas.
--
-- Se hace en la base y no en la app para que la igualdad que la especificación
-- exige como obligatoria no pueda desincronizarse nunca, ni siquiera si
-- alguien modifica la base por fuera de Streamlit.
-- ---------------------------------------------------------------------------
-- Los triggers mantienen DOS columnas: el subtotal, que es la suma de las
-- partidas, y el total final, que le suma el IVA de la nota. Se recalculan
-- enteros desde las partidas en vez de sumar diferencias, para que ningún
-- error de redondeo se vaya acumulando con el tiempo.
CREATE TRIGGER IF NOT EXISTS trg_partidas_insert
AFTER INSERT ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = NEW.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = NEW.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = NEW.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;

CREATE TRIGGER IF NOT EXISTS trg_partidas_delete
AFTER DELETE ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = OLD.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = OLD.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = OLD.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = OLD.id_nota;
END;

-- En el UPDATE se recalculan ambas notas: la partida pudo cambiar de nota.
CREATE TRIGGER IF NOT EXISTS trg_partidas_update
AFTER UPDATE ON partidas
BEGIN
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = OLD.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = OLD.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = OLD.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = OLD.id_nota;
    UPDATE notas
       SET subtotal_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                                  FROM partidas WHERE id_nota = NEW.id_nota),
           total_centavos = (SELECT COALESCE(SUM(total_centavos), 0)
                               FROM partidas WHERE id_nota = NEW.id_nota)
                          + CAST(ROUND((SELECT COALESCE(SUM(total_centavos), 0)
                                          FROM partidas
                                         WHERE id_nota = NEW.id_nota)
                                       * tasa_iva) AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;

-- Cambiar la tasa también tiene que recalcular el total. SQLite no encadena
-- triggers por omisión, así que esta actualización sobre `notas` no se
-- dispara a sí misma.
CREATE TRIGGER IF NOT EXISTS trg_notas_iva
AFTER UPDATE OF tasa_iva ON notas
BEGIN
    UPDATE notas
       SET total_centavos = NEW.subtotal_centavos
                          + CAST(ROUND(NEW.subtotal_centavos * NEW.tasa_iva)
                                 AS INTEGER)
     WHERE id_nota = NEW.id_nota;
END;

-- ---------------------------------------------------------------------------
-- Índices para las consultas del dashboard y las búsquedas de la app.
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_notas_cliente     ON notas(id_cliente);
CREATE INDEX IF NOT EXISTS idx_notas_vehiculo    ON notas(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_notas_fecha       ON notas(fecha);
CREATE INDEX IF NOT EXISTS idx_notas_estado      ON notas(estado);
CREATE INDEX IF NOT EXISTS idx_vehiculos_cliente ON vehiculos(id_cliente);
CREATE INDEX IF NOT EXISTS idx_partidas_nota     ON partidas(id_nota);
CREATE INDEX IF NOT EXISTS idx_partidas_categoria ON partidas(categoria);
CREATE INDEX IF NOT EXISTS idx_partidas_tipo     ON partidas(tipo_concepto);
CREATE INDEX IF NOT EXISTS idx_catalogo_activo   ON catalogo(activo);
CREATE INDEX IF NOT EXISTS idx_productos_cat     ON productos(id_cat);
CREATE INDEX IF NOT EXISTS idx_productos_activo  ON productos(activo);
CREATE INDEX IF NOT EXISTS idx_vehiculos_placas  ON vehiculos(placas);
CREATE INDEX IF NOT EXISTS idx_clientes_nombre   ON clientes(nombre);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_cliente  ON cotizaciones(id_cliente);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_vehiculo ON cotizaciones(id_vehiculo);
CREATE INDEX IF NOT EXISTS idx_cotizaciones_estado   ON cotizaciones(estado);
CREATE INDEX IF NOT EXISTS idx_cotizacion_partidas_cot
    ON cotizacion_partidas(id_cotizacion);
