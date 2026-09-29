"""
Consulta de solo lectura para revisar el contenido actual de la base de datos.

Objetivos:
1. Mostrar cuántos registros hay en cada tabla pública.
2. Exportar los registros actuales de cada tabla a CSV.
3. Generar un resumen clínico por paciente con antecedentes, encuentros,
   diagnósticos, observaciones, exámenes y estudios PACS asociados.
4. Señalar exámenes que parecen corresponder a imagen diagnóstica y que aún
   no tienen un estudio PACS relacionado, sin tomar decisiones clínicas.

Este script NO modifica la base de datos.
"""

from __future__ import annotations

import csv
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv


# ---------------------------------------------------------------------
# Rutas y conexión
# ---------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
BACK_DIR = SCRIPT_DIR.parent
PASS_ENV = BACK_DIR / "pass.env"
OUTPUT_DIR = SCRIPT_DIR / "salida_registros_bd"

load_dotenv(PASS_ENV, override=True)
PG_CONNECTION_STRING = os.getenv("PG_CONNECTION_STRING")

if not PG_CONNECTION_STRING:
    raise ValueError(f"Falta PG_CONNECTION_STRING en {PASS_ENV}")


# Columnas que no aportan al análisis y no deben imprimirse/exportarse tal cual.
COLUMNAS_SENSIBLES = {
    "password_hash",
    "contrasena",
    "password",
    "token",
    "access_token",
    "refresh_token",
    "jwt",
    "jwt_secret",
}

# Solo se usa para marcar técnicamente exámenes cuyo nombre/categoría parece
# corresponder a imagen diagnóstica. NO significa que el paciente necesite
# una imagen por criterio clínico.
PATRON_IMAGEN = re.compile(
    r"\b("
    r"radiograf(?:ia|ía)|rayos?\s*x|rx|dx|cr|"
    r"tomograf(?:ia|ía)|tac|ct|"
    r"resonancia|rm|mri|mr|"
    r"ecograf(?:ia|ía)|ultrasonido|ultrasonograf(?:ia|ía)|us|"
    r"mamograf(?:ia|ía)|mg|"
    r"pet|pt|angiograf(?:ia|ía)|xa"
    r")\b",
    re.IGNORECASE,
)


def valor_seguro(columna: str, valor):
    """Oculta valores sensibles sin alterar la BD."""
    if columna.lower() in COLUMNAS_SENSIBLES:
        return "[OCULTO]"
    return valor


def imprimir_titulo(texto: str, caracter: str = "=") -> None:
    print("\n" + caracter * 90)
    print(texto)
    print(caracter * 90)


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
    return [fila["table_name"] for fila in cur.fetchall()]


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
    return [fila["column_name"] for fila in cur.fetchall()]


def exportar_tabla(cur, tabla: str) -> tuple[int, Path]:
    """Exporta una tabla a CSV, ocultando columnas sensibles."""
    columnas = obtener_columnas(cur, tabla)
    consulta = sql.SQL("SELECT * FROM {} ORDER BY 1;").format(sql.Identifier(tabla))
    cur.execute(consulta)
    filas = cur.fetchall()

    ruta = OUTPUT_DIR / f"{tabla}.csv"
    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        writer = csv.DictWriter(archivo, fieldnames=columnas)
        writer.writeheader()
        for fila in filas:
            writer.writerow({c: valor_seguro(c, fila.get(c)) for c in columnas})

    return len(filas), ruta


def existe_tabla(tablas: Iterable[str], nombre: str) -> bool:
    return nombre in set(tablas)


def obtener_lista(cur, consulta: str, parametros=()) -> list[dict]:
    cur.execute(consulta, parametros)
    return cur.fetchall()


def texto_o_guion(valor) -> str:
    if valor is None or valor == "":
        return "-"
    return str(valor)


