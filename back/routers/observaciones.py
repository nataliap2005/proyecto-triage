from decimal import Decimal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,obtener_encuentro,obtener_registro

router=APIRouter()

class ObservacionCreate(BaseModel):
    id_encuentro:int
    tipo_observacion:str=Field(max_length=100)
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str=Field(max_length=150)
    valor_numerico:Decimal|None=None
    valor_texto:str|None=None
    unidad:str|None=Field(default=None,max_length=30)

class ObservacionUpdate(BaseModel):
    tipo_observacion:str|None=Field(default=None,max_length=100)
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str|None=Field(default=None,max_length=150)
    valor_numerico:Decimal|None=None
    valor_texto:str|None=None
    unidad:str|None=Field(default=None,max_length=30)

def validar_observacion(d):
    if (d.get("valor_numerico") is None)==(d.get("valor_texto") is None):
        raise HTTPException(
            status_code=400,
            detail="Debe enviar exactamente uno entre valor_numerico y valor_texto"
        )

@router.post("/observaciones",tags=["Observaciones"],status_code=201)
def crear_observacion(data:ObservacionCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    d=data.model_dump()
    validar_observacion(d)
    return clinical_create(db,u,"observaciones","id_observacion",d)

@router.get("/encuentros/{id_encuentro}/observaciones",tags=["Observaciones"])
def observaciones_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM observaciones
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_hora_observacion;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/observaciones/{id_observacion}",tags=["Observaciones"])
def editar_observacion(id_observacion:int,data:ObservacionUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    cambios=data.model_dump(exclude_unset=True)

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        actual=obtener_registro(cur,"observaciones","id_observacion",id_observacion)

        if not actual:
            raise HTTPException(status_code=404,detail="Observación no encontrada")

        combinado=dict(actual)
        combinado.update(cambios)
        validar_observacion(combinado)

    finally:
        cur.close()

    return clinical_update(
        db,u,"observaciones","id_observacion",
        id_observacion,"registrado_por",cambios
    )

@router.delete("/observaciones/{id_observacion}",tags=["Observaciones"])
def eliminar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_delete(
        db,u,"observaciones","id_observacion",
        id_observacion,"registrado_por"
    )

@router.patch("/observaciones/{id_observacion}/restaurar",tags=["Observaciones"])
def restaurar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"observaciones","id_observacion",id_observacion
    )
