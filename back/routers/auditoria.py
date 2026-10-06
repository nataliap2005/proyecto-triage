from typing import Literal

from fastapi import APIRouter,Depends,Query
from psycopg2.extras import RealDictCursor

from auth.service import requerir_roles
from core.database import get_db

router=APIRouter()

TablaAuditoria=Literal[
    "usuarios","pacientes","antecedentes","reportes_previos",
    "encuentros","observaciones","diagnosticos","notas_clinicas",
    "examenes","medicamentos","prescripciones","facturas",
    "factura_detalle","remisiones","fhir:Observation"
]


@router.get("/auditoria",tags=["Auditoría"])
def auditoria(
    limite:int=Query(100,ge=1,le=500),
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin"))
):
    """Devuelve en un solo log la auditoría funcional y los eventos de autenticación."""
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM (
                SELECT
                    a.id_auditoria::text AS id_evento,
                    'cambios'::text AS origen,
                    a.origen AS sistema_origen,
                    a.tabla_afectada,
                    a.registro_id,
                    a.accion,
                    a.datos_anteriores,
                    a.datos_nuevos,
                    a.realizado_por,
                    u.username,
                    r.nombre AS rol,
                    a.fecha_hora,
                    NULL::boolean AS exitoso,
                    NULL::text AS detalle
                FROM auditoria_cambios a
                LEFT JOIN usuarios u
                  ON u.numero_documento_usuario=a.realizado_por
                LEFT JOIN roles r
                  ON r.id_rol=u.id_rol

                UNION ALL

                SELECT
                    al.id_auth_log::text AS id_evento,
                    'autenticacion'::text AS origen,
                    'API'::text AS sistema_origen, 
                    'usuarios'::text AS tabla_afectada,
                    COALESCE(
                        al.numero_documento_usuario::text,
                        al.username_intentado
                    ) AS registro_id,
                    al.evento AS accion,
                    NULL::jsonb AS datos_anteriores,
                    jsonb_build_object(
                        'username_intentado',al.username_intentado,
                        'exitoso',al.exitoso,
                        'detalle',al.detalle
                    ) AS datos_nuevos,
                    al.numero_documento_usuario AS realizado_por,
                    COALESCE(u.username,al.username_intentado) AS username,
                    r.nombre AS rol,
                    al.fecha_hora,
                    al.exitoso,
                    al.detalle
                FROM auth_log al
                LEFT JOIN usuarios u
                  ON u.numero_documento_usuario=al.numero_documento_usuario
                LEFT JOIN roles r
                  ON r.id_rol=u.id_rol
            ) eventos
            ORDER BY fecha_hora DESC
            LIMIT %s;
        """,(limite,))

        return cur.fetchall()

    finally:
        cur.close()


@router.get("/auditoria/{tabla}/{registro_id}",tags=["Auditoría"])
def auditoria_registro(
    tabla:TablaAuditoria,
    registro_id:str,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin"))
):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                a.*,
                u.username,
                r.nombre AS rol
            FROM auditoria_cambios a
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario=a.realizado_por
            LEFT JOIN roles r
              ON r.id_rol=u.id_rol
            WHERE a.tabla_afectada=%s
              AND a.registro_id=%s
            ORDER BY a.fecha_hora;
        """,(tabla,registro_id))

        return cur.fetchall()

    finally:
        cur.close()