def imprimir_items(titulo: str, items: list[dict], campos: list[tuple[str, str]]) -> None:
    print(f"\n  {titulo} ({len(items)})")
    if not items:
        print("    - Sin registros")
        return

    for item in items:
        partes = []
        for etiqueta, campo in campos:
            partes.append(f"{etiqueta}: {texto_o_guion(item.get(campo))}")
        print("    - " + " | ".join(partes))


def generar_resumen_pacientes(cur, tablas: list[str], ruta_txt: Path) -> None:
    """Genera resumen clínico legible y lo imprime además en consola."""
    cur.execute(
        """
        SELECT
            numero_documento_paciente,
            nombres,
            apellidos,
            fecha_nacimiento,
            genero_fhir,
            municipio_residencia,
            zona_residencia,
            id_usuario,
            is_deleted
        FROM pacientes
        ORDER BY numero_documento_paciente;
        """
    )
    pacientes = cur.fetchall()

    lineas: list[str] = []

    def guardar_y_mostrar(texto: str = "") -> None:
        print(texto)
        lineas.append(texto)

    imprimir_titulo("RESUMEN CLÍNICO POR PACIENTE")
    lineas.extend(["=" * 90, "RESUMEN CLÍNICO POR PACIENTE", "=" * 90])

    for paciente in pacientes:
        documento = paciente["numero_documento_paciente"]
        nombre = f'{paciente["nombres"]} {paciente["apellidos"]}'.strip()

        cabecera = f"PACIENTE {documento} - {nombre}"
        guardar_y_mostrar("\n" + "-" * 90)
        guardar_y_mostrar(cabecera)
        guardar_y_mostrar("-" * 90)
        guardar_y_mostrar(
            "Datos: "
            f"fecha_nacimiento={texto_o_guion(paciente['fecha_nacimiento'])} | "
            f"genero={texto_o_guion(paciente['genero_fhir'])} | "
            f"municipio={texto_o_guion(paciente['municipio_residencia'])} | "
            f"zona={texto_o_guion(paciente['zona_residencia'])} | "
            f"cuenta_usuario={texto_o_guion(paciente['id_usuario'])} | "
            f"eliminado={paciente['is_deleted']}"
        )

        # Antecedentes
        antecedentes = []
        if existe_tabla(tablas, "antecedentes"):
            antecedentes = obtener_lista(
                cur,
                """
                SELECT id_antecedente, tipo, codigo, descripcion, fecha_registro
                FROM antecedentes
                WHERE id_paciente = %s AND is_deleted = false
                ORDER BY fecha_registro, id_antecedente;
                """,
                (documento,),
            )

        # Reportes previos
        reportes = []
        if existe_tabla(tablas, "reportes_previos"):
            reportes = obtener_lista(
                cur,
                """
                SELECT id_reporte, fecha_hora_reporte, sintoma_principal,
                       signos_alarma_presentes, descripcion_signos_alarma,
                       orientacion_inicial
                FROM reportes_previos
                WHERE id_paciente = %s AND is_deleted = false
                ORDER BY fecha_hora_reporte, id_reporte;
                """,
                (documento,),
            )

        # Encuentros
        encuentros = obtener_lista(
            cur,
            """
            SELECT id_encuentro, fecha_hora_ingreso, fecha_hora_fin, estado,
                   motivo_consulta, nivel_triage, dolor_escala,
                   observaciones_triage, medico_responsable
            FROM encuentros
            WHERE id_paciente = %s AND is_deleted = false
            ORDER BY fecha_hora_ingreso, id_encuentro;
            """,
            (documento,),
        )

        # Diagnósticos del paciente vía encuentros
        diagnosticos = obtener_lista(
            cur,
            """
            SELECT d.id_diagnostico, d.id_encuentro, d.codigo_cie10,
                   d.descripcion, d.tipo, d.estado_clinico, d.fecha_diagnostico
            FROM diagnosticos d
            JOIN encuentros e ON e.id_encuentro = d.id_encuentro
            WHERE e.id_paciente = %s
              AND e.is_deleted = false
              AND d.is_deleted = false
            ORDER BY d.fecha_diagnostico, d.id_diagnostico;
            """,
            (documento,),
        )

        observaciones = obtener_lista(
            cur,
            """
            SELECT o.id_observacion, o.id_encuentro, o.tipo_observacion,
                   o.codigo_loinc, o.nombre, o.valor_numerico, o.valor_texto,
                   o.unidad, o.fecha_hora_observacion
            FROM observaciones o
            JOIN encuentros e ON e.id_encuentro = o.id_encuentro
            WHERE e.id_paciente = %s
              AND e.is_deleted = false
              AND o.is_deleted = false
            ORDER BY o.fecha_hora_observacion, o.id_observacion;
            """,
            (documento,),
        )

        examenes = obtener_lista(
            cur,
            """
            SELECT ex.id_examen, ex.id_encuentro, ex.codigo_loinc, ex.nombre,
                   ex.categoria, ex.estado, ex.resultado, ex.conclusion,
                   ex.fecha_solicitud, ex.fecha_resultado
            FROM examenes ex
            JOIN encuentros e ON e.id_encuentro = ex.id_encuentro
            WHERE e.id_paciente = %s
              AND e.is_deleted = false
              AND ex.is_deleted = false
            ORDER BY ex.fecha_solicitud, ex.id_examen;
            """,
            (documento,),
        )

        estudios = []
        if existe_tabla(tablas, "estudios_imagenes"):
            estudios = obtener_lista(
                cur,
                """
                SELECT id_estudio, id_encuentro, id_examen, modalidad,
                       descripcion, fecha_estudio, orthanc_study_id,
                       study_instance_uid
                FROM estudios_imagenes
                WHERE id_paciente = %s AND is_deleted = false
                ORDER BY COALESCE(fecha_estudio, created_at), id_estudio;
                """,
                (documento,),
            )

        # Escribir bloques al TXT y consola.
        def bloque(titulo, items, campos):
            guardar_y_mostrar(f"\n  {titulo} ({len(items)})")
            if not items:
                guardar_y_mostrar("    - Sin registros")
                return
            for item in items:
                partes = [f"{et}: {texto_o_guion(item.get(campo))}" for et, campo in campos]
                guardar_y_mostrar("    - " + " | ".join(partes))

        bloque(
            "ANTECEDENTES",
            antecedentes,
            [
                ("ID", "id_antecedente"),
                ("tipo", "tipo"),
                ("codigo", "codigo"),
                ("descripcion", "descripcion"),
            ],
        )
        bloque(
            "REPORTES PREVIOS",
            reportes,
            [
                ("ID", "id_reporte"),
                ("sintoma", "sintoma_principal"),
                ("alarma", "signos_alarma_presentes"),
                ("descripcion_alarma", "descripcion_signos_alarma"),
            ],
        )
        bloque(
            "ENCUENTROS",
            encuentros,
            [
                ("ID", "id_encuentro"),
                ("fecha", "fecha_hora_ingreso"),
                ("estado", "estado"),
                ("motivo", "motivo_consulta"),
                ("triage", "nivel_triage"),
                ("dolor", "dolor_escala"),
            ],
        )
        bloque(
            "DIAGNÓSTICOS / ENFERMEDADES REGISTRADAS",
            diagnosticos,
            [
                ("ID", "id_diagnostico"),
                ("encuentro", "id_encuentro"),
                ("CIE10", "codigo_cie10"),
                ("descripcion", "descripcion"),
                ("tipo", "tipo"),
                ("estado", "estado_clinico"),
            ],
        )
        bloque(
            "OBSERVACIONES",
            observaciones,
            [
                ("ID", "id_observacion"),
                ("encuentro", "id_encuentro"),
                ("nombre", "nombre"),
                ("valor", "valor_numerico"),
                ("texto", "valor_texto"),
                ("unidad", "unidad"),
                ("LOINC", "codigo_loinc"),
            ],
        )
        bloque(
            "EXÁMENES",
            examenes,
            [
                ("ID", "id_examen"),
                ("encuentro", "id_encuentro"),
                ("nombre", "nombre"),
                ("categoria", "categoria"),
                ("estado", "estado"),
                ("resultado", "resultado"),
                ("conclusion", "conclusion"),
            ],
        )
        bloque(
            "ESTUDIOS PACS YA ASOCIADOS",
            estudios,
            [
                ("ID", "id_estudio"),
                ("encuentro", "id_encuentro"),
                ("examen", "id_examen"),
                ("modalidad", "modalidad"),
                ("descripcion", "descripcion"),
            ],
        )

        # Exámenes que parecen de imagen y no tienen PACS todavía.
        ids_examen_con_pacs = {e["id_examen"] for e in estudios}
        candidatos = []
        for ex in examenes:
            texto = f"{ex.get('nombre') or ''} {ex.get('categoria') or ''}"
            if PATRON_IMAGEN.search(texto) and ex["id_examen"] not in ids_examen_con_pacs:
                candidatos.append(ex)

        bloque(
            "POSIBLES EXÁMENES DE IMAGEN SIN PACS (revisión técnica, no decisión clínica)",
            candidatos,
            [
                ("examen", "id_examen"),
                ("encuentro", "id_encuentro"),
                ("nombre", "nombre"),
                ("categoria", "categoria"),
                ("estado", "estado"),
            ],
        )

    ruta_txt.write_text("\n".join(lineas), encoding="utf-8")


