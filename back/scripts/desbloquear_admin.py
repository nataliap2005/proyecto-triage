# Script de recuperación administrativa.
# Se usa únicamente en casos extremos cuando un usuario Admin
# queda bloqueado y no puede ser desbloqueado desde la API.

import os

import psycopg2
from dotenv import load_dotenv

load_dotenv("pass.env",override=True)

PG_CONNECTION_STRING=os.getenv("PG_CONNECTION_STRING")

if not PG_CONNECTION_STRING:
    raise ValueError("Falta PG_CONNECTION_STRING en pass.env")


username=input("Username del Admin a desbloquear: ").strip()

confirmacion=input(
    f"¿Seguro que desea desbloquear al usuario '{username}'? (si/no): "
).strip().lower()

if confirmacion!="si":
    print("Operación cancelada.")
    raise SystemExit


conexion=psycopg2.connect(PG_CONNECTION_STRING)
cursor=conexion.cursor()

try:
    cursor.execute("""
        SELECT
            u.numero_documento_usuario,
            u.username,
            r.nombre AS rol,
            u.bloqueado,
            u.intentos_fallidos
        FROM usuarios u
        JOIN roles r ON r.id_rol=u.id_rol
        WHERE u.username=%s;
    """,(username,))

    usuario=cursor.fetchone()

    if not usuario:
        print("Usuario no encontrado.")
        raise SystemExit

    if usuario[2]!="Admin":
        print("El usuario existe, pero no tiene rol Admin.")
        raise SystemExit

    cursor.execute("""
        UPDATE usuarios
        SET intentos_fallidos=0,
            bloqueado=false,
            bloqueado_at=NULL,
            updated_at=now()
        WHERE username=%s
        RETURNING username,bloqueado,intentos_fallidos;
    """,(username,))

    actualizado=cursor.fetchone()

    conexion.commit()

    print("\nAdmin desbloqueado correctamente.")
    print("Usuario:",actualizado[0])
    print("Bloqueado:",actualizado[1])
    print("Intentos fallidos:",actualizado[2])

except Exception:
    conexion.rollback()
    raise

finally:
    cursor.close()
    conexion.close()