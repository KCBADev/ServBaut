"""
Pruebas del esquema — Servicio Bautista.

Comprueba que las garantías del esquema se cumplen de verdad: que las llaves
foráneas rechazan huérfanos, que los CHECK rechazan datos inválidos, que los
triggers mantienen el total de las notas y que editar el catálogo no altera el
histórico.

Corre sobre una base temporal; nunca toca taller.db.

Uso:
    .venv\\Scripts\\python.exe pruebas_esquema.py
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

import auth
import db
import migraciones

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

fallos = 0
pruebas = 0


def comprobar(descripcion: str, condicion: bool) -> None:
    global fallos, pruebas
    pruebas += 1
    if condicion:
        print(f"  [OK] {descripcion}")
    else:
        fallos += 1
        print(f"  [!!] FALLÓ: {descripcion}")


def rechaza(descripcion: str, conexion: sqlite3.Connection, sql: str,
            parametros: tuple) -> None:
    """Comprueba que la base RECHAZA una operación que debe ser inválida."""
    try:
        conexion.execute(sql, parametros)
    except sqlite3.IntegrityError:
        comprobar(descripcion, True)
    else:
        comprobar(descripcion, False)


def _version_de(ruta: Path) -> int:
    """Lee `PRAGMA user_version` de una base cerrada."""
    with db.conectar(ruta) as conexion:
        return migraciones.version_actual(conexion)


def sembrar(conexion: sqlite3.Connection) -> None:
    """Datos mínimos para poder probar."""
    conexion.execute("INSERT INTO categorias (nombre) VALUES ('Suspensión')")
    conexion.execute("INSERT INTO acciones (nombre) VALUES ('Reemplazo')")
    conexion.execute("INSERT INTO marcas (nombre) VALUES ('Jeep')")
    conexion.execute(
        "INSERT INTO clientes (id_cliente, nombre, telefono) VALUES (1, 'Prueba', '3312345678')"
    )
    conexion.execute(
        """INSERT INTO vehiculos (id_vehiculo, id_cliente, marca, modelo, anio, color)
           VALUES (1, 1, 'Jeep', 'Patriot', 2020, 'Negro')"""
    )
    conexion.execute(
        """INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha)
           VALUES ('N-001', 1, 1, '2025-01-15')"""
    )
    conexion.execute(
        """INSERT INTO catalogo (descripcion, tipo_concepto, categoria,
                                 precio_actual_centavos)
           VALUES ('Amortiguador', 'Producto', 'Suspensión', 180000)"""
    )


def main() -> None:
    with tempfile.TemporaryDirectory() as carpeta:
        ruta = Path(carpeta) / "prueba.db"
        db.inicializar_esquema(ruta)

        with db.conectar(ruta) as c:
            sembrar(c)

            print("\n--- Llaves foráneas ---")
            rechaza(
                "Rechaza una nota de un cliente inexistente", c,
                """INSERT INTO notas (id_nota, id_cliente, fecha)
                   VALUES ('N-002', 999, '2025-01-15')""", (),
            )
            rechaza(
                "Rechaza una nota con un vehículo inexistente", c,
                """INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha)
                   VALUES ('N-003', 1, 999, '2025-01-15')""", (),
            )
            rechaza(
                "Rechaza un vehículo con una marca no registrada", c,
                """INSERT INTO vehiculos (id_cliente, marca, modelo)
                   VALUES (1, 'Ferrari', 'F40')""", (),
            )
            rechaza(
                "Rechaza un estado de nota desconocido", c,
                """INSERT INTO notas (id_nota, id_cliente, fecha, estado)
                   VALUES ('N-004', 1, '2025-01-15', 'Inventado')""", (),
            )
            rechaza(
                "Rechaza un pago negativo", c,
                """INSERT INTO notas (id_nota, id_cliente, fecha, pagado_centavos)
                   VALUES ('N-005', 1, '2025-01-15', -100)""", (),
            )
            rechaza(
                "Rechaza una partida de una nota inexistente", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-999', 1, 'Producto', 'Suspensión', 'X', 1, 100, 100)""", (),
            )

            print("\n--- Reglas de negocio (CHECK) ---")
            rechaza(
                "Rechaza un Servicio sin acción", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         accion, descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 90, 'Servicio', 'Suspensión', NULL, 'X', 1, 100, 100)""",
                (),
            )
            rechaza(
                "Rechaza un Producto CON acción", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         accion, descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 91, 'Producto', 'Suspensión', 'Reemplazo', 'X',
                           1, 100, 100)""",
                (),
            )
            rechaza(
                "Rechaza total distinto de cantidad x precio", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 92, 'Producto', 'Suspensión', 'X', 2, 100, 999)""",
                (),
            )
            rechaza(
                "Rechaza cantidad cero", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 93, 'Producto', 'Suspensión', 'X', 0, 100, 0)""",
                (),
            )
            rechaza(
                "Rechaza un teléfono que no sean 10 dígitos", c,
                "INSERT INTO clientes (nombre, telefono) VALUES ('Y', '33-1234')", (),
            )
            rechaza(
                "Rechaza un lado inválido", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, lado, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 94, 'Producto', 'Suspensión', 'X', 'Arriba',
                           1, 100, 100)""",
                (),
            )
            rechaza(
                "Rechaza dos partidas con la misma línea en la misma nota", c,
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   SELECT 'N-001', 1, 'Producto', 'Suspensión', 'X', 1, 100, 100
                   UNION ALL
                   SELECT 'N-001', 1, 'Producto', 'Suspensión', 'Y', 1, 100, 100""",
                (),
            )

            print("\n--- Triggers que mantienen el total de la nota ---")
            c.execute(
                """INSERT INTO partidas (id_nota, linea, id_catalogo, tipo_concepto,
                                         categoria, descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 1, 1, 'Producto', 'Suspensión', 'Amortiguador',
                           2, 180000, 360000)"""
            )
            total = c.execute(
                "SELECT total_centavos t FROM notas WHERE id_nota='N-001'"
            ).fetchone()["t"]
            comprobar(f"El INSERT actualiza el total de la nota (={total})", total == 360000)

            c.execute(
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         accion, descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-001', 2, 'Servicio', 'Suspensión', 'Reemplazo',
                           'Mano de obra', 1, 90000, 90000)"""
            )
            total = c.execute(
                "SELECT total_centavos t FROM notas WHERE id_nota='N-001'"
            ).fetchone()["t"]
            comprobar(f"Suma la segunda partida (={total})", total == 450000)

            c.execute(
                "UPDATE partidas SET cantidad=1, total_centavos=180000 "
                "WHERE id_nota='N-001' AND linea=1"
            )
            total = c.execute(
                "SELECT total_centavos t FROM notas WHERE id_nota='N-001'"
            ).fetchone()["t"]
            comprobar(f"El UPDATE recalcula el total (={total})", total == 270000)

            c.execute("DELETE FROM partidas WHERE id_nota='N-001' AND linea=2")
            total = c.execute(
                "SELECT total_centavos t FROM notas WHERE id_nota='N-001'"
            ).fetchone()["t"]
            comprobar(f"El DELETE recalcula el total (={total})", total == 180000)

            print("\n--- El histórico es inmutable frente al catálogo ---")
            antes = c.execute(
                "SELECT precio_unitario_centavos p FROM partidas "
                "WHERE id_nota='N-001' AND linea=1"
            ).fetchone()["p"]
            c.execute(
                "UPDATE catalogo SET precio_actual_centavos = 999999 WHERE id_catalogo = 1"
            )
            despues = c.execute(
                "SELECT precio_unitario_centavos p FROM partidas "
                "WHERE id_nota='N-001' AND linea=1"
            ).fetchone()["p"]
            comprobar(
                f"Cambiar el precio del catálogo no altera la partida "
                f"({antes} -> {despues})",
                antes == despues == 180000,
            )

            c.execute("UPDATE catalogo SET activo = 0 WHERE id_catalogo = 1")
            sigue = c.execute(
                "SELECT COUNT(*) n FROM partidas WHERE id_catalogo = 1"
            ).fetchone()["n"]
            comprobar("Desactivar un concepto no borra sus partidas históricas", sigue == 1)

            print("\n--- Borrado en cascada de una nota ---")
            c.execute(
                """INSERT INTO notas (id_nota, id_cliente, id_vehiculo, fecha)
                   VALUES ('N-002', 1, 1, '2025-02-01')"""
            )
            c.execute(
                """INSERT INTO partidas (id_nota, linea, tipo_concepto, categoria,
                                         descripcion, cantidad,
                                         precio_unitario_centavos, total_centavos)
                   VALUES ('N-002', 1, 'Producto', 'Suspensión', 'X', 1, 5000, 5000)"""
            )
            c.execute("DELETE FROM notas WHERE id_nota='N-002'")
            restantes = c.execute(
                "SELECT COUNT(*) n FROM partidas WHERE id_nota='N-002'"
            ).fetchone()["n"]
            comprobar("Borrar una nota borra sus partidas", restantes == 0)

            print("\n--- Cotizaciones ---")
            rechaza(
                "Rechaza un folio de cotización con formato inválido", c,
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha)
                   VALUES ('X-001', 1, 1, '2025-01-15')""", (),
            )
            rechaza(
                "Rechaza un estado de cotización desconocido", c,
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha, estado)
                   VALUES ('COT-900', 1, 1, '2025-01-15', 'Inventado')""", (),
            )
            rechaza(
                "Rechaza Convertida sin su folio de nota", c,
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha, estado)
                   VALUES ('COT-901', 1, 1, '2025-01-15', 'Convertida')""", (),
            )
            rechaza(
                "Rechaza Pendiente CON un folio de nota", c,
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha, id_nota_generada)
                   VALUES ('COT-902', 1, 1, '2025-01-15', 'N-001')""", (),
            )

            c.execute(
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha)
                   VALUES ('COT-001', 1, 1, '2025-03-01')"""
            )
            c.execute(
                """INSERT INTO cotizacion_partidas (id_cotizacion, linea,
                        tipo_concepto, categoria, descripcion, cantidad,
                        precio_unitario_centavos, total_centavos)
                   VALUES ('COT-001', 1, 'Producto', 'Suspensión', 'Amortiguador',
                           2, 180000, 360000)"""
            )
            total = c.execute(
                "SELECT total_centavos t FROM cotizaciones WHERE id_cotizacion='COT-001'"
            ).fetchone()["t"]
            comprobar(f"El INSERT actualiza el total de la cotización (={total})",
                      total == 360000)

            c.execute("UPDATE cotizaciones SET tasa_iva = 0.16 WHERE id_cotizacion='COT-001'")
            total = c.execute(
                "SELECT total_centavos t FROM cotizaciones WHERE id_cotizacion='COT-001'"
            ).fetchone()["t"]
            comprobar(f"Aplicar el IVA recalcula el total (={total})",
                      total == 360000 + round(360000 * 0.16))

            c.execute("DELETE FROM cotizacion_partidas WHERE id_cotizacion='COT-001'")
            total = c.execute(
                "SELECT total_centavos t, subtotal_centavos s FROM cotizaciones "
                "WHERE id_cotizacion='COT-001'"
            ).fetchone()
            comprobar("El DELETE recalcula el total a cero",
                      total["t"] == 0 and total["s"] == 0)

            c.execute("DELETE FROM cotizaciones WHERE id_cotizacion='COT-001'")
            c.execute(
                """INSERT INTO cotizaciones (id_cotizacion, id_cliente,
                                             id_vehiculo, fecha)
                   VALUES ('COT-002', 1, 1, '2025-03-01')"""
            )
            c.execute(
                """INSERT INTO cotizacion_partidas (id_cotizacion, linea,
                        tipo_concepto, categoria, descripcion, cantidad,
                        precio_unitario_centavos, total_centavos)
                   VALUES ('COT-002', 1, 'Producto', 'Suspensión', 'X', 1, 5000, 5000)"""
            )
            c.execute("DELETE FROM cotizaciones WHERE id_cotizacion='COT-002'")
            restantes = c.execute(
                "SELECT COUNT(*) n FROM cotizacion_partidas WHERE id_cotizacion='COT-002'"
            ).fetchone()["n"]
            comprobar("Borrar una cotización borra sus renglones", restantes == 0)

            print("\n--- Diagnósticos con escáner ---")
            rechaza(
                "Rechaza un folio de diagnóstico con formato inválido", c,
                """INSERT INTO diagnosticos (id_diagnostico, id_cliente,
                                             id_vehiculo, fecha)
                   VALUES ('X-001', 1, 1, '2025-01-15')""", (),
            )
            rechaza(
                "Rechaza un diagnóstico sin vehículo", c,
                """INSERT INTO diagnosticos (id_diagnostico, id_cliente, fecha)
                   VALUES ('DX-900', 1, '2025-01-15')""", (),
            )
            c.execute(
                """INSERT INTO diagnosticos (id_diagnostico, id_cliente,
                                             id_vehiculo, fecha, tecnico)
                   VALUES ('DX-001', 1, 1, '2025-03-01', 'R. Bautista')"""
            )
            rechaza(
                "Rechaza una gravedad desconocida", c,
                """INSERT INTO diagnostico_codigos (id_diagnostico, linea,
                        sistema, codigo, descripcion, significado, gravedad)
                   VALUES ('DX-001', 1, 'Motor', 'P0135', 'X', 'Y',
                           'Inventada')""", (),
            )
            rechaza(
                "Rechaza un código de un diagnóstico inexistente", c,
                """INSERT INTO diagnostico_codigos (id_diagnostico, linea,
                        sistema, codigo, descripcion, significado)
                   VALUES ('DX-999', 1, 'Motor', 'P0135', 'X', 'Y')""", (),
            )
            c.execute(
                """INSERT INTO diagnostico_codigos (id_diagnostico, linea,
                        sistema, codigo, descripcion, significado, gravedad)
                   VALUES ('DX-001', 1, 'Motor', 'P0135',
                           'Fallo en el calentador', 'Sensor dañado', 'ALTA')"""
            )
            c.execute(
                """INSERT INTO diagnostico_codigos (id_diagnostico, linea,
                        sistema, codigo, descripcion, significado, gravedad)
                   VALUES ('DX-001', 2, 'Frenos ABS', 'C1145',
                           'Fallo circuito de entrada', 'Sin señal de rueda',
                           'ALTA')"""
            )
            total = c.execute(
                "SELECT COUNT(*) n FROM diagnostico_codigos WHERE id_diagnostico='DX-001'"
            ).fetchone()["n"]
            comprobar(f"Los códigos quedan asociados al diagnóstico (={total})",
                      total == 2)

            c.execute("DELETE FROM diagnosticos WHERE id_diagnostico='DX-001'")
            restantes = c.execute(
                "SELECT COUNT(*) n FROM diagnostico_codigos WHERE id_diagnostico='DX-001'"
            ).fetchone()["n"]
            comprobar("Borrar un diagnóstico borra sus códigos", restantes == 0)

            print("\n--- Contraseñas ---")
            auth.crear_usuario(c, "prueba", "MiClaveSegura123", rol="admin")
            fila = c.execute(
                "SELECT hash_password, salt FROM usuarios WHERE usuario='prueba'"
            ).fetchone()
            comprobar("La contraseña no se guarda en texto plano",
                      "MiClaveSegura123" not in fila["hash_password"])
            comprobar("Autentica con la contraseña correcta",
                      auth.autenticar(c, "prueba", "MiClaveSegura123") is not None)
            comprobar("Rechaza la contraseña incorrecta",
                      auth.autenticar(c, "prueba", "otra") is None)
            comprobar("Rechaza un usuario inexistente",
                      auth.autenticar(c, "nadie", "MiClaveSegura123") is None)

            auth.crear_usuario(c, "prueba2", "MiClaveSegura123")
            hashes = [f["hash_password"] for f in c.execute(
                "SELECT hash_password FROM usuarios WHERE usuario IN ('prueba','prueba2')"
            )]
            comprobar("Dos usuarios con la misma contraseña tienen hashes distintos",
                      hashes[0] != hashes[1])

            print("\n--- Conversión de dinero ---")
            comprobar("381146.50 pesos -> 38114650 centavos",
                      db.pesos_a_centavos("381146.50") == 38114650)
            comprobar("229.50 pesos -> 22950 centavos",
                      db.pesos_a_centavos(229.50) == 22950)
            comprobar("Ida y vuelta sin pérdida",
                      db.pesos_a_centavos(db.centavos_a_pesos(38114650)) == 38114650)
            comprobar("Formato legible", db.formato_pesos(38114650) == "$381,146.50")

            print("\n--- Versionado del esquema ---")
            # El invariante que de verdad importa: una base recién creada desde
            # `esquema.sql` tiene que verse como VERSION_OBJETIVO. Si alguien
            # agrega una tabla al esquema y olvida su `Paso` en migraciones.py,
            # o al revés, esta prueba lo caza antes de que una base nueva quede
            # sellada con un número que no corresponde a su forma.
            comprobar("`esquema.sql` produce la forma de VERSION_OBJETIVO",
                      migraciones.version_detectada(c)
                      == migraciones.VERSION_OBJETIVO)

            migraciones.sellar(c, 5)
            comprobar("Sellar y volver a leer da el mismo número",
                      migraciones.version_actual(c) == 5)
            comprobar("Con la versión atrasada aparecen pasos pendientes",
                      [p.version for p in migraciones.pendientes(c)] == [6, 7, 8])
            migraciones.sellar(c, migraciones.VERSION_OBJETIVO)
            comprobar("Al día no queda ningún paso pendiente",
                      migraciones.pendientes(c) == [])

            comprobar("Todos los pasos declaran guion o forma de aplicarse",
                      all(p.aplicar is not None or p.guion
                          for p in migraciones.PASOS[1:]))
            comprobar("Las versiones de los pasos son consecutivas desde 1",
                      [p.version for p in migraciones.PASOS]
                      == list(range(1, len(migraciones.PASOS) + 1)))

        with tempfile.TemporaryDirectory() as otra_carpeta:
            desde_cero = Path(otra_carpeta) / "nueva.db"
            hechos = migraciones.preparar(desde_cero)
            comprobar("`preparar` crea la base si no existe", desde_cero.exists())
            comprobar("Y la deja sellada en VERSION_OBJETIVO",
                      _version_de(desde_cero) == migraciones.VERSION_OBJETIVO)
            comprobar("Reporta lo que hizo", len(hechos) == 1)
            comprobar("Llamarla de nuevo no hace nada",
                      migraciones.preparar(desde_cero) == [])

    print()
    print("=" * 74)
    if fallos:
        print(f"{fallos} de {pruebas} pruebas FALLARON.")
    else:
        print(f"Las {pruebas} pruebas pasaron.")
    print("=" * 74)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
