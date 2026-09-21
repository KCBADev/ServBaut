"""
Pruebas de la capa de acceso a datos — Servicio Bautista.

Comprueba el CRUD de db.py: altas, ediciones, búsqueda sin acentos, captura de
notas completas y que el total lo calculen los triggers y no la aplicación.

Corre sobre una base temporal; nunca toca taller.db.

Uso:
    .venv\\Scripts\\python.exe pruebas_datos.py
"""

from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

import arranque
import auth
import config
import db
import exportar
import nota_pdf
import respaldos
from explorar_excel import detectar_bloques, extraer_tabla

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


def sembrar() -> None:
    """Referencias mínimas para poder capturar notas."""
    with db.transaccion() as c:
        for nombre in ("Suspensión", "Motor", "Frenos"):
            c.execute("INSERT INTO categorias (nombre) VALUES (?)", (nombre,))
        for nombre in ("Reemplazo", "Reparación"):
            c.execute("INSERT INTO acciones (nombre) VALUES (?)", (nombre,))
        for nombre in ("Jeep", "Mazda"):
            c.execute("INSERT INTO marcas (nombre) VALUES (?)", (nombre,))


def main() -> None:
    with tempfile.TemporaryDirectory() as carpeta:
        # Se apunta la capa de datos a una base temporal.
        db.RUTA_DB = Path(carpeta) / "prueba.db"
        db.inicializar_esquema()
        sembrar()

        print("\n--- Teléfonos ---")
        comprobar("Acepta 10 dígitos limpios",
                  db.normalizar_telefono("5550100001") == "5550100001")
        comprobar("Limpia espacios, guiones y paréntesis",
                  db.normalizar_telefono("(55) 5010-0001") == "5550100001")
        comprobar("Vacío -> None", db.normalizar_telefono("") is None)
        comprobar("None -> None", db.normalizar_telefono(None) is None)
        try:
            db.normalizar_telefono("55501")
            comprobar("Rechaza menos de 10 dígitos", False)
        except ValueError:
            comprobar("Rechaza menos de 10 dígitos", True)

        print("\n--- Clientes ---")
        id1 = db.crear_cliente("Martín Quiroga", "5550100001")
        id2 = db.crear_cliente("Ana López", None)
        comprobar(f"Crea clientes con id consecutivo ({id1}, {id2})",
                  id1 == 1 and id2 == 2)

        cliente = db.obtener_cliente(id2)
        comprobar("El teléfono opcional queda en NULL", cliente["telefono"] is None)

        comprobar("Busca sin acentos ('martin' encuentra 'Martín')",
                  len(db.listar_clientes("martin")) == 1)
        comprobar("Busca sin distinguir mayúsculas",
                  len(db.listar_clientes("ANA")) == 1)
        comprobar("Busca por teléfono",
                  len(db.listar_clientes("0100")) == 1)
        comprobar("Búsqueda vacía devuelve todos",
                  len(db.listar_clientes("")) == 2)

        parecidos = db.buscar_nombres_parecidos("martin quiroga")
        comprobar("Detecta un nombre duplicado ignorando acentos y mayúsculas",
                  len(parecidos) == 1 and parecidos[0]["id_cliente"] == id1)
        comprobar("No se señala a sí mismo al editar",
                  db.buscar_nombres_parecidos("Martín Quiroga", excluir_id=id1) == [])

        db.actualizar_cliente(id2, "Ana López Ruiz", "3310000000")
        cliente = db.obtener_cliente(id2)
        comprobar("Actualiza nombre y teléfono",
                  cliente["nombre"] == "Ana López Ruiz"
                  and cliente["telefono"] == "3310000000")

        try:
            db.crear_cliente("   ", None)
            comprobar("Rechaza un nombre vacío", False)
        except ValueError:
            comprobar("Rechaza un nombre vacío", True)

        print("\n--- Catálogo ---")
        cat1 = db.crear_concepto("Amortiguador", "Producto", "Suspensión", 180000)
        cat2 = db.crear_concepto("Alineación", "Servicio", "Suspensión", 30000)
        comprobar("Crea conceptos", cat1 == 1 and cat2 == 2)

        comprobar("Filtra por tipo",
                  len(db.listar_catalogo(tipo="Producto")) == 1)
        comprobar("Filtra por categoría",
                  len(db.listar_catalogo(categoria="Suspensión")) == 2)
        comprobar("Busca sin acentos ('alineacion' encuentra 'Alineación')",
                  len(db.listar_catalogo("alineacion")) == 1)

        db.cambiar_estado_concepto(cat2, False)
        comprobar("Desactivar lo saca de los activos",
                  len(db.listar_catalogo(solo_activos=True)) == 1)
        db.cambiar_estado_concepto(cat2, True)

        try:
            db.crear_concepto("Amortiguador", "Producto", "Motor", 100)
            comprobar("Rechaza descripción+tipo duplicados", False)
        except Exception:
            comprobar("Rechaza descripción+tipo duplicados", True)

        comprobar("Permite la misma descripción con otro tipo",
                  db.crear_concepto("Amortiguador", "Servicio", "Suspensión", 50000) > 0)

        print("\n--- Vehículos ---")
        veh1 = db.crear_vehiculo(id1, "Jeep", "Patriot", 2020, "Negro",
                                 placas="ABC-123")
        veh2 = db.crear_vehiculo(id2, "Mazda", "Mazda-3", 2018, "Blanco")
        comprobar(f"Crea vehículos ({veh1}, {veh2})", veh1 == 1 and veh2 == 2)
        comprobar("Los lista con su dueño",
                  len(db.listar_vehiculos()) == 2)
        comprobar("Busca sin acentos y por placas",
                  len(db.listar_vehiculos("ABC")) == 1
                  and len(db.listar_vehiculos("mazda")) == 1)
        comprobar("Filtra por cliente",
                  len(db.listar_vehiculos(id_cliente=id1)) == 1)

        print("\n--- Notas ---")
        id_nota = db.crear_nota(
            id_cliente=id1, fecha="2025-06-15", id_vehiculo=veh1,
            partidas=[
                {"id_catalogo": cat1, "tipo_concepto": "Producto",
                 "categoria": "Suspensión", "accion": None,
                 "descripcion": "Amortiguador", "posicion": "Anterior",
                 "lado": "Par", "cantidad": 2,
                 "precio_unitario_centavos": 180000},
                {"id_catalogo": None, "tipo_concepto": "Servicio",
                 "categoria": "Suspensión", "accion": "Reemplazo",
                 "descripcion": "Mano de obra", "posicion": None, "lado": None,
                 "cantidad": 1, "precio_unitario_centavos": 90000},
            ],
        )
        comprobar(f"El folio sigue el formato original ({id_nota})", id_nota == "N-001")

        nota = db.obtener_nota(id_nota)
        comprobar("La nota guarda sus dos partidas", len(nota["partidas"]) == 2)
        comprobar("Las líneas se numeran 1..n dentro de la nota",
                  [p["linea"] for p in nota["partidas"]] == [1, 2])
        comprobar(f"El total lo calcularon los triggers, no la app "
                  f"({db.formato_pesos(nota['total_centavos'])})",
                  nota["total_centavos"] == 2 * 180000 + 90000)
        comprobar("El importe de cada partida es cantidad x precio",
                  nota["partidas"][0]["total_centavos"] == 360000)

        segundo = db.crear_nota(
            id_cliente=id2, fecha="2025-07-01", id_vehiculo=veh2,
            partidas=[{"id_catalogo": cat2, "tipo_concepto": "Servicio",
                       "categoria": "Suspensión", "accion": "Reparación",
                       "descripcion": "Alineación", "posicion": None, "lado": None,
                       "cantidad": 1, "precio_unitario_centavos": 30000}],
        )
        comprobar(f"El folio avanza ({segundo})", segundo == "N-002")

        comprobar("Lista las dos notas", len(db.listar_notas()) == 2)
        comprobar("Filtra por rango de fechas",
                  len(db.listar_notas(desde="2025-06-20")) == 1)
        comprobar("Busca por folio", len(db.listar_notas("N-001")) == 1)
        comprobar("Busca por nombre de cliente sin acentos",
                  len(db.listar_notas("martin")) == 1)
        comprobar("Busca por modelo", len(db.listar_notas("patriot")) == 1)

        try:
            db.crear_nota(id_cliente=id1, fecha="2025-08-01",
                          id_vehiculo=veh1, partidas=[])
            comprobar("Rechaza una nota sin partidas", False)
        except ValueError:
            comprobar("Rechaza una nota sin partidas", True)

        try:
            db.crear_nota(
                id_cliente=id1, fecha="2025-08-01", id_vehiculo=veh1,
                partidas=[{"tipo_concepto": "Servicio", "categoria": "Motor",
                           "accion": None, "descripcion": "X", "cantidad": 1,
                           "precio_unitario_centavos": 100}],
            )
            comprobar("Rechaza un Servicio sin acción", False)
        except Exception:
            comprobar("Rechaza un Servicio sin acción", True)

        comprobar("La nota rechazada no dejó rastro (transacción revertida)",
                  len(db.listar_notas()) == 2)

        print("\n--- El histórico no se mueve al editar el catálogo ---")
        antes = db.obtener_nota("N-001")["partidas"][0]["precio_unitario_centavos"]
        db.actualizar_concepto(cat1, "Amortiguador", "Producto", "Suspensión",
                               999900, True)
        despues = db.obtener_nota("N-001")["partidas"][0]["precio_unitario_centavos"]
        comprobar(f"El precio de la partida no cambió ({antes} -> {despues})",
                  antes == despues == 180000)
        comprobar("El total de la nota tampoco",
                  db.obtener_nota("N-001")["total_centavos"] == 450000)

        print("\n--- Cuadre global ---")
        cuadre = db.verificar_cuadre()
        comprobar("Notas y partidas suman lo mismo", cuadre["coinciden"])
        comprobar("Ninguna nota descuadrada", cuadre["notas_descuadradas"] == [])

        print("\n--- Resumen del cliente ---")
        martin = [c for c in db.listar_clientes() if c["id_cliente"] == id1][0]
        comprobar("Cuenta las notas del cliente", martin["num_notas"] == 1)
        comprobar("Suma lo facturado del cliente",
                  martin["total_facturado_centavos"] == 450000)

        # ------------------------------------------------------------------
        # Edición de notas. Se usa una nota propia para no alterar las
        # aserciones de arriba.
        # ------------------------------------------------------------------
        print("\n--- Editar la cabecera de una nota ---")
        editable = db.crear_nota(
            id_cliente=id2, fecha="2025-09-01", id_vehiculo=veh2,
            partidas=[
                {"tipo_concepto": "Producto", "categoria": "Motor", "accion": None,
                 "descripcion": "Pieza A", "cantidad": 1,
                 "precio_unitario_centavos": 10000},
                {"tipo_concepto": "Producto", "categoria": "Motor", "accion": None,
                 "descripcion": "Pieza B", "cantidad": 1,
                 "precio_unitario_centavos": 20000},
                {"tipo_concepto": "Servicio", "categoria": "Motor",
                 "accion": "Reemplazo", "descripcion": "Mano de obra",
                 "cantidad": 1, "precio_unitario_centavos": 30000},
            ],
        )
        comprobar(f"Nota de prueba creada ({editable})",
                  db.obtener_nota(editable)["total_centavos"] == 60000)

        db.actualizar_nota(editable, id_cliente=id1, fecha="2025-09-15",
                           id_vehiculo=veh1)
        nota = db.obtener_nota(editable)
        comprobar("Cambia el cliente asignado", nota["id_cliente"] == id1)
        comprobar("Cambia la fecha", nota["fecha"] == "2025-09-15")
        comprobar("Cambia el vehículo atendido",
                  nota["id_vehiculo"] == veh1 and nota["modelo"] == "Patriot")
        comprobar("Editar la cabecera no altera el total",
                  nota["total_centavos"] == 60000)

        print("\n--- Corregir el vehículo alcanza a todas sus notas ---")
        # Es la razón de ser de la tabla: el año de un carro no es historia.
        db.actualizar_vehiculo(veh1, id1, "Jeep", "Patriot", 2007, "Negro",
                               "ABC-123", None, None, True)
        comprobar("La nota ya refleja el año corregido",
                  db.obtener_nota(editable)["anio"] == 2007)
        comprobar("Y también la otra nota de ese vehículo",
                  db.obtener_nota(id_nota)["anio"] == 2007)

        print("\n--- Estado y pagos ---")
        db.cambiar_estado(editable, "En proceso")
        comprobar("Cambia el estado",
                  db.obtener_nota(editable)["estado"] == "En proceso")
        try:
            db.cambiar_estado(editable, "Inventado")
            comprobar("Rechaza un estado desconocido", False)
        except ValueError:
            comprobar("Rechaza un estado desconocido", True)

        db.registrar_pago(editable, 20000)
        nota = db.obtener_nota(editable)
        comprobar(f"Registra el pago ({db.formato_pesos(nota['pagado_centavos'])})",
                  nota["pagado_centavos"] == 20000)
        comprobar(f"Calcula el saldo ({db.formato_pesos(nota['saldo_centavos'])})",
                  nota["saldo_centavos"] == 40000)
        try:
            db.registrar_pago(editable, 999999)
            comprobar("Impide pagar más que el total", False)
        except ValueError:
            comprobar("Impide pagar más que el total", True)

        print("\n--- Entregar marca la nota como pagada, sola ---")
        # `editable` sigue con 20000 de 60000 pagado (arriba). El taller no
        # entrega un carro sin cobrarlo, así que pasar a "Entregado" cierra
        # el pago sin que haga falta el paso manual de "Registrar pago".
        db.cambiar_estado(editable, "Entregado")
        nota = db.obtener_nota(editable)
        comprobar(f"Al entregar, el pago se completa solo "
                  f"({db.formato_pesos(nota['pagado_centavos'])})",
                  nota["pagado_centavos"] == nota["total_centavos"])
        comprobar("Y el saldo queda en cero", nota["saldo_centavos"] == 0)

        db.cambiar_estado(editable, "En proceso")
        comprobar("Mover la nota a otro estado NO deshace el pago ya cobrado",
                  db.obtener_nota(editable)["pagado_centavos"]
                  == nota["total_centavos"])

        print("\n--- Historial del vehículo ---")
        ficha = db.obtener_vehiculo(veh1)
        comprobar(f"Junta las notas del carro ({len(ficha['historial'])})",
                  len(ficha["historial"]) == 2)
        comprobar("Y resume en qué se gastó",
                  len(ficha["por_categoria"]) > 0)

        print("\n--- Datos del taller ---")
        db.actualizar_taller("Auto Servicio Bautista", "Nota de servicio",
                             "Av. Vallarta 123", "3312345678",
                             "taller@ejemplo.mx", "BAUK900101ABC",
                             "Gracias por su preferencia.")
        taller = db.obtener_taller()
        comprobar("Guarda los datos del taller",
                  taller["telefono"] == "3312345678"
                  and taller["rfc"] == "BAUK900101ABC")
        try:
            db.actualizar_taller("  ", None, None, None, None, None, None)
            comprobar("Rechaza un taller sin nombre", False)
        except ValueError:
            comprobar("Rechaza un taller sin nombre", True)

        print("\n--- Editar las partidas ---")
        partidas = db.obtener_nota(editable)["partidas"]
        db.actualizar_partida(partidas[0]["id_partida"], cantidad=3,
                              precio_unitario_centavos=10000)
        nota = db.obtener_nota(editable)
        comprobar("El importe de la partida se recalcula",
                  nota["partidas"][0]["total_centavos"] == 30000)
        comprobar(f"El trigger sube el total de la nota "
                  f"({db.formato_pesos(nota['total_centavos'])})",
                  nota["total_centavos"] == 80000)

        nuevo_id = db.agregar_partida(editable, {
            "tipo_concepto": "Producto", "categoria": "Frenos", "accion": None,
            "descripcion": "Pieza D", "cantidad": 2,
            "precio_unitario_centavos": 5000,
        })
        nota = db.obtener_nota(editable)
        comprobar("Agrega una partida al final", len(nota["partidas"]) == 4)
        comprobar("La partida nueva toma la línea siguiente",
                  nota["partidas"][-1]["linea"] == 4)
        comprobar("El total incluye la partida nueva",
                  nota["total_centavos"] == 90000)

        print("\n--- Quitar una partida y renumerar ---")
        # Se quita la segunda de cuatro: deben quedar las líneas 1,2,3 sin huecos.
        segunda = db.obtener_nota(editable)["partidas"][1]
        db.eliminar_partida(segunda["id_partida"])
        nota = db.obtener_nota(editable)
        comprobar("Queda una partida menos", len(nota["partidas"]) == 3)
        comprobar(f"Las líneas se renumeran 1..n sin huecos "
                  f"({[p['linea'] for p in nota['partidas']]})",
                  [p["linea"] for p in nota["partidas"]] == [1, 2, 3])
        comprobar("Se conserva el orden de las que quedaron",
                  [p["descripcion"] for p in nota["partidas"]]
                  == ["Pieza A", "Mano de obra", "Pieza D"])
        comprobar(f"El total baja al quitar la partida "
                  f"({db.formato_pesos(nota['total_centavos'])})",
                  nota["total_centavos"] == 70000)

        # Una nota no puede quedarse vacía: su total quedaría en cero.
        solo_una = db.crear_nota(
            id_cliente=id2, fecha="2025-09-20", id_vehiculo=veh2,
            partidas=[{"tipo_concepto": "Producto", "categoria": "Motor",
                       "accion": None, "descripcion": "Única", "cantidad": 1,
                       "precio_unitario_centavos": 5000}],
        )
        unica = db.obtener_nota(solo_una)["partidas"][0]
        try:
            db.eliminar_partida(unica["id_partida"])
            comprobar("Impide dejar una nota sin partidas", False)
        except ValueError:
            comprobar("Impide dejar una nota sin partidas", True)

        print("\n--- Eliminar una nota completa ---")
        antes = len(db.listar_notas())
        db.eliminar_nota(solo_una)
        comprobar("La nota desaparece de la lista",
                  len(db.listar_notas()) == antes - 1)
        comprobar("Y ya no se puede obtener", db.obtener_nota(solo_una) is None)
        with db.conectar() as conexion:
            huerfanas = conexion.execute(
                "SELECT COUNT(*) AS n FROM partidas WHERE id_nota = ?",
                (solo_una,),
            ).fetchone()["n"]
        comprobar("Sus partidas se borraron en cascada", huerfanas == 0)

        cuadre = db.verificar_cuadre()
        comprobar("Tras editar y borrar, el cuadre se mantiene",
                  cuadre["coinciden"] and not cuadre["notas_descuadradas"])

        print("\n--- PDF de la nota ---")
        pdf = nota_pdf.generar(editable)
        comprobar("Genera un PDF válido", pdf[:5] == b"%PDF-")
        comprobar(f"Con contenido real ({len(pdf):,} bytes)", len(pdf) > 800)
        comprobar("El nombre del archivo lleva el folio",
                  nota_pdf.nombre_archivo(editable) == f"orden-{editable}.pdf")
        try:
            nota_pdf.generar("N-999")
            comprobar("Falla claro si la nota no existe", False)
        except ValueError:
            comprobar("Falla claro si la nota no existe", True)

        print("\n--- IVA ---")
        # Los importes del ejemplo real del taller: 5,000 + 16% = 5,800.
        renglones = [
            {"tipo_concepto": "Producto", "categoria": "Frenos", "accion": None,
             "descripcion": d, "cantidad": 1, "precio_unitario_centavos": p}
            for d, p in (("Balatas", 101000), ("Balatas traseras", 69000),
                         ("Rectificado delantero", 20000),
                         ("Rectificado trasero", 20000),
                         ("Mano de obra frenos", 80000), ("Afinación", 210000))
        ]
        sin_iva = db.crear_nota(id1, "2026-01-21", veh1, renglones)
        n = db.obtener_nota(sin_iva)
        comprobar(f"Sin IVA el total es el subtotal "
                  f"({db.formato_pesos(n['total_centavos'])})",
                  n["subtotal_centavos"] == 500000
                  and n["total_centavos"] == 500000)

        con_iva = db.crear_nota(id1, "2026-01-21", veh1, renglones,
                                tasa_iva=0.16)
        n = db.obtener_nota(con_iva)
        iva = n["total_centavos"] - n["subtotal_centavos"]
        comprobar(f"Con IVA al 16%: 5,000 + 800 = 5,800 "
                  f"({db.formato_pesos(n['total_centavos'])})",
                  n["subtotal_centavos"] == 500000 and iva == 80000
                  and n["total_centavos"] == 580000)

        db.cambiar_tasa_iva(sin_iva, 0.16)
        comprobar("Aplicar IVA después recalcula el total",
                  db.obtener_nota(sin_iva)["total_centavos"] == 580000)
        db.cambiar_tasa_iva(sin_iva, 0)
        comprobar("Y quitarlo lo devuelve al subtotal",
                  db.obtener_nota(sin_iva)["total_centavos"] == 500000)

        db.agregar_partida(con_iva, {
            "tipo_concepto": "Producto", "categoria": "Frenos", "accion": None,
            "descripcion": "Líquido de frenos", "cantidad": 1,
            "precio_unitario_centavos": 25000})
        n = db.obtener_nota(con_iva)
        comprobar("Agregar un renglón recalcula subtotal e IVA",
                  n["subtotal_centavos"] == 525000
                  and n["total_centavos"] == 525000 + round(525000 * 0.16))

        try:
            db.cambiar_tasa_iva(con_iva, 1.5)
            comprobar("Rechaza una tasa fuera de rango", False)
        except ValueError:
            comprobar("Rechaza una tasa fuera de rango", True)

        # El PDF de una nota con IVA debe salir y traer el impuesto.
        pdf = nota_pdf.generar(con_iva)
        comprobar("La orden de trabajo con IVA se genera",
                  pdf[:5] == b"%PDF-" and len(pdf) > 800)

        db.eliminar_nota(sin_iva)
        db.eliminar_nota(con_iva)

        print("\n--- El vehículo siempre tiene dueño ---")
        try:
            db.crear_vehiculo(None, "Jeep", "Suelto", 2020, "Negro")
            comprobar("Rechaza un vehículo sin dueño", False)
        except ValueError:
            comprobar("Rechaza un vehículo sin dueño", True)
        try:
            db.actualizar_vehiculo(veh1, None, "Jeep", "Patriot", 2007,
                                   "Negro", None, None, None, True)
            comprobar("Tampoco deja quitarle el dueño a uno existente", False)
        except ValueError:
            comprobar("Tampoco deja quitarle el dueño a uno existente", True)

        print("\n--- Cotizaciones ---")
        renglones_cot = [
            {"tipo_concepto": "Producto", "categoria": "Frenos", "accion": None,
             "descripcion": "Balatas", "cantidad": 1,
             "precio_unitario_centavos": 100000},
            {"tipo_concepto": "Servicio", "categoria": "Frenos",
             "accion": "Reemplazo", "descripcion": "Mano de obra",
             "cantidad": 1, "precio_unitario_centavos": 50000},
        ]

        cot1 = db.crear_cotizacion(id1, veh1, "2026-02-01", renglones_cot)
        comprobar(f"El folio de cotización sigue su propio formato ({cot1})",
                  cot1 == "COT-001")
        cotizacion = db.obtener_cotizacion(cot1)
        comprobar("Nace en estado Pendiente",
                  cotizacion["estado"] == "Pendiente")
        comprobar(f"El total lo calculan los triggers, no la app "
                  f"({db.formato_pesos(cotizacion['total_centavos'])})",
                  cotizacion["subtotal_centavos"] == 150000
                  and cotizacion["total_centavos"] == 150000)
        comprobar("Trae sus dos renglones", len(cotizacion["partidas"]) == 2)

        print("\n--- PDF de la cotización ---")
        pdf_cot = nota_pdf.generar_cotizacion(cot1)
        comprobar("Genera un PDF válido", pdf_cot[:5] == b"%PDF-")
        comprobar(f"Con contenido real ({len(pdf_cot):,} bytes)",
                  len(pdf_cot) > 800)
        comprobar("El nombre del archivo lleva el folio",
                  nota_pdf.nombre_archivo_cotizacion(cot1)
                  == f"cotizacion-{cot1}.pdf")
        try:
            nota_pdf.generar_cotizacion("COT-999")
            comprobar("Falla claro si la cotización no existe", False)
        except ValueError:
            comprobar("Falla claro si la cotización no existe", True)

        comprobar("El cliente ya existía: no se duplicó al cotizar",
                  len(db.listar_clientes()) == 2)
        comprobar("El vehículo usado en la cotización sigue siendo el mismo",
                  cotizacion["id_vehiculo"] == veh1)

        try:
            db.crear_cotizacion(id1, veh1, "2026-02-01", [])
            comprobar("Rechaza una cotización sin renglones", False)
        except ValueError:
            comprobar("Rechaza una cotización sin renglones", True)

        comprobar("NO aparece entre las notas (no es trabajo realizado)",
                  cot1 not in [n["id_nota"] for n in db.listar_notas()])
        kpis_antes = db.kpis()

        cot2 = db.crear_cotizacion(id2, veh2, "2026-02-02", renglones_cot,
                                   tasa_iva=0.16)
        cotizacion2 = db.obtener_cotizacion(cot2)
        iva_cot = cotizacion2["total_centavos"] - cotizacion2["subtotal_centavos"]
        comprobar(f"Cotización con IVA al 16% ({db.formato_pesos(iva_cot)})",
                  iva_cot == round(150000 * 0.16))

        comprobar("listar_cotizaciones trae ambas",
                  len({c["id_cotizacion"] for c in db.listar_cotizaciones()}
                      & {cot1, cot2}) == 2)
        comprobar("Filtra por estado Pendiente",
                  all(c["estado"] == "Pendiente"
                      for c in db.listar_cotizaciones(estado="Pendiente")))
        comprobar("Busca por folio",
                  len(db.listar_cotizaciones(busqueda=cot1)) == 1)

        print("\n--- Convertir una cotización en nota ---")
        folio_nota = db.convertir_cotizacion_a_nota(cot1, fecha="2026-02-05")
        comprobar(f"Genera un folio de NOTA, no de cotización ({folio_nota})",
                  folio_nota.startswith("N-"))
        nota_generada = db.obtener_nota(folio_nota)
        comprobar("La nota hereda cliente, vehículo y renglones de la cotización",
                  nota_generada["id_cliente"] == id1
                  and nota_generada["id_vehiculo"] == veh1
                  and len(nota_generada["partidas"]) == 2
                  and nota_generada["subtotal_centavos"] == 150000)
        comprobar("La nota nace como Recibido",
                  nota_generada["estado"] == "Recibido")

        cotizacion = db.obtener_cotizacion(cot1)
        comprobar("La cotización queda Convertida y apunta al folio nuevo",
                  cotizacion["estado"] == "Convertida"
                  and cotizacion["id_nota_generada"] == folio_nota)

        kpis_despues = db.kpis()
        comprobar("Convertir SÍ mueve los KPIs (ahora es una nota real)",
                  kpis_despues["num_notas"] == kpis_antes["num_notas"] + 1)

        try:
            db.convertir_cotizacion_a_nota(cot1)
            comprobar("No deja convertir la misma cotización dos veces", False)
        except ValueError:
            comprobar("No deja convertir la misma cotización dos veces", True)

        try:
            db.eliminar_cotizacion(cot1)
            comprobar("No deja borrar una cotización ya convertida", False)
        except ValueError:
            comprobar("No deja borrar una cotización ya convertida", True)

        print("\n--- Rechazar y borrar una cotización ---")
        db.rechazar_cotizacion(cot2)
        comprobar("Rechazar cambia su estado",
                  db.obtener_cotizacion(cot2)["estado"] == "Rechazada")
        try:
            db.rechazar_cotizacion(cot1)
            comprobar("No deja rechazar una ya convertida", False)
        except ValueError:
            comprobar("No deja rechazar una ya convertida", True)

        db.eliminar_cotizacion(cot2)
        comprobar("Sí se puede borrar una rechazada",
                  db.obtener_cotizacion(cot2) is None)

        print("\n--- Borrar la nota generada revierte la cotización ---")
        db.eliminar_nota(folio_nota)
        cotizacion = db.obtener_cotizacion(cot1)
        comprobar("La cotización vuelve a Pendiente en vez de quedar huérfana",
                  cotizacion["estado"] == "Pendiente"
                  and cotizacion["id_nota_generada"] is None)
        db.eliminar_cotizacion(cot1)

        comprobar("El cuadre del histórico no se movió con las cotizaciones",
                  db.verificar_cuadre()["coinciden"])

        print("\n--- arranque.py: primer administrador ---")
        # Base propia y aparte, no la compartida del resto de la suite: si el
        # admin automático conviviera con "jefe" y "ayudante" más abajo,
        # dejaría de ser cierto que "jefe" es el ÚNICO administrador activo
        # tras desactivar a "ayudante", y rompería esa prueba sin que tuviera
        # nada que ver con lo que se está probando aquí.
        with tempfile.TemporaryDirectory() as otra_carpeta:
            ruta_arranque = Path(otra_carpeta) / "prueba.db"
            db.inicializar_esquema(ruta_arranque)

            with db.transaccion(ruta_arranque) as c:
                informe1 = arranque.asegurar_admin(c)
            comprobar("Sin usuarios, crea el primer administrador",
                      informe1 is not None)
            with db.conectar(ruta_arranque) as c:
                fila = c.execute(
                    "SELECT usuario, rol, debe_cambiar_password FROM usuarios"
                ).fetchone()
            comprobar("Usa el nombre por omisión ('admin')",
                      fila["usuario"] == "admin")
            comprobar("Nace como administrador", fila["rol"] == "admin")
            comprobar("Nace con el cambio de contraseña obligatorio",
                      bool(fila["debe_cambiar_password"]))

            with db.transaccion(ruta_arranque) as c:
                informe2 = arranque.asegurar_admin(c)
            comprobar("Con un administrador ya existente, no crea otro",
                      informe2 is None)

            try:
                with db.transaccion(ruta_arranque) as c:
                    auth.crear_usuario(c, "admin", "otra-clave", rol="admin")
                comprobar("Dos administradores con el mismo nombre: rechazado",
                          False)
            except sqlite3.IntegrityError:
                comprobar("Dos administradores con el mismo nombre: rechazado",
                          True)

        print("\n--- Usuarios y roles ---")
        with db.transaccion() as conexion:
            auth.crear_usuario(conexion, "jefe", "ClaveLarga123", "admin")
            auth.crear_usuario(conexion, "ayudante", "ClaveLarga123", "operador")
        usuarios = db.listar_usuarios()
        comprobar(f"Lista los usuarios ({len(usuarios)})", len(usuarios) == 2)

        ayudante = next(u for u in usuarios if u["usuario"] == "ayudante")
        db.cambiar_rol_usuario(ayudante["id_usuario"], "admin")
        comprobar("Sube a alguien a administrador",
                  next(u for u in db.listar_usuarios()
                       if u["usuario"] == "ayudante")["rol"] == "admin")

        db.cambiar_estado_usuario(ayudante["id_usuario"], False)
        comprobar("Desactiva a un usuario",
                  not next(u for u in db.listar_usuarios()
                           if u["usuario"] == "ayudante")["activo"])

        # Con el ayudante desactivado, "jefe" es el único administrador vivo.
        jefe = next(u for u in db.listar_usuarios() if u["usuario"] == "jefe")
        try:
            db.cambiar_estado_usuario(jefe["id_usuario"], False)
            comprobar("Protege al último administrador activo", False)
        except ValueError:
            comprobar("Protege al último administrador activo", True)
        try:
            db.cambiar_rol_usuario(jefe["id_usuario"], "operador")
            comprobar("Tampoco deja quitarle el rol", False)
        except ValueError:
            comprobar("Tampoco deja quitarle el rol", True)

        print("\n--- Respaldo: db.respaldar / db.bytes_respaldo ---")
        with tempfile.TemporaryDirectory() as carpeta_resp:
            destino = Path(carpeta_resp) / "copia.db"
            ruta_devuelta = db.respaldar(destino)
            comprobar("db.respaldar devuelve la misma ruta que recibió",
                      ruta_devuelta == destino)
            comprobar("El archivo de respaldo existe y no está vacío",
                      destino.exists() and destino.stat().st_size > 0)

            con_copia = sqlite3.connect(destino)
            try:
                integro = con_copia.execute(
                    "PRAGMA integrity_check").fetchone()[0] == "ok"
            finally:
                con_copia.close()
            comprobar("El respaldo pasa integrity_check", integro)

            comprobar("El respaldo cuadra igual que la base original",
                      db.verificar_cuadre(destino) == db.verificar_cuadre())

            datos = db.bytes_respaldo()
            comprobar("bytes_respaldo empieza con el encabezado de SQLite",
                      datos[:16] == b"SQLite format 3\x00")
            comprobar("bytes_respaldo pesa lo mismo que el archivo de respaldar",
                      len(datos) == destino.stat().st_size)

        print("\n--- respaldos.py: crear y verificar ---")
        with tempfile.TemporaryDirectory() as carpeta_resp:
            carpeta_resp = Path(carpeta_resp)
            archivo = respaldos.crear(carpeta_resp)
            comprobar("crear() deja el archivo dentro de la carpeta pedida",
                      archivo.parent == carpeta_resp)
            comprobar("El nombre sigue el patrón esperado (fecha reconocible)",
                      respaldos._fecha_de_nombre(archivo) is not None)
            comprobar("verificar() confirma que un respaldo recién hecho es "
                      "de fiar", respaldos.verificar(archivo))

            corrupto = carpeta_resp / "corrupto.db.gz"
            corrupto.write_bytes(b"esto no es un respaldo valido")
            comprobar("verificar() da False (no truena) ante un archivo "
                      "corrupto", respaldos.verificar(corrupto) is False)

            comprobar("_fecha_de_nombre ignora un archivo que no sigue "
                      "el patrón",
                      respaldos._fecha_de_nombre(corrupto) is None)

        print("\n--- respaldos.py: rotar ---")
        with tempfile.TemporaryDirectory() as carpeta_resp:
            carpeta_resp = Path(carpeta_resp)
            # Nombres fabricados en vez de crear() de verdad espaciado en el
            # tiempo: la rotación decide por la fecha del NOMBRE, así que no
            # hace falta esperar semanas de reloj para probarla.
            base_original = respaldos.crear(carpeta_resp)
            contenido = base_original.read_bytes()
            base_original.unlink()

            fechas = [datetime(2026, 1, 1) + timedelta(days=2 * i)
                      for i in range(20)]  # 20 respaldos, cada 2 días
            for fecha in fechas:
                nombre = fecha.strftime(respaldos.PATRON_NOMBRE)
                (carpeta_resp / nombre).write_bytes(contenido)

            comprobar("Los 20 respaldos fabricados quedaron en la carpeta",
                      len(list(carpeta_resp.glob("taller-*.db.gz"))) == 20)

            borrados = respaldos.rotar(carpeta_resp, diarios=7, semanales=4)
            restantes = sorted(carpeta_resp.glob("taller-*.db.gz"))
            comprobar(f"Borra los que sobran y no más de diarios+semanales "
                      f"(quedaron {len(restantes)})",
                      len(restantes) <= 11 and len(borrados) == 20 - len(restantes))

            mas_recientes = sorted(
                (carpeta_resp / f.strftime(respaldos.PATRON_NOMBRE)
                 for f in fechas), reverse=True)[:7]
            comprobar("Los 7 respaldos más recientes sobreviven completos",
                      all(r in restantes for r in mas_recientes))

            intruso = carpeta_resp / "algo-que-alguien-dejo.db.gz"
            intruso.write_bytes(b"no es un respaldo de este script")
            respaldos.rotar(carpeta_resp, diarios=1, semanales=0)
            comprobar("Un archivo que no sigue el patrón de nombre no se "
                      "toca al rotar", intruso.exists())

        print("\n--- Límite de intentos de acceso ---")
        db.limpiar_intentos("jefe")
        db.limpiar_intentos("nadie-existe")
        maximo = config.max_intentos()

        for i in range(1, maximo + 1):
            db.registrar_intento_fallido("jefe")
        comprobar(f"Sin bloqueo hasta llegar al máximo ({maximo} intentos)",
                  db.segundos_de_bloqueo("jefe") == 0)

        db.registrar_intento_fallido("jefe")
        primera_espera = db.segundos_de_bloqueo("jefe")
        comprobar(f"Un intento de más sí bloquea (~30 s, dio {primera_espera})",
                  25 <= primera_espera <= 30)

        db.registrar_intento_fallido("jefe")
        segunda_espera = db.segundos_de_bloqueo("jefe")
        comprobar(f"El siguiente intento dobla la espera (~60 s, dio {segunda_espera})",
                  55 <= segunda_espera <= 60)

        # El punto entero del cambio: antes esto vivía en session_state, y
        # "recargar la página" (una `AppTest`/sesión nueva) lo reiniciaba.
        # Aquí no hay sesión de por medio: es una consulta a la base.
        comprobar("El bloqueo no depende de ninguna sesión abierta",
                  db.segundos_de_bloqueo("jefe") > 0)

        for _ in range(maximo + 1):
            db.registrar_intento_fallido("nadie-existe")
        espera_inexistente = db.segundos_de_bloqueo("nadie-existe")
        comprobar(
            "Un usuario que NO existe se bloquea igual que uno que sí "
            "(si no, el tiempo de espera delataría cuáles existen)",
            espera_inexistente > 0)

        comprobar("Normaliza mayúsculas y espacios a la misma llave",
                  db.segundos_de_bloqueo("  JEFE  ") == db.segundos_de_bloqueo("jefe"))

        db.limpiar_intentos("jefe")
        comprobar("limpiar_intentos borra el bloqueo",
                  db.segundos_de_bloqueo("jefe") == 0)
        db.limpiar_intentos("nadie-existe")

        print("\n--- Exportación con la estructura de la hoja del taller ---")
        libro = exportar.libro_original()
        comprobar("Genera un .xlsx válido", libro[:2] == b"PK")

        hojas = pd.read_excel(io.BytesIO(libro), sheet_name=None, header=None)
        comprobar("Trae las dos hojas del original, TC_TA y TSA",
                  list(hojas) == ["TC_TA", "TSA"])

        # La prueba que de verdad importa: que la columna D siga vacía. Es lo
        # único que separa las dos tablas de TC_TA, y si se pierde el archivo
        # deja de poder reimportarse.
        bloques = detectar_bloques(hojas["TC_TA"])
        comprobar(f"Deja la columna D vacía y separa las dos tablas {bloques}",
                  bloques == [(0, 2), (4, 11)])

        clientes_hoja = extraer_tabla(hojas["TC_TA"], *bloques[0])
        notas_hoja = extraer_tabla(hojas["TC_TA"], *bloques[1])
        servicios_hoja = extraer_tabla(
            hojas["TSA"], *detectar_bloques(hojas["TSA"])[0])

        comprobar("Los encabezados de clientes van literales",
                  list(clientes_hoja.columns)
                  == ["ID_Cliente (PK)", "Nombre", "Telefono"])
        comprobar("Los de notas también, con «Año» y «Tipo»",
                  list(notas_hoja.columns)
                  == ["ID_N (PK)", "ID_Cliente (FK)", "Fecha", "Marca",
                      "Año", "Tipo", "Color", "TOTAL"])
        comprobar("Y los de servicios, sin la columna ID_SA",
                  list(servicios_hoja.columns)
                  == ["ID_N (FK)", "Tipo De concepto", "Categoría", "Acción",
                      "Descripción", "Posición", "Lado", "Cantidad",
                      "Precio unitario", "Total", "Notas"])

        comprobar(f"Exporta todos los clientes ({len(clientes_hoja)})",
                  len(clientes_hoja) == len(db.listar_clientes()))
        comprobar(f"Exporta todas las notas ({len(notas_hoja)})",
                  len(notas_hoja) == len(db.listar_notas()))

        # El importe tiene que sobrevivir el viaje a pesos y de vuelta.
        total_hoja = db.pesos_a_centavos(str(notas_hoja["TOTAL"].sum()))
        comprobar(f"El TOTAL de la hoja cuadra con la base "
                  f"({db.formato_pesos(total_hoja)})",
                  total_hoja == db.verificar_cuadre()["total_notas_centavos"])

        # Los scripts de analisis/ estuvieron rotos sin que nadie se enterara:
        # consultaban `notas.marca`, columna que una migración se había
        # llevado a `vehiculos`. No fallaban al importarlos, solo al correrlos,
        # y nada los corría. Esto los ejercita.
        print("\n--- Los cargadores de analisis/ ---")
        sys.path.insert(0, str(Path(__file__).resolve().parent / "analisis"))
        import comun

        notas_analisis = comun.cargar_notas()
        comprobar("cargar_notas() corre y trae todas las notas",
                  len(notas_analisis) == len(db.listar_notas()))
        comprobar("Trae el vehículo desde su propia tabla",
                  {"marca", "anio", "modelo"} <= set(notas_analisis.columns))
        comprobar("Y el importe cuadra con la base",
                  int(notas_analisis["total_centavos"].sum())
                  == db.verificar_cuadre()["total_notas_centavos"])

        partidas_analisis = comun.cargar_partidas()
        comprobar("cargar_partidas() corre y trae fecha y marca",
                  {"fecha", "marca"} <= set(partidas_analisis.columns))

        # Una nota sin vehículo no puede desaparecer del análisis: con un JOIN
        # normal en vez de LEFT JOIN se caería, y los totales saldrían mal.
        suelta = db.crear_nota(
            id_cliente=id1, fecha="2025-11-30", id_vehiculo=None,
            partidas=[{"id_catalogo": None, "tipo_concepto": "Servicio",
                       "categoria": "Motor", "accion": "Reparación",
                       "descripcion": "Diagnóstico", "posicion": None,
                       "lado": None, "cantidad": 1,
                       "precio_unitario_centavos": 50000}],
        )
        con_suelta = comun.cargar_notas()
        comprobar("Una nota sin vehículo sigue contando en el análisis",
                  len(con_suelta) == len(notas_analisis) + 1
                  and con_suelta.loc[con_suelta["id_nota"] == suelta,
                                     "marca"].isna().all())
        db.eliminar_nota(suelta)

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
