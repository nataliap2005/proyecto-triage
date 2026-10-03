# Ejecuta la migración 003 de vinculación de cuentas Paciente.
# Lee PG_CONNECTION_STRING desde back/pass.env, muestra cuántos pacientes
# están pendientes, aplica la migración y verifica el resultado.

from pathlib import Path
import os
import sys

import psycopg2
from dotenv import load_dotenv

BACK_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BACK_DIR / "pass.env"
MIGRATION_FILE = BACK_DIR / "migrations" / "003_vincular_cuentas_pacientes.sql"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE, override=True)

pg_connection_string = os.getenv("PG_CONNECTION_STRING")

if not pg_connection_string:
    raise RuntimeError("Falta PG_CONNECTION_STRING en back/pass.env")

if not MIGRATION_FILE.exists():
    raise FileNotFoundError(f"No existe la migración: {MIGRATION_FILE}")

sql = MIGRATION_FILE.read_text(encoding="utf-8")

CONSULTA_PENDIENTES = """
    SELECT COUNT(*)
    FROM pacientes p
    JOIN usuarios u
      ON u.numero_documento_usuario = p.numero_documento_paciente
    JOIN roles r
      ON r.id_rol = u.id_rol
    WHERE r.nombre = 'Paciente'
      AND u.is_deleted = FALSE
      AND u.estado = TRUE
      AND p.is_deleted = FALSE
      AND p.id_usuario IS NULL;
"""

CONSULTA_VINCULADOS = """
    SELECT COUNT(*)
    FROM pacientes p
    JOIN usuarios u
      ON u.numero_documento_usuario = p.id_usuario
    JOIN roles r
      ON r.id_rol = u.id_rol
    WHERE r.nombre = 'Paciente'
      AND p.numero_documento_paciente = u.numero_documento_usuario
      AND p.is_deleted = FALSE
      AND u.is_deleted = FALSE;
"""

print("Migración a ejecutar:")
print(f"  {MIGRATION_FILE}")
print()

conn = None

try:
    conn = psycopg2.connect(pg_connection_string)
    conn.autocommit = False

    with conn.cursor() as cur:
        cur.execute(CONSULTA_PENDIENTES)
        pendientes_antes = cur.fetchone()[0]

    conn.rollback()

    print(f"Pacientes pendientes de vincular: {pendientes_antes}")

    confirmacion = input(
        "¿Ejecutar migración 003 en la BD configurada? [s/N]: "
    ).strip().lower()

    if confirmacion not in {"s", "si", "sí", "y", "yes"}:
        print("Migración cancelada.")
        sys.exit(0)

    with conn.cursor() as cur:
        cur.execute(sql)

        cur.execute(CONSULTA_PENDIENTES)
        pendientes_despues = cur.fetchone()[0]

        cur.execute(CONSULTA_VINCULADOS)
        vinculados_total = cur.fetchone()[0]

        cur.execute("""
            SELECT pg_get_constraintdef(c.oid)
            FROM pg_constraint c
            WHERE c.conrelid='public.auditoria_cambios'::regclass
              AND c.conname='chk_auditoria_cambios_accion';
        """)
        constraint_def = cur.fetchone()

    conn.commit()

    if pendientes_despues != 0:
        raise RuntimeError(
            f"Quedaron {pendientes_despues} pacientes que deberían estar vinculados."
        )

    if not constraint_def or "VINCULAR_CUENTA" not in constraint_def[0]:
        raise RuntimeError(
            "La restricción de auditoría no quedó preparada para VINCULAR_CUENTA."
        )

    print("\n✅ Migración 003 aplicada correctamente.")
    print(f"✅ Vinculados en esta migración: {pendientes_antes}")
    print(f"✅ Total de pacientes con cuenta Paciente vinculada: {vinculados_total}")
    print("✅ Auditoría acepta la acción VINCULAR_CUENTA.")

except Exception as exc:
    if conn is not None:
        conn.rollback()
    print(f"\n❌ Error ejecutando la migración 003: {exc}")
    raise

finally:
    if conn is not None:
        conn.close()
