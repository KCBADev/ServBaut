# Arquitectura — Servicio Bautista

Documento técnico para quien quiera entender **cómo** está construida la
aplicación y, sobre todo, **por qué** — las decisiones de diseño que no son
obvias con solo leer el código. El `README.md` explica cómo instalarla y
usarla; este documento explica cómo razona por dentro.

## Contexto del problema

Un taller mecánico llevaba 62 notas de servicio y 58 clientes en una hoja de
Excel. El encargo: una aplicación para digitalizar esa operación — capturar
clientes, vehículos y notas de servicio, cobrar con IVA, imprimir la orden de
trabajo y ver un tablero de negocio — sin perder ni un peso del histórico
($381,146.50 exactos) ni la trazabilidad de las notas en papel.

Es una aplicación de un solo usuario administrador, en una sola computadora,
sin necesidad de servidor remoto ni de soportar escrituras concurrentes de
verdad. Varias decisiones de abajo solo tienen sentido en ese contexto.

## Stack y por qué

| Pieza | Elección | Por qué |
|---|---|---|
| Interfaz | **Streamlit** | Formularios, tablas y estado de sesión listos de fábrica; para una app interna de un solo usuario, escribir un frontend a mano no pagaba su costo. |
| Base de datos | **SQLite** (`sqlite3`, estándar de Python) | Un solo archivo, sin servidor que administrar, con triggers y `CHECK` de verdad. Correcto para un taller con una computadora; no lo sería para varias sucursales escribiendo a la vez. |
| Gráficas | **Altair** | Declarativo, se integra nativo con Streamlit y exporta a PNG para los reportes fuera de la app. |
| PDF | **Chromium vía Playwright** | Ver la sección dedicada abajo — es la decisión menos obvia del proyecto. |
| Contraseñas | **PBKDF2-HMAC-SHA256**, 600,000 iteraciones, salt único | Librería estándar de Python, sin compilar nada en Windows (a diferencia de bcrypt/argon2). |
| Datos de origen | **pandas + openpyxl** | Solo para la carga inicial desde el Excel; la app nunca vuelve a tocarlo. |

## Estructura del código

```
app.py                Login y navegación — el único punto de entrada
db.py                 TODO el SQL del proyecto vive aquí (1,596 líneas, 70 funciones)
auth.py               Hash y verificación de contraseñas
nota_pdf.py           Arma el HTML de la orden/cotización y lo imprime con Chromium
exportar.py           Vuelca la base a CSV / Excel / SQL para análisis externo
styles.py             Paleta y hoja de estilo de toda la interfaz, en un solo lugar
esquema.sql           Definición completa: tablas, triggers, índices, CHECKs
paginas/              11 pantallas, una por módulo — cada una importa db.py, nunca escribe SQL
paginas/descargas.py  Envoltorios cacheados de los archivos descargables (ver más abajo)
historico/            Migraciones ya aplicadas; quedan como registro, no se vuelven a correr
pruebas_*.py          3 suites independientes — 226 pruebas en total
```

**Regla de una sola vía:** ninguna pantalla en `paginas/` ejecuta SQL directo.
Todas pasan por funciones de `db.py`. Esto es lo que permite, por ejemplo, que
`verificar_cuadre()` sea una sola función confiable en vez de una suma
recalculada — y ligeramente distinta — en cada pantalla que necesita mostrar
un total.

## El modelo de datos

15 tablas, 8 triggers, 49 restricciones `CHECK`, 17 índices. Las decisiones
que valen la pena explicar:

### El dinero se guarda en centavos, como entero

`notas.total_centavos`, no `notas.total`. La especificación exigía que el
histórico sumara **exactamente** $381,146.50, y la suma de números en punto
flotante se desvía (`0.1 + 0.2` no es exactamente `0.3` en ningún lenguaje).
Con enteros la aritmética es exacta y un `CHECK` que exige
`total_centavos = cantidad * precio_unitario_centavos` no necesita margen de
tolerancia. `db.py` es la única frontera donde se cruza entre pesos y
centavos — `pesos_a_centavos`, `centavos_a_pesos`, `formato_pesos` — así que
ninguna pantalla hace esa conversión por su cuenta.

### Los totales los mantienen triggers, no la aplicación

`trg_partidas_insert`, `_delete` y `_update` recalculan `notas.subtotal_centavos`
y `notas.total_centavos` cada vez que una partida cambia — directo en SQLite,
no en Python. La consecuencia práctica: esa igualdad no puede desincronizarse
ni aunque alguien edite la base por fuera de Streamlit (con DB Browser, por
ejemplo). El mismo patrón se repite para `cotizaciones` / `cotizacion_partidas`,
con su propio juego de triggers — están deliberadamente duplicados en vez de
compartidos, ver más abajo.

### El historial es inmutable

Cada partida guarda **su propia copia** de la descripción, la categoría y el
precio con que se cobró, además de una referencia opcional al catálogo
(`id_catalogo`). Cambiar el precio de un concepto en el catálogo mañana no
altera ni un peso de una nota ya cobrada hoy — hay una prueba dedicada a
verificar justo eso.

### Cotizaciones vive en tablas separadas de notas

Una cotización (presupuesto) usa `cotizaciones` / `cotizacion_partidas`, no
una nota con una bandera `es_cotizacion`. La razón: con una bandera, un
`WHERE` olvidado en cualquier reporte futuro dejaría que un presupuesto —
trabajo que nunca se hizo — se colara en los ingresos del tablero. Con tablas
separadas es estructuralmente imposible. El cliente y el vehículo sí se
guardan en sus tablas normales de inmediato, que es lo que permite que, al
convertir la cotización en nota, ya estén ahí sin volver a capturarlos.

### Un CHECK codifica una regla real del negocio

