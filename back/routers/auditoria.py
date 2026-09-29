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
    "factura_detalle"
]

@router.get("/auditoria",tags=["Auditoría"])
def auditoria(
    limite:int=Query(100,ge=1,le=500),
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin"))
):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                a.*,u.username,r.nombre AS rol
            FROM auditoria_cambios a
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario=a.realizado_por
            LEFT JOIN roles r
              ON r.id_rol=u.id_rol
            ORDER BY a.fecha_hora DESC
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
            SELECT *
            FROM auditoria_cambios
            WHERE tabla_afectada=%s
              AND registro_id=%s
            ORDER BY fecha_hora;
        """,(tabla,registro_id))

        return cur.fetchall()

    finally:
        cur.close()
