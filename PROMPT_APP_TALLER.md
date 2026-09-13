# Construcción de app de administración — Servicio Bautista

## Objetivo

Construir una aplicación en **Streamlit** para administrar mi taller automotriz, usando como
base los datos históricos del archivo de Excel `1_MySQL_AutoSB.xlsx`.

**Carpeta de trabajo:** `C:\Users\Kevin Bautista\Desktop\AppClaude`

Todo el proyecto vive ahí: el Excel de origen, el código, la base de datos y los scripts.
No crees ni modifiques archivos fuera de esa carpeta. En las rutas dentro del código usa
rutas relativas a la raíz del proyecto (con `pathlib`), no rutas absolutas de Windows, para
que el proyecto siga funcionando si lo muevo o lo subo a un repositorio.

## Paso 0 — Explora antes de escribir código

Antes de crear nada, escribe un script de inspección con pandas y muéstrame la salida:
hojas, dimensiones, tipos de dato, nulos por columna y valores únicos de las columnas
categóricas. No asumas la estructura, verifícala.

## Estructura real del archivo (ya verificada, respétala)

**Ojo: la hoja `TC_TA` contiene DOS tablas lado a lado**, separadas por una columna vacía.
Leerla como una sola tabla es un error.

### Tabla 1 — Clientes (hoja `TC_TA`, columnas A–C, 58 registros)
| Columna | Notas |
|---|---|
| `ID_Cliente (PK)` | entero, va de 1 a 62 con huecos |
| `Nombre` | sin nulos |
| `Telefono` | 16 nulos; pandas lo lee como float, debe guardarse como **texto** |

### Tabla 2 — Notas de servicio (hoja `TC_TA`, columnas E–L, 62 registros)
| Columna | Notas |
|---|---|
| `ID_N (PK)` | texto con formato `N-001` |
| `ID_Cliente (FK)` | → Clientes; sin huérfanos |
| `Fecha` | rango 2024-01-21 a 2025-12-14 |
| `Marca` | 16 marcas distintas |
| `Año` | año del vehículo |
| `Tipo` | **en realidad es el MODELO del vehículo** (Patriot, Mazda-3, C-200). Renómbrala a `Modelo` en la base de datos |
| `Color` | |
| `TOTAL` | total de la nota |

### Tabla 3 — Partidas de servicio (hoja `TSA`, 245 registros)
| Columna | Notas |
|---|---|
| `ID_SA (PK)` | **23 valores nulos** — regenera la PK como entero autoincremental |
| `ID_N (FK)` | → Notas; sin huérfanos, las 62 notas tienen partidas |
| `Tipo De concepto` | `Producto` (143) / `Servicio` (102), 1 nulo |
| `Categoría` | 11 valores: Suspensión, Dirección, Motor, Llantas y rines, Transmisión, Chasis, Frenos, General, Combustible, Escape, Eléctrico |
| `Acción` | 10 valores, 144 nulos (normal: los Productos no llevan acción) |
| `Descripción` | 89 descripciones únicas |
| `Posición` | Anterior / Posterior, 53 nulos |
| `Lado` | Derecho / Izquierdo / Par / Centro, 63 nulos |
| `Cantidad`, `Precio unitario`, `Total` | |
| `Notas` | 245 de 246 nulos, prácticamente vacía |

### Regla de validación obligatoria
La suma de `Total` en TSA es **381,146.50** y coincide exactamente con la suma de `TOTAL`
en Notas. Después de migrar los datos, verifica esa igualdad y avísame si no cuadra.
Además, el `TOTAL` de cada nota individual debe ser igual a la suma de sus partidas.

## Arquitectura

- **Base de datos: SQLite** (`taller.db`), no el Excel. El Excel es la carga inicial y nada más;
  la app nunca lo escribe. Motivo: necesito escrituras concurrentes, integridad referencial y
  transacciones, y quiero poder migrar a MySQL después sin rehacer la app.
- **Script de carga separado** (`cargar_datos.py`), idempotente: se puede correr de nuevo sin
  duplicar registros. Que sea un archivo aparte de la app, no código dentro de `app.py`.
- **Esquema normalizado** con PKs, FKs declaradas y `PRAGMA foreign_keys = ON`.
- Capa de acceso a datos en su propio módulo (`db.py`), separada de la interfaz. Nada de
  SQL suelto entre widgets de Streamlit.
- **SQL parametrizado siempre** (`?`), nunca concatenación de strings.

## Tablas nuevas que hay que crear

**`usuarios`** — para el login: usuario, hash de contraseña, rol, fecha de creación.
Contraseñas con hash + salt (usa `bcrypt` o `hashlib.pbkdf2_hmac`), jamás en texto plano.
Crea un usuario administrador inicial y dime cuáles son las credenciales.

**`catalogo`** — el archivo NO trae catálogo, hay que derivarlo. Extrae las 89 descripciones
únicas de TSA con su `Tipo De concepto`, `Categoría` y el precio unitario más reciente
observado. Añade columnas `precio_actual` y `activo`. Esta tabla es editable desde la app,
independiente del histórico: cambiar un precio en el catálogo no debe alterar notas pasadas.

## Pantallas

1. **Inicio de sesión** — pantalla previa; nada del resto de la app es accesible sin
   autenticarse. Sesión persistente con `st.session_state` y botón de cerrar sesión.

2. **Dashboard** — visualizaciones derivadas de lo que los datos realmente permiten:
   - Ingresos por mes (serie de tiempo, hay 2 años de historia)
   - KPIs: ingreso total, número de notas, ticket promedio, clientes atendidos
   - Ingresos por categoría de servicio (Suspensión y Dirección dominan, se va a notar)
   - Mix Producto vs Servicio
   - Marcas de vehículo más atendidas
   - Top clientes por facturación y clientes recurrentes
   - Filtro por rango de fechas que afecte a todo el tablero

3. **Registro de cliente** — alta con validación: nombre obligatorio, teléfono opcional
   (16 clientes históricos no lo tienen) y guardado como texto. Advierte si el nombre ya
   existe. Debe incluir también búsqueda y edición de clientes existentes.

4. **Catálogo** — alta, edición, búsqueda y activar/desactivar productos y servicios,
   con filtros por tipo y categoría.

5. **Notas de servicio** — crear una nota nueva: seleccionar cliente, capturar datos del
   vehículo, agregar partidas desde el catálogo (con posición y lado cuando aplique) y que
   el total se calcule solo a partir de las partidas. Consultar notas existentes con su detalle.

## Scripts de análisis

Carpeta `analisis/` con scripts de Python independientes de la app: estacionalidad de la
demanda, categorías más rentables, frecuencia de retorno de clientes y análisis del ticket
promedio por marca. Que guarden sus salidas en `analisis/salidas/`.

## Cómo quiero que trabajes

- Explícame las decisiones de diseño de base de datos antes de implementarlas.
- Construye por etapas y verifica cada una antes de seguir: esquema → carga y validación →
  login → CRUD → dashboard. No escribas la app completa de un tirón.
- `requirements.txt` y un `README.md` con las instrucciones para correrla.
- Comentarios en español.
- Al terminar, corre la app y confirma que levanta sin errores.
