# Script de ejecución de la migración PACS.
# Lee la conexión PostgreSQL desde pass.env, ejecuta la migración
# 002_pacs_estudios_imagenes.sql y verifica que la tabla estudios_imagenes
# haya sido creada correctamente antes de finalizar.
from pathlib import Path
import os
import sys

import psycopg2
from dotenv import load_dotenv

BACK_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACK_DIR / "pass.env"
MIGRATION_FILE = BACK_DIR / "migrations" / "002_pacs_estudios_imagenes.sql"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

pg_connection_string = os.getenv("PG_CONNECTION_STRING")

if not pg_connection_string:
    raise RuntimeError("Falta PG_CONNECTION_STRING en back/pass.env")

if not MIGRATION_FILE.exists():
    raise FileNotFoundError(f"No existe la migración: {MIGRATION_FILE}")

sql = MIGRATION_FILE.read_text(encoding="utf-8")

print("Migración a ejecutar:")
print(f"  {MIGRATION_FILE}")
print()

confirmacion = input("¿Ejecutar migración PACS en la BD configurada? [s/N]: ").strip().lower()

if confirmacion not in {"s", "si", "sí", "y", "yes"}:
    print("Migración cancelada.")
    sys.exit(0)

conn = None

try:
    conn = psycopg2.connect(pg_connection_string)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute(sql)

        cur.execute("""
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema='public'
                  AND table_name='estudios_imagenes'
            );
        """)
        existe = cur.fetchone()[0]

        cur.execute("""
            SELECT column_name,data_type,is_nullable
            FROM information_schema.columns
            WHERE table_schema='public'
              AND table_name='estudios_imagenes'
            ORDER BY ordinal_position;
        """)
        columnas = cur.fetchall()

    conn.commit()

    if not existe:
        raise RuntimeError("La migración terminó pero la tabla estudios_imagenes no fue encontrada.")

    print("\n✅ Migración aplicada correctamente.")
    print(f"✅ Tabla estudios_imagenes creada/verificada con {len(columnas)} columnas.")

    for nombre,tipo,nullable in columnas:
        print(f"   - {nombre}: {tipo} | nullable={nullable}")

except Exception as exc:
    if conn is not None:
        conn.rollback()
    print(f"\n❌ Error ejecutando la migración: {exc}")
    raise

finally:
    if conn is not None:
        conn.close()