Un `CHECK` obliga a que un concepto tipo *Servicio* siempre lleve una acción
(Cambio, Reparación…) y uno tipo *Producto* nunca. Se verificó contra las 246
filas del histórico original sin una sola excepción antes de agregarlo — no
es una regla inventada, es la que el taller ya seguía en papel.

### Las llaves primarias del papel se conservan

`id_cliente` sigue el consecutivo de llegada al taller y `id_nota` mantiene el
formato `N-001`. Reasignarlas habría roto la trazabilidad con las notas
físicas que el taller todavía archiva. La única que se regenera es la de
`partidas`: el identificador del Excel original era un contador global con 23
valores nulos y sin significado real.

## El PDF: por qué Chromium y no una librería de Python

El taller ya tenía un diseño de orden de trabajo hecho en HTML/CSS —
tipografía, colores, cuadrícula de dos columnas, franjas de color — y lo
pidieron igual, no parecido. Ninguna librería de PDF en Python (fpdf2,
reportlab) interpreta flexbox, grid, `@page` ni `@font-face`; son intérpretes
de HTML del año 2005, no navegadores.

La solución: `nota_pdf.py` rellena la plantilla HTML con los datos de la nota
(con escapado obligatorio en todo dato dinámico — un cliente con `<` o `&` en
el nombre no debe poder romper la maquetación) y la imprime con **Chromium
sin cabeza, vía Playwright**. El mismo motor de renderizado que usa cualquier
navegador moderno, así que el PDF sale idéntico al diseño aprobado, sin
reinterpretarlo a mano.

El detalle que hace que esto funcione: el HTML relleno se escribe en un
archivo temporal *dentro de la carpeta de la plantilla* y se abre como
archivo local, no con una inyección directa de HTML en memoria — es la única
forma de que las rutas relativas a las tipografías resuelvan correctamente.

Costo asumido conscientemente: unos 150 MB de navegador y 1-2 segundos por
PDF, en vez de milisegundos. Para imprimir una orden a la vez es irrelevante;
se notaría generando cientos en lote.

## Rendimiento: por qué existe `paginas/descargas.py`

Los botones de descarga de Streamlit evalúan su contenido en **cada**
reejecución del script, se haga clic en ellos o no. La pantalla de "nota
guardada" tenía cuatro: el PDF (que levanta Chromium) y tres exportes de la
base completa a CSV/Excel/SQL. Medido: **2.9 segundos por cada vez que esa
pantalla se dibujaba**, aunque nadie descargara nada — y ese costo crece con
cada nota nueva, porque los exportes vuelcan la base entera.

`paginas/descargas.py` envuelve cada uno con la caché de datos de Streamlit,
usando la fecha de última escritura del archivo de la base como llave de
invalidación: el número cambia con cada INSERT, UPDATE o DELETE, así que en
cuanto se guarda, edita o borra algo, lo cacheado se invalida solo — un PDF
nunca puede salir con datos viejos, sin necesidad de limpiar la caché a mano.

## Pruebas: 226, en tres suites independientes

| Suite | Qué cubre | Cómo |
|---|---|---|
| `pruebas_esquema.py` (37) | Que el esquema garantiza lo que promete: los CHECK, los triggers, las claves foráneas | Base temporal, se descarta al terminar |
| `pruebas_datos.py` (122) | Cada función de `db.py`: alta, edición, borrado en cascada, IVA, cotizaciones, roles de usuario | Base temporal — nunca toca `taller.db` |
| `pruebas_app.py` (67) | Que cada pantalla renderiza sin excepciones y que el candado de sesión funciona | `AppTest`, el harness oficial de Streamlit — ejecuta la app real sin navegador |

Una regla de diseño que costó un bug real aprenderla: **las pruebas de
pantalla no deben comparar contra números fijos** del histórico original. La
primera versión de `pruebas_app.py` esperaba literalmente 58 clientes; en
cuanto el taller empezó a capturar datos reales, esa prueba empezó a fallar
en falso. Ahora compara contra el resultado de `db.listar_clientes()`
calculado en el momento — la prueba verifica la *consistencia* entre pantalla
y base, no una foto fija de un día de agosto.

## Seguridad

- El servidor está atado a `localhost` (`.streamlit/config.toml`); sin eso,
  Streamlit escucha en todas las interfaces de red y el taller quedaría
  accesible desde fuera, con datos de clientes detrás de un login sobre HTTP
  sin cifrar.
- Contraseñas con PBKDF2-HMAC-SHA256, 600,000 iteraciones, salt único por
  usuario — nunca en texto plano, ni siquiera para el administrador.
- El Excel de origen y la base de datos están en `.gitignore`: contienen
  nombres y teléfonos reales de 58 clientes y no deben salir de la
  computadora del taller.
- La base de datos vive **fuera de la carpeta del proyecto**, en un disco
  distinto al del sistema — una decisión operativa después de que el disco
  del sistema se quedara sin espacio libre a medio guardar una nota.

## Decisiones que tomaría distinto a mayor escala

Ser explícito sobre los límites de un diseño es parte del diseño:

- **SQLite asume una sola computadora escribiendo.** Funciona porque el
  taller tiene una sola caja registradora, en el sentido literal. Con más de
  una sucursal, la base tendría que migrar a un servidor (Postgres/MySQL) con
  escrituras concurrentes de verdad.
- **Los triggers de cotizaciones duplican los de notas** en vez de compartir
  lógica, porque SQLite no tiene triggers parametrizables. Con una tercera
  tabla de este tipo, valdría la pena revisar si conviene otra forma de
  organizarlo.
- **No hay control de versiones del esquema** más allá de los scripts en
  `historico/` corridos a mano. Con un equipo de más de una persona, eso
  necesitaría una herramienta como Alembic.
