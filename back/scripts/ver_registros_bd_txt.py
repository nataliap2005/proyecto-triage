"""
Genera UN SOLO archivo TXT con el contenido actual de la base de datos.

- No imprime todos los registros en consola.
- No modifica la base de datos.
- Oculta columnas sensibles como password_hash y tokens.
- Incluye:
  1) resumen de tablas y cantidades,
  2) todos los registros por tabla,
  3) resumen clínico por paciente,
  4) exámenes de imagen y estado PACS cuando existen esas tablas.

Coloca este archivo dentro de: back/scripts/
Ejecuta desde la raíz del proyecto con:
    python back/scripts/ver_registros_bd_txt.py

Salida:
    back/scripts/reporte_bd_completo.txt
"""

from __future__ import annotations

import os
from pathlib import Path
from datetime import date, datetime

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


SCRIPT_DIR = Path(__file__).resolve().parent
BACK_DIR = SCRIPT_DIR.parent
PASS_ENV = BACK_DIR / "pass.env"
OUTPUT_FILE = SCRIPT_DIR / "reporte_bd_completo.txt"

load_dotenv(PASS_ENV, override=True)
PG_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING")

if not PG_CONNECTION_STRING:
    raise ValueError(f"Falta PG_CONNECTION_STRING en {PASS_ENV}")

COLUMNAS_SENSIBLES = {
    "password_hash",
    "password",
    "contrasena",
    "token",
    "access_token",
    "refresh_token",
    "jwt",
    "jwt_secret",
    "secret",
}


def seguro(nombre: str, valor):
    if nombre.lower() in COLUMNAS_SENSIBLES:
        return "[OCULTO]"
    if isinstance(valor, (datetime, date)):
        return valor.isoformat(sep=" ") if isinstance(valor, datetime) else valor.isoformat()
    return valor


def txt(valor) -> str:
    if valor is None or valor == "":
        return "-"
    return str(valor).replace("\n", " ").replace("\r", " ")


def obtener_tablas(cur) -> list[str]:
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
    )
    return [r["table_name"] for r in cur.fetchall()]


