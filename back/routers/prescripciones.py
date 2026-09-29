from fastapi import APIRouter,Depends,HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,exigir_autor_o_admin,obtener_encuentro,obtener_registro,registrar_auditoria

router=APIRouter()

class PrescripcionCreate(BaseModel):
    id_encuentro:int
    codigo_cum:str=Field(max_length=50)
    dosis:str|None=Field(default=None,max_length=100)
    frecuencia:str|None=Field(default=None,max_length=100)
    via_administracion:str|None=Field(default=None,max_length=50)
    cantidad:int=Field(gt=0)

class PrescripcionUpdate(BaseModel):
    dosis:str|None=Field(default=None,max_length=100)
    frecuencia:str|None=Field(default=None,max_length=100)
    via_administracion:str|None=Field(default=None,max_length=50)
    cantidad:int|None=Field(default=None,gt=0)

@router.post("/prescripciones",tags=["Prescripciones"],status_code=201)
def crear_prescripcion(data:PrescripcionCreate,db=Depends(get_db),u=Depends(requerir_roles("Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT 1
            FROM medicamentos
            WHERE codigo_cum=%s
              AND is_deleted=FALSE;
        """,(data.codigo_cum,))

        if not cur.fetchone():
            raise HTTPException(status_code=404,detail="Medicamento no encontrado")

    finally:
        cur.close()

    return clinical_create(
        db,u,"prescripciones","id_prescripcion",
        data.model_dump(),"prescrito_por"
    )

@router.get("/prescripciones",tags=["Prescripciones"])
def listar_prescripciones(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                pr.*,m.nombre AS medicamento,e.id_paciente
            FROM prescripciones pr
            JOIN medicamentos m ON m.codigo_cum=pr.codigo_cum
            JOIN encuentros e ON e.id_encuentro=pr.id_encuentro
            WHERE pr.is_deleted=FALSE
            ORDER BY pr.fecha_prescripcion DESC;
        """)
        return cur.fetchall()

    finally:
        cur.close()

@router.get("/encuentros/{id_encuentro}/prescripciones",tags=["Prescripciones"])
def prescripciones_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT
                pr.*,m.nombre AS medicamento
            FROM prescripciones pr
            JOIN medicamentos m ON m.codigo_cum=pr.codigo_cum
            WHERE pr.id_encuentro=%s
              AND pr.is_deleted=FALSE
            ORDER BY pr.fecha_prescripcion;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/prescripciones/{id_prescripcion}",tags=["Prescripciones"])
def editar_prescripcion(id_prescripcion:int,data:PrescripcionUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"prescripciones","id_prescripcion",
        id_prescripcion,"prescrito_por",
        data.model_dump(exclude_unset=True)
    )

def cambiar_estado_prescripcion(id_prescripcion,nuevo_estado,accion,db,u):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"prescripciones","id_prescripcion",id_prescripcion)

        if not anterior or anterior["is_deleted"]:
            raise HTTPException(status_code=404,detail="Prescripción no encontrada")

        exigir_autor_o_admin(anterior,"prescrito_por",u)

        cur.execute("""
            UPDATE prescripciones
            SET estado=%s,
                updated_at=now()
            WHERE id_prescripcion=%s
            RETURNING *;
        """,(nuevo_estado,id_prescripcion))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"prescripciones",id_prescripcion,accion,
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.patch("/prescripciones/{id_prescripcion}/dispensar",tags=["Prescripciones"])
def dispensar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return cambiar_estado_prescripcion(
        id_prescripcion,"dispensada","DISPENSAR",db,u
    )

@router.patch("/prescripciones/{id_prescripcion}/anular",tags=["Prescripciones"])
def anular_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return cambiar_estado_prescripcion(
        id_prescripcion,"anulada","ANULAR",db,u
    )

@router.delete("/prescripciones/{id_prescripcion}",tags=["Prescripciones"])
def eliminar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"prescripciones","id_prescripcion",
        id_prescripcion,"prescrito_por"
    )

@router.patch("/prescripciones/{id_prescripcion}/restaurar",tags=["Prescripciones"])
def restaurar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"prescripciones","id_prescripcion",id_prescripcion
    )
