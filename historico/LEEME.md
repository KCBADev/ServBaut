# Migraciones ya aplicadas

Estos ocho guiones llevaron la base de su forma original a la actual. **Todos
están aplicados**; la base en `D:\TallerBautista\taller.db` ya pasó por los
ocho. Se conservan solo como registro de cómo evolucionó el esquema.

| Guion | Qué introdujo |
|---|---|
| `migrar.py` | saca los datos del vehículo de `notas` a la tabla `vehiculos` (el mismo carro repetido en varias notas queda como una ficha con historial) y añade a `notas` el estado del trabajo y lo pagado |
| `migrar_v3.py` | el dueño del vehículo pasa a ser opcional |
| `migrar_v4.py` | catálogo de productos e inventario, con su propia taxonomía, aparte del catálogo de conceptos cobrables |
| `migrar_v5.py` | IVA (`subtotal_centavos` y `tasa_iva`), dueño obligatorio otra vez, y membrete |
| `migrar_v6.py` | cotizaciones (`cotizaciones` y `cotizacion_partidas`) |
| `migrar_v7.py` | diagnósticos con escáner (`diagnosticos` y `diagnostico_codigos`) |
| `migrar_v8.py` | candados contra duplicados: tres índices únicos de expresión sobre `clientes` y `vehiculos` (placa única, vehículo sin placa único por dueño, cliente único por nombre+teléfono) |

## No hace falta correrlos

Para levantar la base desde cero está `esquema.sql` + `cargar_datos.py`, que ya
crean la forma final. Estos guiones solo sirven si algún día restauras un
respaldo **anterior** a alguna de esas versiones (los hay en
`D:\TallerBautista\respaldos\`).

## Si alguna vez necesitas correr uno

Esperan estar en la raíz del proyecto, junto a `db.py`. Copia el que necesites
de vuelta a la raíz, córrelo desde ahí y luego bórralo:

```powershell
Copy-Item historico\migrar_v6.py .
.venv\Scripts\python.exe migrar_v6.py
Remove-Item migrar_v6.py
```

Cada uno hace su propio respaldo de la base antes de tocar nada.
