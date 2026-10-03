from datetime import datetime,timezone
from typing import Literal

from fastapi import APIRouter,Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,obtener_encuentro

router=APIRouter()

EstadoExamen=Literal[
    "draft","active","on-hold","revoked",
    "completed","entered-in-error","unknown"
]

class ExamenCreate(BaseModel):
    id_encuentro:int
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str=Field(max_length=150)
    categoria:str|None=Field(default=None,max_length=100)

class ExamenUpdate(BaseModel):
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str|None=Field(default=None,max_length=150)
    categoria:str|None=Field(default=None,max_length=100)
    estado:EstadoExamen|None=None
    resultado:str|None=None
    conclusion:str|None=None
    fecha_resultado:datetime|None=None

@router.post("/examenes",tags=["Exámenes"],status_code=201)
def crear_examen(data:ExamenCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    d=data.model_dump()
    d["estado"]="active"
    return clinical_create(
        db,u,"examenes","id_examen",d,"solicitado_por"
    )

@router.get("/encuentros/{id_encuentro}/examenes",tags=["Exámenes"])
def examenes_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM examenes
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_solicitud;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/examenes/{id_examen}",tags=["Exámenes"])
def editar_examen(id_examen:int,data:ExamenUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    cambios=data.model_dump(exclude_unset=True)

    if cambios.get("estado")=="completed":
        cambios["registrado_resultado_por"]=u["numero_documento_usuario"]

        if cambios.get("fecha_resultado") is None:
            cambios["fecha_resultado"]=datetime.now(timezone.utc)

    return clinical_update(
        db,u,"examenes","id_examen",
        id_examen,"solicitado_por",cambios
    )

@router.delete("/examenes/{id_examen}",tags=["Exámenes"])
def eliminar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_delete(
        db,u,"examenes","id_examen",
        id_examen,"solicitado_por"
    )

@router.patch("/examenes/{id_examen}/restaurar",tags=["Exámenes"])
def restaurar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"examenes","id_examen",id_examen
    )
