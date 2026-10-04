import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2
from core.config import PG_CONNECTION_STRING

sql = (Path(__file__).resolve().parent.parent / "migrations" / "005_notificaciones.sql").read_text(encoding="utf-8")

with psycopg2.connect(PG_CONNECTION_STRING) as conn, conn.cursor() as cur:
    cur.execute(sql)

print("Migración 005 aplicada")