"""R27: cifra el teléfono y la dirección que ya estaban guardados en claro.

Desde la carpeta back/:
    python scripts/cifrar_datos_existentes_r27.py            solo cuenta, no cambia nada
    python scripts/cifrar_datos_existentes_r27.py --aplicar  cifra y guarda
    python scripts/cifrar_datos_existentes_r27.py --verificar comprueba que todo descifra

- Requiere la migración 017 aplicada y CIFRADO_LLAVE_K1 en pass.env.
- Se puede repetir sin riesgo: lo que ya está cifrado no se vuelve a cifrar.
- Todo ocurre en una sola transacción: si algo falla, no queda nada a medias.
- No toca la auditoría: los registros antiguos conservan su contenido, porque
  cambiarlos rompería la cadena de hashes de R28.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from core.cifrado import cifrar, descifrar, esta_cifrado
from core.config import PG_CONNECTION_STRING

# (tabla, columna de identificación, campo)
COLUMNAS = [
    ("pacientes", "numero_documento_paciente", "telefono"),
    ("pacientes", "numero_documento_paciente", "direccion"),
    ("usuarios", "numero_documento_usuario", "telefono"),
]


def main() -> int:
    aplicar = "--aplicar" in sys.argv
    verificar = "--verificar" in sys.argv
    cifrar("prueba", "telefono")  # falla aquí, antes de tocar nada, si falta la llave

    with psycopg2.connect(PG_CONNECTION_STRING) as conn, conn.cursor() as cur:
        for tabla, llave, campo in COLUMNAS:
            cur.execute(
                f"SELECT {llave}, {campo} FROM {tabla} "
                f"WHERE {campo} IS NOT NULL AND {campo} <> '' ORDER BY {llave} FOR UPDATE;"
            )
            filas = cur.fetchall()
            en_claro = [(ident, valor) for ident, valor in filas if not esta_cifrado(valor)]
            ya_cifradas = len(filas) - len(en_claro)

            if verificar:
                for ident, valor in filas:
                    if esta_cifrado(valor):
                        descifrar(valor, campo)  # lanza ErrorCifrado si no corresponde
                print(f"{tabla}.{campo}: {ya_cifradas} cifradas y verificadas, {len(en_claro)} en claro")
                continue

            if aplicar:
                for ident, valor in en_claro:
                    cur.execute(
                        f"UPDATE {tabla} SET {campo} = %s WHERE {llave} = %s;",
                        (cifrar(valor, campo), ident),
                    )
            print(f"{tabla}.{campo}: {ya_cifradas} ya cifradas, {len(en_claro)} en claro"
                  + (" -> cifradas ahora" if aplicar else ""))

        if not aplicar:
            conn.rollback()

    if not aplicar and not verificar:
        print("No se cambió nada. Para cifrar, repita con --aplicar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
