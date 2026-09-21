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
db.py                 TODO el SQL del proyecto vive aquí (1,784 líneas, 77 funciones)
auth.py               Hash y verificación de contraseñas
nota_pdf.py           Arma el HTML de la orden/cotización y lo imprime con Chromium
diagnostico_pdf.py    Arma el HTML del reporte de diagnóstico (agrupado por sistema) e imprime igual
exportar.py           Vuelca la base a CSV / Excel / SQL para análisis externo
styles.py             Paleta y hoja de estilo de toda la interfaz, en un solo lugar
esquema.sql           Definición completa: tablas, triggers, índices, CHECKs
paginas/              12 pantallas, una por módulo — cada una importa db.py, nunca escribe SQL
paginas/descargas.py  Envoltorios cacheados de los archivos descargables (ver más abajo)
historico/            Migraciones ya aplicadas; quedan como registro, no se vuelven a correr
pruebas_*.py          3 suites independientes — 268 pruebas en total
```

**Regla de una sola vía:** ninguna pantalla en `paginas/` ejecuta SQL directo.
Todas pasan por funciones de `db.py`. Esto es lo que permite, por ejemplo, que
`verificar_cuadre()` sea una sola función confiable en vez de una suma
recalculada — y ligeramente distinta — en cada pantalla que necesita mostrar
un total.

## El modelo de datos

17 tablas, 8 triggers, 58 restricciones `CHECK`, 20 índices. Las decisiones
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

### Diagnósticos con escáner no maneja dinero ni catálogo

`diagnosticos` / `diagnostico_codigos` capturan el reporte de códigos de
falla (DTC) que hoy se entrega en papel tras conectar el escáner: mismo
cliente y vehículo que una nota, folio propio (`DX-001`), pero sin subtotal,
IVA ni partidas de catálogo — no hay nada que cobrar directamente por leer
los códigos. `sistema` vive como columna en cada código, no como tabla propia
con llave foránea, porque agrupar es lo único que hace (no tiene atributos
propios ni se reutiliza entre diagnósticos); repetir el texto del sistema en
cada renglón es más simple que una tabla intermedia para algo que solo agrupa
filas de una tabla en pantalla y en el PDF. Los códigos y el resumen final se
capturan a mano, igual que en el papel: la app no interpreta el significado
de un DTC ni sugiere reparaciones, solo estructura lo que el técnico lee.

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

El detalle que hace que esto funcione: el documento se arma **autocontenido**
antes de imprimir. El logo ya venía incrustado en base64 desde el diseño, y
`_incrustar_fuentes()` hace lo mismo con las tipografías, que eran lo único
que seguía siendo una ruta relativa (`url('fonts/…')`). Así se puede usar
`set_content` e imprimir sin tocar el disco.

Antes se escribía un archivo temporal *dentro de la carpeta de la plantilla*,
porque era la única forma de que esas rutas relativas resolvieran. Eso exigía
que el directorio del código fuera escribible — imposible en una imagen de
contenedor de solo lectura — y dejaba basura si el proceso moría a medio
imprimir. Como la carpeta `fonts/` nunca llegó a existir, además el PDF
llevaba años saliendo con la tipografía de reserva sin que nadie lo notara.

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

## Pruebas: 268, en tres suites independientes

| Suite | Qué cubre | Cómo |
|---|---|---|
| `pruebas_esquema.py` (43) | Que el esquema garantiza lo que promete: los CHECK, los triggers, las claves foráneas | Base temporal, se descarta al terminar |
| `pruebas_datos.py` (136) | Cada función de `db.py`: alta, edición, borrado en cascada, IVA, cotizaciones, roles de usuario | Base temporal — nunca toca `taller.db` |
| `pruebas_app.py` (89) | Que cada pantalla renderiza sin excepciones, que el candado de sesión funciona, y que interacciones reales (clics, no solo abrir la pantalla) no truenan — incluida la captura completa de un diagnóstico con escáner sobre una base temporal propia | `AppTest`, el harness oficial de Streamlit — ejecuta la app real sin navegador |

Una regla de diseño que costó un bug real aprenderla: **las pruebas de
pantalla no deben comparar contra números fijos** del histórico original. La
primera versión de `pruebas_app.py` esperaba literalmente 58 clientes; en
cuanto el taller empezó a capturar datos reales, esa prueba empezó a fallar
en falso. Ahora compara contra el resultado de `db.listar_clientes()`
calculado en el momento — la prueba verifica la *consistencia* entre pantalla
y base, no una foto fija de un día de agosto.

## Seguridad

- El servidor escucha en toda interfaz de red (`address = "0.0.0.0"` en
  `.streamlit/config.toml`), para entrar desde otros dispositivos en el
  mismo Wi-Fi del taller. Sigue siendo HTTP sin cifrar, así que esto es
  seguro solo dentro de esa red de confianza — nunca debe exponerse hacia
  internet (por ejemplo con port-forwarding en el router), porque el login y
  los datos de clientes viajarían sin cifrar.
- Contraseñas con PBKDF2-HMAC-SHA256, 600,000 iteraciones, salt único por
  usuario — nunca en texto plano, ni siquiera para el administrador.
- El Excel de origen y la base de datos están en `.gitignore`: contienen
  nombres y teléfonos reales de 58 clientes y no deben salir de la
  computadora del taller.
- La base de datos vive **fuera de la carpeta del proyecto**, en un disco
  distinto al del sistema por omisión — una decisión operativa después de
  que el disco del sistema se quedara sin espacio libre a medio guardar una
  nota. `config.py` la vuelve configurable por entorno sin cambiar ese
  comportamiento por omisión.
- **Límite de intentos de acceso persistido** (`intentos_acceso`, tabla),
  no en `session_state`: recargar la página ya no lo reinicia. Se cuenta por
  nombre de usuario tecleado, exista o no —si solo se contaran los reales, el
  tiempo de espera delataría cuáles existen—, y la espera crece exponencial
  en vez de bloquear en seco, para no convertir el límite en una negación de
  servicio contra quien sí tiene la contraseña correcta.
- **Expiración de sesión** por inactividad y por duración absoluta
  (`app.py`, `_sesion_vigente`): cubre la tablet que se queda encendida, no
  robo de credenciales — aquí no hay ningún token que robar.
- El primer administrador nace con una contraseña que no eligió (generada al
  azar, o la que alguien puso en `TALLER_ADMIN_PASSWORD`) y con
  `debe_cambiar_password = 1`: la app no deja pasar a la navegación hasta que
  la cambie.

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
- **El control de versiones del esquema (`migraciones.py`, `PRAGMA
  user_version`) solo automatiza hacia adelante.** Las migraciones v2-v8, que
  ya se aplicaron a la única base que existió, se dejaron manuales a
  propósito: automatizar una reconstrucción de tablas que nunca se va a
  volver a ejecutar es riesgo sin beneficio. Con un equipo de más de una
  persona tocando el esquema seguido, valdría la pena una herramienta como
  Alembic en vez de esto.
