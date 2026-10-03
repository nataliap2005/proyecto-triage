# Ejecuta la migración 004: roles, especialidades y remisiones.
from pathlib import Path
import os
import sys
import psycopg2
from dotenv import load_dotenv

BACK_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACK_DIR / "pass.env"
MIGRATION_FILE = BACK_DIR / "migrations" / "004_roles_especialidades_remisiones.sql"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

pg_connection_string = os.getenv("PG_CONNECTION_STRING")
if not pg_connection_string:
    raise RuntimeError("Falta PG_CONNECTION_STRING. Conserve su back/pass.env local o defina la variable de entorno.")

sql = MIGRATION_FILE.read_text(encoding="utf-8")
print(f"Migración a ejecutar: {MIGRATION_FILE}")
confirmacion = input("¿Ejecutar migración 004 en la BD configurada? [s/N]: ").strip().lower()
if confirmacion not in {"s","si","sí","y","yes"}:
    print("Migración cancelada.")
    sys.exit(0)

conn=None
try:
    conn=psycopg2.connect(pg_connection_string)
    conn.autocommit=False
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute("SELECT nombre FROM roles WHERE is_active=TRUE ORDER BY id_rol;")
        roles=[r[0] for r in cur.fetchall()]
        cur.execute("SELECT COUNT(*) FROM especialidades WHERE activo=TRUE;")
        n_especialidades=cur.fetchone()[0]
        cur.execute("SELECT to_regclass('public.remisiones');")
        remisiones=cur.fetchone()[0]
    conn.commit()
    esperados={"Admin","Medico","Especialista","Paciente","Contable"}
    if set(roles)!=esperados:
        raise RuntimeError(f"Roles activos inesperados: {roles}")
    if n_especialidades < 12:
        raise RuntimeError(f"Solo quedaron {n_especialidades} especialidades activas")
    if remisiones != 'remisiones':
        raise RuntimeError("No se creó la tabla remisiones")
    print("\n✅ Migración 004 aplicada correctamente.")
    print(f"✅ Roles activos: {', '.join(roles)}")
    print(f"✅ Especialidades activas: {n_especialidades}")
    print("✅ Tabla remisiones disponible.")
except Exception as exc:
    if conn is not None:
        conn.rollback()
    print(f"\n❌ Error ejecutando la migración 004: {exc}")
    raise
finally:
    if conn is not None:
        conn.close()
