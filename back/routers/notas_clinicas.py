from typing import Literal

from fastapi import APIRouter,Depends
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,obtener_encuentro

router=APIRouter()

class NotaCreate(BaseModel):
    id_encuentro:int
    tipo_nota:Literal["evolucion","valoracion","nota_clinica"]
    contenido:str

class NotaUpdate(BaseModel):
    tipo_nota:Literal["evolucion","valoracion","nota_clinica"]|None=None
    contenido:str|None=None

@router.post("/notas-clinicas",tags=["Notas clínicas"],status_code=201)
def crear_nota(data:NotaCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_create(
        db,u,"notas_clinicas","id_nota",data.model_dump()
    )

@router.get("/encuentros/{id_encuentro}/notas-clinicas",tags=["Notas clínicas"])
def notas_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM notas_clinicas
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_hora;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/notas-clinicas/{id_nota}",tags=["Notas clínicas"])
def editar_nota(id_nota:int,data:NotaUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"notas_clinicas","id_nota",
        id_nota,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@router.delete("/notas-clinicas/{id_nota}",tags=["Notas clínicas"])
def eliminar_nota(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"notas_clinicas","id_nota",
        id_nota,"registrado_por"
    )

@router.patch("/notas-clinicas/{id_nota}/restaurar",tags=["Notas clínicas"])
def restaurar_nota(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"notas_clinicas","id_nota",id_nota
    )
