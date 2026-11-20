"""R27: muestra cómo queda guardado un paciente en PostgreSQL y cómo lo ve la API.

Desde la carpeta back/:
    python scripts/evidencia_r27.py                      primer paciente activo
    python scripts/evidencia_r27.py --documento 1156640927

Solo lee. Sirve como evidencia y para la demostración en la sustentación:
primero se crea un paciente en la app y luego se corre este script con su documento.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core import identidad
from core.cifrado import descifrar, esta_cifrado
from core.config import PG_CONNECTION_STRING


def main() -> int:
    documento = None
    if "--documento" in sys.argv:
        documento = int(sys.argv[sys.argv.index("--documento") + 1])

    with psycopg2.connect(PG_CONNECTION_STRING) as conn, conn.cursor() as cur:
        if documento is None:
            cur.execute("SELECT numero_documento_paciente FROM pacientes "
                        "WHERE is_deleted = FALSE AND telefono IS NOT NULL ORDER BY created_at LIMIT 1;")
            interno = cur.fetchone()[0]
        else:
            interno = identidad.interno(documento)

        cur.execute("SELECT numero_documento_paciente, nombres, telefono, direccion "
                    "FROM pacientes WHERE numero_documento_paciente = %s;", (interno,))
        fila = cur.fetchone()
        if not fila:
            print("No hay un paciente con ese documento.")
            return 1
        _, nombres, telefono, direccion = fila
        cur.execute("SELECT documento_cifrado FROM identidades WHERE id_interno = %s;", (interno,))
        boveda = cur.fetchone()[0]

        print("=== 1. Lo que hay guardado en PostgreSQL (lo que vería quien robe la base) ===")
        print(f"pacientes.numero_documento_paciente : {interno}   (número interno, no es el documento)")
        print(f"pacientes.telefono                  : {telefono}")
        print(f"pacientes.direccion                 : {direccion}")
        print(f"identidades.documento_cifrado       : {boveda}")
        print()
        print("=== 2. Lo mismo descifrado con la llave CIFRADO_LLAVE_K1 (lo que muestra la API) ===")
        print(f"documento : {descifrar(boveda, identidad.CONTEXTO)}")
        print(f"nombre    : {nombres}")
        print(f"telefono  : {descifrar(telefono, 'telefono')}")
        print(f"direccion : {descifrar(direccion, 'direccion')}")
        print()

        print("=== 3. Resumen de toda la base ===")
        for tabla, col in (("pacientes", "numero_documento_paciente"), ("usuarios", "numero_documento_usuario")):
            cur.execute(f"SELECT {col} FROM {tabla};")
            valores = [v for (v,) in cur.fetchall()]
            en_claro = sum(1 for v in valores if not identidad.es_interno(v))
            print(f"{tabla}: {len(valores)} filas, documentos en claro: {en_claro}")
        for tabla, campo in (("pacientes", "telefono"), ("pacientes", "direccion"), ("usuarios", "telefono")):
            cur.execute(f"SELECT {campo} FROM {tabla} WHERE {campo} IS NOT NULL AND {campo} <> '';")
            valores = [v for (v,) in cur.fetchall()]
            en_claro = sum(1 for v in valores if not esta_cifrado(v))
            print(f"{tabla}.{campo}: {len(valores)} con dato, en claro: {en_claro}")
        cur.execute("SELECT count(*) FROM identidades;")
        print(f"identidades (bóveda): {cur.fetchone()[0]} documentos cifrados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