def generar_csv_resumen_imagenes(cur, tablas: list[str], ruta: Path) -> None:
    """Lista exámenes por paciente y si ya tienen estudio PACS asociado."""
    tiene_pacs = existe_tabla(tablas, "estudios_imagenes")

    if tiene_pacs:
        consulta = """
            SELECT
                p.numero_documento_paciente AS documento,
                p.nombres,
                p.apellidos,
                e.id_encuentro,
                e.motivo_consulta,
                e.nivel_triage,
                d.codigo_cie10,
                d.descripcion AS diagnostico,
                ex.id_examen,
                ex.nombre AS examen,
                ex.categoria,
                ex.estado AS estado_examen,
                ei.id_estudio,
                ei.modalidad,
                ei.descripcion AS descripcion_estudio
            FROM pacientes p
            JOIN encuentros e
              ON e.id_paciente = p.numero_documento_paciente
             AND e.is_deleted = false
            LEFT JOIN diagnosticos d
              ON d.id_encuentro = e.id_encuentro
             AND d.is_deleted = false
            LEFT JOIN examenes ex
              ON ex.id_encuentro = e.id_encuentro
             AND ex.is_deleted = false
            LEFT JOIN estudios_imagenes ei
              ON ei.id_examen = ex.id_examen
             AND ei.is_deleted = false
            WHERE p.is_deleted = false
            ORDER BY p.numero_documento_paciente, e.id_encuentro, ex.id_examen;
        """
    else:
        consulta = """
            SELECT
                p.numero_documento_paciente AS documento,
                p.nombres,
                p.apellidos,
                e.id_encuentro,
                e.motivo_consulta,
                e.nivel_triage,
                d.codigo_cie10,
                d.descripcion AS diagnostico,
                ex.id_examen,
                ex.nombre AS examen,
                ex.categoria,
                ex.estado AS estado_examen,
                NULL::BIGINT AS id_estudio,
                NULL::VARCHAR AS modalidad,
                NULL::VARCHAR AS descripcion_estudio
            FROM pacientes p
            JOIN encuentros e
              ON e.id_paciente = p.numero_documento_paciente
             AND e.is_deleted = false
            LEFT JOIN diagnosticos d
              ON d.id_encuentro = e.id_encuentro
             AND d.is_deleted = false
            LEFT JOIN examenes ex
              ON ex.id_encuentro = e.id_encuentro
             AND ex.is_deleted = false
            WHERE p.is_deleted = false
            ORDER BY p.numero_documento_paciente, e.id_encuentro, ex.id_examen;
        """

    cur.execute(consulta)
    filas = cur.fetchall()

    campos = [
        "documento",
        "nombres",
        "apellidos",
        "id_encuentro",
        "motivo_consulta",
        "nivel_triage",
        "codigo_cie10",
        "diagnostico",
        "id_examen",
        "examen",
        "categoria",
        "estado_examen",
        "parece_imagen",
        "tiene_pacs",
        "id_estudio",
        "modalidad",
        "descripcion_estudio",
    ]

    with ruta.open("w", newline="", encoding="utf-8-sig") as archivo:
        writer = csv.DictWriter(archivo, fieldnames=campos)
        writer.writeheader()

        for fila in filas:
            texto_examen = f"{fila.get('examen') or ''} {fila.get('categoria') or ''}"
            salida = dict(fila)
            salida["parece_imagen"] = bool(PATRON_IMAGEN.search(texto_examen))
            salida["tiene_pacs"] = fila.get("id_estudio") is not None
            writer.writerow({campo: salida.get(campo) for campo in campos})


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("\nSISTEMA DE APOYO AL TRIAGE - REVISIÓN DE REGISTROS ACTUALES")
    print("Modo: SOLO LECTURA. El script no INSERTA, EDITA ni ELIMINA datos.")
    print(f"Salida: {OUTPUT_DIR}")

    conexion = psycopg2.connect(PG_CONNECTION_STRING)
    conexion.set_session(readonly=True, autocommit=False)

    try:
        with conexion.cursor(cursor_factory=RealDictCursor) as cur:
            imprimir_titulo("1. CONEXIÓN")
            cur.execute("SELECT current_database() AS bd, current_user AS usuario, now() AS fecha;")
            info = cur.fetchone()
            print(f"BD: {info['bd']} | usuario: {info['usuario']} | fecha: {info['fecha']}")

            tablas = obtener_tablas(cur)

            imprimir_titulo("2. REGISTROS POR TABLA")
            resumen_conteos = []
            for tabla in tablas:
                consulta = sql.SQL("SELECT COUNT(*) AS total FROM {};").format(sql.Identifier(tabla))
                cur.execute(consulta)
                total = cur.fetchone()["total"]
                resumen_conteos.append((tabla, total))
                print(f"{tabla:<30} {total:>6}")

            imprimir_titulo("3. EXPORTANDO TODAS LAS TABLAS A CSV")
            for tabla, _ in resumen_conteos:
                total, ruta = exportar_tabla(cur, tabla)
                print(f"{tabla}: {total} registros -> {ruta.name}")

            ruta_resumen = OUTPUT_DIR / "resumen_clinico_pacientes.txt"
            generar_resumen_pacientes(cur, tablas, ruta_resumen)

            ruta_imagenes = OUTPUT_DIR / "pacientes_examenes_y_pacs.csv"
            generar_csv_resumen_imagenes(cur, tablas, ruta_imagenes)

            imprimir_titulo("4. ARCHIVOS GENERADOS")
            print(f"Resumen clínico: {ruta_resumen}")
            print(f"Guía examen/PACS: {ruta_imagenes}")
            print(f"CSV de cada tabla: {OUTPUT_DIR}")
            print("\nIMPORTANTE:")
            print("- 'parece_imagen' solo revisa el texto del nombre/categoría del examen.")
            print("- No decide si clínicamente corresponde realizar una imagen.")
            print("- Para subir DICOM al PACS, prioriza registros que ya tengan un examen de imagen solicitado.")
            print("- No se modificó ningún dato de la base.")

        conexion.rollback()

    finally:
        conexion.close()


if __name__ == "__main__":
    main()