def obtener_columnas(cur, tabla: str) -> list[str]:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = %s
        ORDER BY ordinal_position;
        """,
        (tabla,),
    )
    return [r["column_name"] for r in cur.fetchall()]


def existe(tablas: list[str], nombre: str) -> bool:
    return nombre in tablas


def escribir_todos_los_registros(cur, tablas: list[str], out) -> None:
    out.write("\n" + "=" * 110 + "\n")
    out.write("TODOS LOS REGISTROS ACTUALES DE LA BASE DE DATOS\n")
    out.write("=" * 110 + "\n")

    for tabla in tablas:
        columnas = obtener_columnas(cur, tabla)
        cur.execute(sql.SQL("SELECT * FROM {} ORDER BY 1;").format(sql.Identifier(tabla)))
        filas = cur.fetchall()

        out.write("\n" + "-" * 110 + "\n")
        out.write(f"TABLA: {tabla} | TOTAL: {len(filas)}\n")
        out.write("-" * 110 + "\n")

        if not filas:
            out.write("Sin registros.\n")
            continue

        for i, fila in enumerate(filas, 1):
            out.write(f"\n[{i}]\n")
            for col in columnas:
                out.write(f"  {col}: {txt(seguro(col, fila.get(col)))}\n")


def escribir_resumen_clinico(cur, tablas: list[str], out) -> None:
    necesarias = {"pacientes", "encuentros"}
    if not necesarias.issubset(set(tablas)):
        out.write("\nNo se pudo generar resumen clínico: faltan tablas pacientes/encuentros.\n")
        return

    out.write("\n" + "=" * 110 + "\n")
    out.write("RESUMEN CLÍNICO POR PACIENTE\n")
    out.write("=" * 110 + "\n")

    cur.execute("SELECT * FROM pacientes ORDER BY numero_documento_paciente;")
    pacientes = cur.fetchall()

    for p in pacientes:
        doc = p.get("numero_documento_paciente")
        nombre = " ".join(filter(None, [p.get("nombres"), p.get("apellidos")]))

        out.write("\n" + "#" * 110 + "\n")
        out.write(f"PACIENTE: {doc} - {nombre or '-'}\n")
        out.write("#" * 110 + "\n")

        # Encuentros
        cur.execute(
            """
            SELECT *
            FROM encuentros
            WHERE id_paciente = %s
              AND COALESCE(is_deleted, false) = false
            ORDER BY id_encuentro;
            """,
            (doc,),
        )
        encuentros = cur.fetchall()
        out.write(f"\nENCUENTROS ({len(encuentros)})\n")
        for e in encuentros:
            out.write(
                "  - "
                f"ID={txt(e.get('id_encuentro'))} | "
                f"motivo={txt(e.get('motivo_consulta'))} | "
                f"triage={txt(e.get('nivel_triage'))} | "
                f"estado={txt(e.get('estado'))} | "
                f"ingreso={txt(e.get('fecha_hora_ingreso'))}\n"
            )

        # Diagnósticos
        if existe(tablas, "diagnosticos"):
            cur.execute(
                """
                SELECT d.*
                FROM diagnosticos d
                JOIN encuentros e ON e.id_encuentro = d.id_encuentro
                WHERE e.id_paciente = %s
                  AND COALESCE(e.is_deleted, false) = false
                  AND COALESCE(d.is_deleted, false) = false
                ORDER BY d.id_diagnostico;
                """,
                (doc,),
            )
            filas = cur.fetchall()
            out.write(f"\nDIAGNÓSTICOS / ENFERMEDADES ({len(filas)})\n")
            for r in filas:
                out.write(
                    "  - "
                    f"ID={txt(r.get('id_diagnostico'))} | "
                    f"encuentro={txt(r.get('id_encuentro'))} | "
                    f"CIE10={txt(r.get('codigo_cie10'))} | "
                    f"descripcion={txt(r.get('descripcion'))} | "
                    f"tipo={txt(r.get('tipo'))} | "
                    f"estado={txt(r.get('estado_clinico'))}\n"
                )

        # Antecedentes
        if existe(tablas, "antecedentes"):
            cur.execute(
                """
                SELECT * FROM antecedentes
                WHERE id_paciente = %s
                  AND COALESCE(is_deleted, false) = false
                ORDER BY id_antecedente;
                """,
                (doc,),
            )
            filas = cur.fetchall()
            out.write(f"\nANTECEDENTES ({len(filas)})\n")
            for r in filas:
                out.write(
                    "  - "
                    f"tipo={txt(r.get('tipo'))} | "
                    f"codigo={txt(r.get('codigo'))} | "
                    f"descripcion={txt(r.get('descripcion'))}\n"
                )

        # Reportes previos
        if existe(tablas, "reportes_previos"):
            cur.execute(
                """
                SELECT * FROM reportes_previos
                WHERE id_paciente = %s
                  AND COALESCE(is_deleted, false) = false
                ORDER BY id_reporte;
                """,
                (doc,),
            )
            filas = cur.fetchall()
            out.write(f"\nREPORTES PREVIOS ({len(filas)})\n")
            for r in filas:
                out.write(
                    "  - "
                    f"ID={txt(r.get('id_reporte'))} | "
                    f"síntoma={txt(r.get('sintoma_principal'))} | "
                    f"signos_alarma={txt(r.get('signos_alarma_presentes'))} | "
                    f"orientacion={txt(r.get('orientacion_inicial'))}\n"
                )

        # Exámenes + PACS
        if existe(tablas, "examenes"):
            if existe(tablas, "estudios_imagenes"):
                cur.execute(
                    """
                    SELECT
                        ex.id_examen,
                        ex.id_encuentro,
                        ex.codigo_loinc,
                        ex.nombre,
                        ex.categoria,
                        ex.estado,
                        ex.resultado,
                        ex.conclusion,
                        ei.id_estudio,
                        ei.modalidad,
                        ei.descripcion AS descripcion_estudio,
                        ei.orthanc_study_id
                    FROM examenes ex
                    JOIN encuentros e ON e.id_encuentro = ex.id_encuentro
                    LEFT JOIN estudios_imagenes ei
                      ON ei.id_examen = ex.id_examen
                     AND COALESCE(ei.is_deleted, false) = false
                    WHERE e.id_paciente = %s
                      AND COALESCE(e.is_deleted, false) = false
                      AND COALESCE(ex.is_deleted, false) = false
                    ORDER BY ex.id_examen, ei.id_estudio;
                    """,
                    (doc,),
                )
            else:
                cur.execute(
                    """
                    SELECT
                        ex.id_examen,
                        ex.id_encuentro,
                        ex.codigo_loinc,
                        ex.nombre,
                        ex.categoria,
                        ex.estado,
                        ex.resultado,
                        ex.conclusion,
                        NULL::BIGINT AS id_estudio,
                        NULL::TEXT AS modalidad,
                        NULL::TEXT AS descripcion_estudio,
                        NULL::TEXT AS orthanc_study_id
                    FROM examenes ex
                    JOIN encuentros e ON e.id_encuentro = ex.id_encuentro
                    WHERE e.id_paciente = %s
                      AND COALESCE(e.is_deleted, false) = false
                      AND COALESCE(ex.is_deleted, false) = false
                    ORDER BY ex.id_examen;
                    """,
                    (doc,),
                )

            filas = cur.fetchall()
            out.write(f"\nEXÁMENES Y PACS ({len(filas)})\n")
            if not filas:
                out.write("  - Sin exámenes registrados.\n")
            for r in filas:
                out.write(
                    "  - "
                    f"examen={txt(r.get('id_examen'))} | "
                    f"encuentro={txt(r.get('id_encuentro'))} | "
                    f"nombre={txt(r.get('nombre'))} | "
                    f"categoria={txt(r.get('categoria'))} | "
                    f"estado={txt(r.get('estado'))} | "
                    f"PACS={'SI' if r.get('id_estudio') is not None else 'NO'} | "
                    f"modalidad={txt(r.get('modalidad'))} | "
                    f"estudio_pacs={txt(r.get('id_estudio'))}\n"
                )


def main() -> None:
    conexion = psycopg2.connect(PG_CONNECTION_STRING)
    conexion.set_session(readonly=True, autocommit=False)

    try:
        with conexion.cursor(cursor_factory=RealDictCursor) as cur, OUTPUT_FILE.open(
            "w", encoding="utf-8"
        ) as out:
            cur.execute(
                "SELECT current_database() AS bd, current_user AS usuario, now() AS fecha;"
            )
            info = cur.fetchone()

            out.write("SISTEMA DE APOYO AL TRIAGE - REPORTE COMPLETO DE BASE DE DATOS\n")
            out.write("=" * 110 + "\n")
            out.write("MODO: SOLO LECTURA. ESTE SCRIPT NO MODIFICA LA BASE DE DATOS.\n")
            out.write(f"Base de datos: {info['bd']}\n")
            out.write(f"Usuario BD: {info['usuario']}\n")
            out.write(f"Fecha del reporte: {info['fecha']}\n")

            tablas = obtener_tablas(cur)

            out.write("\n" + "=" * 110 + "\n")
            out.write("RESUMEN DE TABLAS\n")
            out.write("=" * 110 + "\n")
            for tabla in tablas:
                cur.execute(
                    sql.SQL("SELECT COUNT(*) AS total FROM {};").format(sql.Identifier(tabla))
                )
                total = cur.fetchone()["total"]
                out.write(f"{tabla}: {total}\n")

            escribir_todos_los_registros(cur, tablas, out)
            escribir_resumen_clinico(cur, tablas, out)

        conexion.rollback()
        print(f"✅ Reporte generado: {OUTPUT_FILE}")

    finally:
        conexion.close()


if __name__ == "__main__":
    main()
