"""Crea usuarios SINTÉTICOS para probar remisiones y tiempo real.

- Idempotente: si el usuario ya existe, no se duplica ni se modifica.
- La contraseña se pide por teclado y se guarda con el mismo hash de la API (pwdlib).
- Los apellidos llevan "Prueba" para distinguirlos de usuarios reales.
"""
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core.config import PG_CONNECTION_STRING
from core.security import hash_password

USUARIOS = [
    {
        "documento": 1000000101,
        "username": "especialista.1000000101",
        "rol": "Especialista",
        "nombres": "Laura",
        "apellidos": "Cárdenas Prueba",
        "especialidades": [3, 8],   # Medicina Interna y Cardiología
    },
    {
        "documento": 1000000102,
        "username": "contable.1000000102",
        "rol": "Contable",
        "nombres": "Jorge",
        "apellidos": "Ortiz Prueba",
        "especialidades": [],
    },
]


def pedir_clave():
    while True:
        clave = getpass.getpass("Clave para los usuarios de prueba: ")
        if len(clave) < 8:
            print("Usa al menos 8 caracteres.")
        elif clave != getpass.getpass("Repítela: "):
            print("No coinciden, intenta de nuevo.")
        else:
            return clave


def main():
    hash_clave = hash_password(pedir_clave())

    conn = psycopg2.connect(PG_CONNECTION_STRING)
    try:
        with conn.cursor() as cur:
            for u in USUARIOS:
                cur.execute("""
                    INSERT INTO usuarios(
                        numero_documento_usuario, id_rol, username,
                        password_hash, nombres, apellidos
                    )
                    SELECT %s, id_rol, %s, %s, %s, %s
                    FROM roles WHERE nombre = %s
                    ON CONFLICT (numero_documento_usuario) DO NOTHING
                    RETURNING numero_documento_usuario;
                """, (u["documento"], u["username"], hash_clave,
                      u["nombres"], u["apellidos"], u["rol"]))
                creado = cur.fetchone() is not None
                print(("CREADO   " if creado else "YA EXISTÍA ") + f"{u['username']} ({u['rol']})")

                for id_esp in u["especialidades"]:
                    cur.execute("""
                        INSERT INTO usuario_especialidades(numero_documento_usuario, id_especialidad)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING;
                    """, (u["documento"], id_esp))
                if u["especialidades"]:
                    print(f"           especialidades: {u['especialidades']}")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()