# Endpoints de integración PACS.
# Permite consultar el estado de Orthanc, cargar imágenes DICOM,
# relacionarlas con paciente, encuentro y examen, listar estudios asociados
# y obtener previews para su posterior visualización desde el frontend.
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_especialista_remitido,exigir_paciente_propio
from services.pacs_service import (
    eliminar_instancia,
    estado_pacs,
    extraer_metadatos_subida,
    obtener_estudio_orthanc,
    obtener_instancias_estudio,
    obtener_preview_instancia,
    subir_instancia_dicom,
)

router = APIRouter(tags=["PACS"])


def _fecha_dicom(study_date: str | None, study_time: str | None):
    if not study_date:
        return None

    try:
        fecha = datetime.strptime(study_date[:8], "%Y%m%d")

        if study_time:
            limpio = study_time.split(".")[0].ljust(6, "0")[:6]
            hora = datetime.strptime(limpio, "%H%M%S").time()
            fecha = datetime.combine(fecha.date(), hora)

        return fecha.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _obtener_estudio_db(cur, id_estudio: int):
    cur.execute("""
        SELECT *
        FROM estudios_imagenes
        WHERE id_estudio=%s
          AND is_deleted=FALSE;
    """, (id_estudio,))
    return cur.fetchone()


@router.get("/pacs/estado")
def consultar_estado_pacs(
    u=Depends(requerir_roles("Admin", "Medico", "Especialista"))
):
    return estado_pacs()


@router.post("/pacs/estudios", status_code=201)
def crear_estudio_pacs(
    id_paciente: int = Query(...),
    id_encuentro: int = Query(...),
    id_examen: int = Query(...),
    descripcion: str | None = Query(default=None, max_length=250),
    dicom: bytes = Body(..., media_type="application/dicom"),
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin", "Medico", "Especialista"))
):
    cur = db.cursor(cursor_factory=RealDictCursor)
    instance_id_subido = None

    try:
        cur.execute("""
            SELECT
                p.numero_documento_paciente,
                e.id_encuentro,
                ex.id_examen
            FROM pacientes p
            JOIN encuentros e
              ON e.id_paciente=p.numero_documento_paciente
            JOIN examenes ex
              ON ex.id_encuentro=e.id_encuentro
            WHERE p.numero_documento_paciente=%s
              AND e.id_encuentro=%s
              AND ex.id_examen=%s
              AND p.is_deleted=FALSE
              AND e.is_deleted=FALSE
              AND ex.is_deleted=FALSE;
        """, (id_paciente, id_encuentro, id_examen))

        if not cur.fetchone():
            raise HTTPException(
                status_code=400,
                detail="Paciente, encuentro y examen no corresponden entre sí o no existen"
            )

        subida = subir_instancia_dicom(dicom)
        instance_id_subido = subida["ID"]

        meta = extraer_metadatos_subida(subida)

        fecha_estudio = _fecha_dicom(
            meta.get("study_date"),
            meta.get("study_time")
        )

        descripcion_final = (
            descripcion
            or meta.get("study_description")
            or "Estudio de imagen"
        )

        cur.execute("""
            INSERT INTO estudios_imagenes(
                id_paciente,
                id_encuentro,
                id_examen,
                orthanc_study_id,
                study_instance_uid,
                modalidad,
                descripcion,
                fecha_estudio,
                creado_por
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT(orthanc_study_id)
            DO UPDATE SET
                modalidad=COALESCE(EXCLUDED.modalidad,estudios_imagenes.modalidad),
                descripcion=COALESCE(EXCLUDED.descripcion,estudios_imagenes.descripcion),
                fecha_estudio=COALESCE(EXCLUDED.fecha_estudio,estudios_imagenes.fecha_estudio),
                updated_at=now()
            RETURNING *;
        """, (
            id_paciente,
            id_encuentro,
            id_examen,
            meta["orthanc_study_id"],
            meta["study_instance_uid"],
            meta.get("modalidad"),
            descripcion_final,
            fecha_estudio,
            u["numero_documento_usuario"]
        ))

        estudio_db = cur.fetchone()
        db.commit()

        return {
            "mensaje": "Imagen DICOM almacenada en PACS y relacionada con la historia clínica",
            "estudio": estudio_db,
            "orthanc": {
                "instance_id": meta["instance_id"],
                "study_id": meta["orthanc_study_id"],
                "patient_id_dicom": meta.get("patient_id_dicom")
            }
        }

    except UniqueViolation:
        db.rollback()

        if instance_id_subido:
            try:
                eliminar_instancia(instance_id_subido)
            except Exception:
                pass

        raise HTTPException(
            status_code=409,
            detail="El estudio DICOM ya se encuentra relacionado en la base de datos"
        )

    except Exception:
        db.rollback()
        raise

    finally:
        cur.close()


