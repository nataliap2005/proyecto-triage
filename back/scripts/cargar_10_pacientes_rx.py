"""
Crea 10 pacientes sintéticos con casos de urgencias que requieren radiografía.

- NO crea cuentas de usuario para los pacientes.
- NO sube imágenes DICOM.
- Deja un examen de imagen en estado "active" para que luego se cargue
  el DICOM desde el frontend y quede relacionado con paciente/encuentro/examen.
- Usa médicos ya existentes en la base.
- Es idempotente por número de documento: si un paciente ya existe, lo omite.
- Ejecuta todo dentro de una transacción.
- Genera un TXT resumen con los IDs creados para facilitar la carga desde el front.

Ejecutar desde la raíz del proyecto:
    python back/scripts/cargar_10_pacientes_rx.py

Requiere que back/pass.env contenga PG_CONNECTION_STRING.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import psycopg2
from psycopg2.extras import RealDictCursor


ROOT = Path(__file__).resolve().parents[2]
BACK = ROOT / "back"
PASS_ENV = BACK / "pass.env"
SALIDA = Path(__file__).resolve().parent / "pacientes_rx_creados.txt"

MEDICOS = [
    1006713773,
    1073827621,
    1059917677,
    1197694986,
]

# Documentos reservados exclusivamente para estos datos sintéticos.
# No se crean usuarios: id_usuario queda NULL.
CASOS = [
    {
        "documento": 1200001001,
        "nombres": "Mateo",
        "apellidos": "Riascos Mina",
        "fecha_nacimiento": "1998-05-14",
        "genero": "male",
        "telefono": "+57 310 555 1101",
        "direccion": "Barrio Ciudadela",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Caída con dolor intenso y deformidad en muñeca derecha",
        "triage": 3,
        "dolor": 8,
        "cie10": "S69.9",
        "diagnostico": "Traumatismo de muñeca y mano, con sospecha de fractura",
        "examen": "Radiografía de muñeca derecha",
        "modalidad": "DX/CR",
        "region": "Muñeca",
        "antecedentes": [],
        "vitales": {"temp": 36.7, "fc": 96, "spo2": 98, "pas": 126, "pad": 78},
    },
    {
        "documento": 1200001002,
        "nombres": "Valentina",
        "apellidos": "Caicedo Angulo",
        "fecha_nacimiento": "2002-11-02",
        "genero": "female",
        "telefono": "+57 310 555 1102",
        "direccion": "Vereda Chilví",
        "municipio": "Tumaco",
        "zona": "rural_dispersa",
        "motivo": "Trauma de tobillo izquierdo con edema e incapacidad para apoyar",
        "triage": 3,
        "dolor": 9,
        "cie10": "S99.9",
        "diagnostico": "Traumatismo de tobillo y pie, con sospecha de lesión ósea",
        "examen": "Radiografía de tobillo izquierdo",
        "modalidad": "DX/CR",
        "region": "Tobillo",
        "antecedentes": [],
        "vitales": {"temp": 36.6, "fc": 102, "spo2": 99, "pas": 119, "pad": 74},
        "reporte_previo": {
            "sintoma": "Dolor y edema en tobillo tras caída",
            "evolucion": "Dolor progresivo e imposibilidad para apoyar el pie",
            "alarma": False,
            "descripcion_alarma": None,
            "ubicacion": "Vereda Chilví",
            "distancia": 18.5,
            "tiempo": 45,
            "orientacion": "Evitar apoyo del miembro y acudir a urgencias para valoración.",
        },
    },
    {
        "documento": 1200001003,
        "nombres": "Samuel",
        "apellidos": "Quiñones Castillo",
        "fecha_nacimiento": "1987-03-21",
        "genero": "male",
        "telefono": "+57 310 555 1103",
        "direccion": "Barrio Obrero",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Golpe directo en tórax con dolor al respirar",
        "triage": 2,
        "dolor": 8,
        "cie10": "S29.9",
        "diagnostico": "Traumatismo de tórax, con sospecha de lesión costal",
        "examen": "Radiografía de tórax",
        "modalidad": "DX/CR",
        "region": "Tórax",
        "antecedentes": [("toxico", None, "Tabaquismo activo")],
        "vitales": {"temp": 36.8, "fc": 108, "spo2": 94, "pas": 132, "pad": 84},
    },
    {
        "documento": 1200001004,
        "nombres": "Isabella",
        "apellidos": "Preciado Mosquera",
        "fecha_nacimiento": "1994-08-09",
        "genero": "female",
        "telefono": "+57 310 555 1104",
        "direccion": "Barrio Miramar",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Dolor y limitación funcional de hombro después de caída",
        "triage": 3,
        "dolor": 7,
        "cie10": "S49.9",
        "diagnostico": "Traumatismo de hombro y brazo, con sospecha de luxación o fractura",
        "examen": "Radiografía de hombro derecho",
        "modalidad": "DX/CR",
        "region": "Hombro",
        "antecedentes": [],
        "vitales": {"temp": 36.5, "fc": 92, "spo2": 99, "pas": 116, "pad": 72},
    },
    {
        "documento": 1200001005,
        "nombres": "Daniel",
        "apellidos": "Valencia Cortés",
        "fecha_nacimiento": "1971-12-17",
        "genero": "male",
        "telefono": "+57 310 555 1105",
        "direccion": "Corregimiento La Guayacana",
        "municipio": "Tumaco",
        "zona": "rural_dispersa",
        "motivo": "Caída sobre rodilla con edema, dolor e imposibilidad para caminar",
        "triage": 3,
        "dolor": 9,
        "cie10": "S89.9",
        "diagnostico": "Traumatismo de pierna y rodilla, con sospecha de fractura",
        "examen": "Radiografía de rodilla izquierda",
        "modalidad": "DX/CR",
        "region": "Rodilla",
        "antecedentes": [("patologico", "I10", "Hipertensión arterial diagnosticada")],
        "vitales": {"temp": 36.9, "fc": 98, "spo2": 97, "pas": 148, "pad": 91},
        "reporte_previo": {
            "sintoma": "Dolor intenso de rodilla después de caída",
            "evolucion": "Aumento del edema y dificultad para movilizar la pierna",
            "alarma": False,
            "descripcion_alarma": None,
            "ubicacion": "Corregimiento La Guayacana",
            "distancia": 82.0,
            "tiempo": 110,
            "orientacion": "Inmovilizar el miembro y acudir a urgencias.",
        },
    },
    {
        "documento": 1200001006,
        "nombres": "Mariana",
        "apellidos": "Grueso Estupiñán",
        "fecha_nacimiento": "1949-04-26",
        "genero": "female",
        "telefono": "+57 310 555 1106",
        "direccion": "Barrio Nuevo Milenio",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Dolor intenso en cadera después de caída, no puede ponerse de pie",
        "triage": 2,
        "dolor": 10,
        "cie10": "S79.9",
        "diagnostico": "Traumatismo de cadera y muslo, con sospecha de fractura proximal de fémur",
        "examen": "Radiografía de pelvis y cadera",
        "modalidad": "DX/CR",
        "region": "Pelvis/Cadera",
        "antecedentes": [
            ("patologico", "I10", "Hipertensión arterial diagnosticada"),
            ("patologico", "E11", "Diabetes mellitus tipo 2"),
        ],
        "vitales": {"temp": 36.4, "fc": 110, "spo2": 96, "pas": 154, "pad": 88},
    },
    {
        "documento": 1200001007,
        "nombres": "Nicolás",
        "apellidos": "Cabezas Hurtado",
        "fecha_nacimiento": "2005-01-30",
        "genero": "male",
        "telefono": "+57 310 555 1107",
        "direccion": "Barrio Panamá",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Golpe en mano derecha durante actividad deportiva con dolor en quinto dedo",
        "triage": 4,
        "dolor": 6,
        "cie10": "S69.9",
        "diagnostico": "Traumatismo de mano y dedo, con sospecha de fractura",
        "examen": "Radiografía de mano derecha",
        "modalidad": "DX/CR",
        "region": "Mano",
        "antecedentes": [],
        "vitales": {"temp": 36.6, "fc": 84, "spo2": 99, "pas": 113, "pad": 69},
    },
    {
        "documento": 1200001008,
        "nombres": "Laura",
        "apellidos": "Sinisterra Perlaza",
        "fecha_nacimiento": "1983-07-11",
        "genero": "female",
        "telefono": "+57 310 555 1108",
        "direccion": "Vereda Inguapí del Carmen",
        "municipio": "Tumaco",
        "zona": "rural_dispersa",
        "motivo": "Fiebre, tos productiva y dificultad respiratoria",
        "triage": 2,
        "dolor": 3,
        "cie10": "J18.9",
        "diagnostico": "Neumonía, organismo no especificado",
        "examen": "Radiografía de tórax",
        "modalidad": "DX/CR",
        "region": "Tórax",
        "antecedentes": [("patologico", "J45", "Asma")],
        "vitales": {"temp": 38.7, "fc": 112, "spo2": 91, "pas": 108, "pad": 67},
        "reporte_previo": {
            "sintoma": "Tos, fiebre y sensación de falta de aire",
            "evolucion": "Síntomas respiratorios progresivos durante tres días",
            "alarma": True,
            "descripcion_alarma": "Dificultad respiratoria y fiebre persistente",
            "ubicacion": "Vereda Inguapí del Carmen",
            "distancia": 32.0,
            "tiempo": 75,
            "orientacion": "Acudir a urgencias por dificultad respiratoria.",
        },
    },
    {
        "documento": 1200001009,
        "nombres": "Andrés",
        "apellidos": "Ortiz Banguera",
        "fecha_nacimiento": "1966-10-05",
        "genero": "male",
        "telefono": "+57 310 555 1109",
        "direccion": "Barrio El Morro",
        "municipio": "Tumaco",
        "zona": "urbana",
        "motivo": "Tos persistente, dolor torácico y disnea de esfuerzo",
        "triage": 3,
        "dolor": 5,
        "cie10": "R05.9",
        "diagnostico": "Tos no especificada con síntomas respiratorios asociados",
        "examen": "Radiografía de tórax",
        "modalidad": "DX/CR",
        "region": "Tórax",
        "antecedentes": [("toxico", None, "Tabaquismo activo")],
        "vitales": {"temp": 37.5, "fc": 96, "spo2": 93, "pas": 138, "pad": 82},
    },
    {
        "documento": 1200001010,
        "nombres": "Sofía",
        "apellidos": "Montaño Quiñones",
        "fecha_nacimiento": "1991-02-18",
        "genero": "female",
        "telefono": "+57 310 555 1110",
        "direccion": "Vereda Bucheli",
        "municipio": "Tumaco",
        "zona": "rural_dispersa",
        "motivo": "Caída desde altura baja con dolor lumbar intenso localizado",
        "triage": 3,
        "dolor": 8,
        "cie10": "S39.9",
        "diagnostico": "Traumatismo de región lumbar, con sospecha de lesión ósea",
        "examen": "Radiografía de columna lumbar",
        "modalidad": "DX/CR",
        "region": "Columna lumbar",
        "antecedentes": [],
        "vitales": {"temp": 36.7, "fc": 94, "spo2": 98, "pas": 124, "pad": 76},
        "reporte_previo": {
            "sintoma": "Dolor lumbar posterior a caída",
            "evolucion": "Dolor persistente que aumenta con el movimiento",
            "alarma": False,
            "descripcion_alarma": None,
            "ubicacion": "Vereda Bucheli",
            "distancia": 15.0,
            "tiempo": 40,
            "orientacion": "Evitar esfuerzos y acudir a valoración en urgencias.",
        },
    },
]


def cargar_env(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def validar_medicos(cur) -> None:
    cur.execute(
        """
        SELECT u.numero_documento_usuario, r.nombre AS rol
        FROM usuarios u
        JOIN roles r ON r.id_rol = u.id_rol
        WHERE u.numero_documento_usuario = ANY(%s)
          AND u.is_deleted = FALSE
          AND u.estado = TRUE;
        """,
        (MEDICOS,),
    )
    encontrados = {r["numero_documento_usuario"]: r["rol"] for r in cur.fetchall()}
    faltantes = [m for m in MEDICOS if encontrados.get(m) != "Medico"]
    if faltantes:
        raise RuntimeError(
            "No se encontraron como médicos activos los documentos: "
            + ", ".join(map(str, faltantes))
        )


def paciente_existe(cur, documento: int) -> bool:
    cur.execute(
        "SELECT 1 FROM pacientes WHERE numero_documento_paciente=%s;",
        (documento,),
    )
    return cur.fetchone() is not None


def insertar_observacion(cur, encuentro, nombre, codigo, valor, unidad, medico, fecha):
    cur.execute(
        """
        INSERT INTO observaciones(
            id_encuentro, tipo_observacion, codigo_loinc, nombre,
            valor_numerico, valor_texto, unidad,
            fecha_hora_observacion, registrado_por
        )
        VALUES (%s,'signo_vital',%s,%s,%s,NULL,%s,%s,%s);
        """,
        (encuentro, codigo, nombre, Decimal(str(valor)), unidad, fecha, medico),
    )


def main() -> None:
    cargar_env(PASS_ENV)
    conn_str = os.getenv("PG_CONNECTION_STRING")
    if not conn_str:
        raise RuntimeError("PG_CONNECTION_STRING no está definido en back/pass.env")

    print("=" * 72)
    print("CARGA DE 10 PACIENTES SINTÉTICOS CON EXÁMENES DE RADIOGRAFÍA")
    print("=" * 72)
    print("Este script INSERTA datos clínicos en Neon/PostgreSQL.")
    print("NO crea cuentas de usuario y NO sube archivos DICOM.")
    print("Los DICOM se cargarán después desde el frontend.")
    print()

    respuesta = input("¿Deseas continuar? [s/N]: ").strip().lower()
    if respuesta != "s":
        print("Operación cancelada.")
        return

    resumen = []
    creados = 0
    omitidos = 0

    with psycopg2.connect(conn_str) as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            validar_medicos(cur)

            ahora = datetime.now(timezone.utc).replace(second=0, microsecond=0)

            for idx, caso in enumerate(CASOS):
                doc = caso["documento"]

                if paciente_existe(cur, doc):
                    print(f"OMITIDO: paciente {doc} ya existe.")
                    omitidos += 1
                    continue

                medico = MEDICOS[idx % len(MEDICOS)]
                ingreso = ahora - timedelta(hours=idx + 1)
                triage = ingreso + timedelta(minutes=8)
                fecha_diag = triage + timedelta(minutes=20)
                fecha_examen = fecha_diag + timedelta(minutes=10)

                cur.execute(
                    """
                    INSERT INTO pacientes(
                        numero_documento_paciente, id_usuario, tipo_documento,
                        nombres, apellidos, fecha_nacimiento, genero_fhir,
                        telefono, direccion, municipio_residencia, zona_residencia
                    )
                    VALUES (%s,NULL,'CC',%s,%s,%s,%s,%s,%s,%s,%s);
                    """,
                    (
                        doc,
                        caso["nombres"],
                        caso["apellidos"],
                        caso["fecha_nacimiento"],
                        caso["genero"],
                        caso["telefono"],
                        caso["direccion"],
                        caso["municipio"],
                        caso["zona"],
                    ),
                )

                for tipo, codigo, descripcion in caso.get("antecedentes", []):
                    cur.execute(
                        """
                        INSERT INTO antecedentes(
                            id_paciente,tipo,codigo,descripcion,registrado_por
                        )
                        VALUES (%s,%s,%s,%s,%s);
                        """,
                        (doc, tipo, codigo, descripcion, medico),
                    )

                rp = caso.get("reporte_previo")
                if rp:
                    cur.execute(
                        """
                        INSERT INTO reportes_previos(
                            id_paciente, fecha_hora_reporte, sintoma_principal,
                            inicio_sintomas, evolucion, signos_alarma_presentes,
                            descripcion_signos_alarma, ubicacion_aproximada,
                            municipio_origen, distancia_aproximada_km,
                            tiempo_desplazamiento_min, orientacion_inicial,
                            registrado_por
                        )
                        VALUES (
                            %s,%s,%s,%s,%s,%s,%s,%s,'Tumaco',%s,%s,%s,%s
                        );
                        """,
                        (
                            doc,
                            ingreso - timedelta(hours=2),
                            rp["sintoma"],
                            ingreso - timedelta(hours=6),
                            rp["evolucion"],
                            rp["alarma"],
                            rp["descripcion_alarma"],
                            rp["ubicacion"],
                            Decimal(str(rp["distancia"])),
                            rp["tiempo"],
                            rp["orientacion"],
                            medico,
                        ),
                    )

                cur.execute(
                    """
                    INSERT INTO encuentros(
                        id_paciente, fecha_hora_ingreso, tipo_encuentro, servicio,
                        estado, motivo_consulta, observaciones_generales,
                        nivel_triage, fecha_hora_triage, dolor_escala,
                        observaciones_triage, clasificado_por,
                        clasificacion_automatica, medico_responsable, creado_por
                    )
                    VALUES (
                        %s,%s,'urgencias','URGENCIAS',
                        'en_atencion',%s,
                        'Paciente valorado en urgencias. Se solicita estudio radiográfico según hallazgos clínicos.',
                        %s,%s,%s,
                        'Clasificación clínica inicial realizada por el profesional.',
                        %s,FALSE,%s,%s
                    )
                    RETURNING id_encuentro;
                    """,
                    (
                        doc,
                        ingreso,
                        caso["motivo"],
                        caso["triage"],
                        triage,
                        caso["dolor"],
                        medico,
                        medico,
                        medico,
                    ),
                )
                encuentro = cur.fetchone()["id_encuentro"]

                v = caso["vitales"]
                insertar_observacion(
                    cur, encuentro, "Temperatura corporal", "8310-5",
                    v["temp"], "Cel", medico, triage
                )
                insertar_observacion(
                    cur, encuentro, "Frecuencia cardiaca", "8867-4",
                    v["fc"], "/min", medico, triage
                )
                insertar_observacion(
                    cur, encuentro, "Saturación de oxígeno", "59408-5",
                    v["spo2"], "%", medico, triage
                )
                insertar_observacion(
                    cur, encuentro, "Presión arterial sistólica", "8480-6",
                    v["pas"], "mm[Hg]", medico, triage
                )
                insertar_observacion(
                    cur, encuentro, "Presión arterial diastólica", "8462-4",
                    v["pad"], "mm[Hg]", medico, triage
                )

                cur.execute(
                    """
                    INSERT INTO diagnosticos(
                        id_encuentro,codigo_cie10,descripcion,tipo,
                        estado_clinico,fecha_diagnostico,registrado_por
                    )
                    VALUES (%s,%s,%s,'principal','active',%s,%s);
                    """,
                    (
                        encuentro,
                        caso["cie10"],
                        caso["diagnostico"],
                        fecha_diag,
                        medico,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO notas_clinicas(
                        id_encuentro,tipo_nota,contenido,fecha_hora,registrado_por
                    )
                    VALUES (
                        %s,'valoracion',
                        %s,%s,%s
                    );
                    """,
                    (
                        encuentro,
                        (
                            f"Valoración en urgencias por: {caso['motivo']}. "
                            f"Se solicita {caso['examen']} para complementar la evaluación. "
                            "Pendiente carga y revisión del estudio de imagen."
                        ),
                        fecha_diag,
                        medico,
                    ),
                )

                cur.execute(
                    """
                    INSERT INTO examenes(
                        id_encuentro,codigo_loinc,nombre,categoria,estado,
                        resultado,conclusion,fecha_solicitud,fecha_resultado,
                        solicitado_por,registrado_resultado_por
                    )
                    VALUES (
                        %s,NULL,%s,'imagenologia','active',
                        NULL,NULL,%s,NULL,%s,NULL
                    )
                    RETURNING id_examen;
                    """,
                    (encuentro, caso["examen"], fecha_examen, medico),
                )
                examen = cur.fetchone()["id_examen"]

                # Auditoría básica de los dos registros principales de la demo.
                cur.execute(
                    """
                    INSERT INTO auditoria_cambios(
                        tabla_afectada,registro_id,accion,datos_nuevos,realizado_por
                    )
                    VALUES (
                        'encuentros',%s,'CREAR',
                        jsonb_build_object(
                            'id_paciente',%s,
                            'estado','en_atencion',
                            'motivo_consulta',%s
                        ),
                        %s
                    );
                    """,
                    (str(encuentro), doc, caso["motivo"], medico),
                )

                cur.execute(
                    """
                    INSERT INTO auditoria_cambios(
                        tabla_afectada,registro_id,accion,datos_nuevos,realizado_por
                    )
                    VALUES (
                        'examenes',%s,'CREAR',
                        jsonb_build_object(
                            'id_encuentro',%s,
                            'nombre',%s,
                            'categoria','imagenologia',
                            'estado','active'
                        ),
                        %s
                    );
                    """,
                    (str(examen), encuentro, caso["examen"], medico),
                )

                resumen.append(
                    {
                        "documento": doc,
                        "paciente": f"{caso['nombres']} {caso['apellidos']}",
                        "encuentro": encuentro,
                        "examen": examen,
                        "solicitud": caso["examen"],
                        "modalidad": caso["modalidad"],
                        "region": caso["region"],
                        "medico": medico,
                    }
                )
                creados += 1
                print(
                    f"CREADO: {doc} | encuentro {encuentro} | "
                    f"examen {examen} | {caso['examen']}"
                )

        conn.commit()

    lineas = [
        "PACIENTES SINTÉTICOS PREPARADOS PARA CARGA DICOM",
        "=" * 80,
        "",
        "IMPORTANTE:",
        "- Los pacientes NO tienen cuenta de usuario.",
        "- Los estudios DICOM todavía NO están cargados.",
        "- Entre al frontend como Médico, busque el documento y use Imágenes PACS.",
        "- Seleccione el encuentro y examen indicados abajo.",
        "",
    ]

    for r in resumen:
        lineas.extend(
            [
                f"Paciente: {r['paciente']}",
                f"Documento: {r['documento']}",
                f"Encuentro: {r['encuentro']}",
                f"Examen: {r['examen']} - {r['solicitud']}",
                f"Modalidad DICOM recomendada: {r['modalidad']}",
                f"Región anatómica: {r['region']}",
                f"Médico responsable: {r['medico']}",
                "-" * 80,
            ]
        )

    lineas.extend(
        [
            "",
            f"Pacientes creados en esta ejecución: {creados}",
            f"Pacientes omitidos porque ya existían: {omitidos}",
        ]
    )

    SALIDA.write_text("\n".join(lineas), encoding="utf-8")

    print()
    print("=" * 72)
    print(f"OK. Creados: {creados} | Omitidos: {omitidos}")
    print(f"Resumen generado en: {SALIDA}")
    print("=" * 72)
    print("Ahora puedes cargar los .dcm desde el frontend como Médico.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nOperación cancelada.")
        sys.exit(1)
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
