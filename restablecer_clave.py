"""
Restablecer la contraseña de un usuario — Auto Servicio Bautista.

Para cuando nadie puede entrar a la aplicación. Genera una contraseña nueva
(o fija la que le indiques) y la deja lista para usar.

La única credencial que exige es el acceso a esta computadora y a la base:
quien pueda ejecutar este script ya tiene el archivo `taller.db` en sus manos.
Por eso la base no debe salir de aquí ni subirse a ningún repositorio.

Uso:
    .venv\\Scripts\\python.exe restablecer_clave.py                    (lista usuarios)
    .venv\\Scripts\\python.exe restablecer_clave.py admin              (clave nueva al azar)
    .venv\\Scripts\\python.exe restablecer_clave.py admin --clave MiClave123

Se recomienda usar la forma sin `--clave` y dejar que genere una al azar:
una contraseña pasada como argumento queda en el historial de la terminal
(`Get-History`, `.bash_history`) en texto plano. `--clave` existe para
cuando de verdad hace falta fijar una en concreto.
"""

from __future__ import annotations

import argparse
import sys

import auth
import db

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LARGO_MINIMO = 8


def listar() -> None:
    usuarios = db.listar_usuarios()
    if not usuarios:
        print("No hay usuarios registrados. Corre cargar_datos.py para crear "
              "el administrador inicial.")
        return
    print("Usuarios registrados:\n")
    for u in usuarios:
        estado = "activo" if u["activo"] else "DESACTIVADO"
        print(f"  {u['usuario']:<16} {u['rol']:<10} {estado:<12} "
              f"último acceso: {u['ultimo_acceso'] or 'nunca'}")
    print("\nPara restablecer:  .venv\\Scripts\\python.exe "
          "restablecer_clave.py <usuario>")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Restablece la contraseña de un usuario.")
    parser.add_argument("usuario", nargs="?",
                        help="Usuario a restablecer. Sin esto solo lista.")
    parser.add_argument("--clave",
                        help="Contraseña a fijar. Si se omite (recomendado), "
                             "se genera una al azar: pasarla aquí la deja en "
                             "el historial de la terminal.")
    parser.add_argument("--activar", action="store_true",
                        help="Reactiva el usuario si estaba desactivado.")
    args = parser.parse_args()

    if not db.RUTA_DB.exists():
        raise SystemExit("No existe taller.db. Corre primero cargar_datos.py")

    if not args.usuario:
        listar()
        return

    with db.conectar() as conexion:
        fila = conexion.execute(
            "SELECT id_usuario, usuario, rol, activo FROM usuarios WHERE usuario = ?",
            (args.usuario,),
        ).fetchone()

    if fila is None:
        print(f"No existe el usuario «{args.usuario}».\n")
        listar()
        sys.exit(1)

    clave = args.clave or auth.generar_password()
    if len(clave) < LARGO_MINIMO:
        raise SystemExit(
            f"La contraseña debe tener al menos {LARGO_MINIMO} caracteres.")

    with db.transaccion() as conexion:
        auth.cambiar_password(conexion, fila["id_usuario"], clave)
        if args.activar and not fila["activo"]:
            conexion.execute(
                "UPDATE usuarios SET activo = 1 WHERE id_usuario = ?",
                (fila["id_usuario"],),
            )

    # Se comprueba de verdad contra la base en vez de dar por hecho que quedó:
    # el motivo de existir de este script es que una contraseña dejó de servir.
    with db.conectar() as conexion:
        verificada = auth.autenticar(conexion, args.usuario, clave) is not None

    print("=" * 66)
    if verificada:
        print(f"Contraseña restablecida para «{fila['usuario']}» ({fila['rol']}):")
        print()
        print(f"    usuario    : {fila['usuario']}")
        print(f"    contraseña : {clave}")
        print()
        print("Comprobada contra la base: con estos datos sí entra.")
        print("Cámbiala desde la app en cuanto puedas.")
    else:
        print("ALGO SALIÓ MAL: la contraseña se guardó pero no verifica.")
    print("=" * 66)
    sys.exit(0 if verificada else 1)


if __name__ == "__main__":
    main()
