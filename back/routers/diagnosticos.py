from typing import Literal

from fastapi import APIRouter,Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,obtener_encuentro

router=APIRouter()

class DiagnosticoCreate(BaseModel):
    id_encuentro:int
    codigo_cie10:str|None=Field(default=None,max_length=30)
    descripcion:str=Field(max_length=250)
    tipo:Literal["principal","secundario"]="principal"
    estado_clinico:Literal[
        "active","recurrence","relapse",
        "inactive","remission","resolved"
    ]="active"

class DiagnosticoUpdate(BaseModel):
    codigo_cie10:str|None=Field(default=None,max_length=30)
    descripcion:str|None=Field(default=None,max_length=250)
    tipo:Literal["principal","secundario"]|None=None
    estado_clinico:Literal[
        "active","recurrence","relapse",
        "inactive","remission","resolved"
    ]|None=None

@router.post("/diagnosticos",tags=["Diagnósticos"],status_code=201)
def crear_diagnostico(data:DiagnosticoCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_create(
        db,u,"diagnosticos","id_diagnostico",data.model_dump()
    )

@router.get("/encuentros/{id_encuentro}/diagnosticos",tags=["Diagnósticos"])
def diagnosticos_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM diagnosticos
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_diagnostico;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/diagnosticos/{id_diagnostico}",tags=["Diagnósticos"])
def editar_diagnostico(id_diagnostico:int,data:DiagnosticoUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_update(
        db,u,"diagnosticos","id_diagnostico",
        id_diagnostico,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@router.delete("/diagnosticos/{id_diagnostico}",tags=["Diagnósticos"])
def eliminar_diagnostico(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_delete(
        db,u,"diagnosticos","id_diagnostico",
        id_diagnostico,"registrado_por"
    )

@router.patch("/diagnosticos/{id_diagnostico}/restaurar",tags=["Diagnósticos"])
def restaurar_diagnostico(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"diagnosticos","id_diagnostico",id_diagnostico
    )
