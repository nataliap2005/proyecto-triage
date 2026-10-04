"""Aplica un archivo .sql de migrations/. Uso: python scripts/ejecutar_migracion.py 006_auditoria_origen_fhir.sql"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from core.config import PG_CONNECTION_STRING

archivo = Path(__file__).resolve().parent.parent / "migrations" / sys.argv[1]
sql = archivo.read_text(encoding="utf-8")

with psycopg2.connect(PG_CONNECTION_STRING) as conn, conn.cursor() as cur:
    cur.execute(sql)

print(f"Migración aplicada: {archivo.name}")