@router.get("/pacientes/{documento}/imagenes")
def listar_imagenes_paciente(
    documento: int,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin", "Medico", "Especialista", "Paciente"))
):
    cur = db.cursor(cursor_factory=RealDictCursor)

    try:
        exigir_paciente_propio(cur, documento, u)
        exigir_especialista_remitido(cur,documento,u,solo_aceptada=True)

        cur.execute("""
            SELECT
                ei.*,
                ex.nombre AS examen,
                ex.codigo_loinc,
                e.fecha_hora_ingreso,
                e.nivel_triage
            FROM estudios_imagenes ei
            JOIN examenes ex
              ON ex.id_examen=ei.id_examen
            JOIN encuentros e
              ON e.id_encuentro=ei.id_encuentro
            WHERE ei.id_paciente=%s
              AND ei.is_deleted=FALSE
            ORDER BY COALESCE(ei.fecha_estudio,ei.created_at) DESC;
        """, (documento,))

        return cur.fetchall()

    finally:
        cur.close()


@router.get("/pacs/estudios/{id_estudio}")
def consultar_estudio_pacs(
    id_estudio: int,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin", "Medico", "Especialista", "Paciente"))
):
    cur = db.cursor(cursor_factory=RealDictCursor)

    try:
        estudio = _obtener_estudio_db(cur, id_estudio)

        if not estudio:
            raise HTTPException(status_code=404, detail="Estudio no encontrado")

        exigir_paciente_propio(cur, estudio["id_paciente"], u)
        exigir_especialista_remitido(cur,estudio["id_paciente"],u,estudio["id_encuentro"],True)

        orthanc = obtener_estudio_orthanc(estudio["orthanc_study_id"])
        instancias = obtener_instancias_estudio(estudio["orthanc_study_id"])

        return {
            "estudio": estudio,
            "orthanc": orthanc,
            "instancias": instancias
        }

    finally:
        cur.close()


@router.get("/pacs/estudios/{id_estudio}/instancias")
def listar_instancias_estudio(
    id_estudio: int,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin", "Medico", "Especialista", "Paciente"))
):
    cur = db.cursor(cursor_factory=RealDictCursor)

    try:
        estudio = _obtener_estudio_db(cur, id_estudio)

        if not estudio:
            raise HTTPException(status_code=404, detail="Estudio no encontrado")

        exigir_paciente_propio(cur, estudio["id_paciente"], u)
        exigir_especialista_remitido(cur,estudio["id_paciente"],u,estudio["id_encuentro"],True)

        return obtener_instancias_estudio(estudio["orthanc_study_id"])

    finally:
        cur.close()


@router.get("/pacs/instancias/{instance_id}/preview")
def preview_instancia(
    instance_id: str,
    u=Depends(requerir_roles("Admin", "Medico", "Especialista"))
):
    contenido, content_type = obtener_preview_instancia(instance_id)

    return Response(
        content=contenido,
        media_type=content_type
    )
