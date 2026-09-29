from fastapi import APIRouter,Depends,HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import clinical_delete,clinical_restore,clinical_update,exigir_paciente_propio,registrar_auditoria

router=APIRouter()

class AntecedenteCreate(BaseModel):
    id_paciente:int
    tipo:str=Field(max_length=50)
    codigo:str|None=Field(default=None,max_length=50)
    descripcion:str

class AntecedenteUpdate(BaseModel):
    tipo:str|None=Field(default=None,max_length=50)
    codigo:str|None=Field(default=None,max_length=50)
    descripcion:str|None=None

@router.post("/antecedentes",tags=["Antecedentes"],status_code=201)
def crear_antecedente(data:AntecedenteCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT 1
            FROM pacientes
            WHERE numero_documento_paciente=%s
              AND is_deleted=FALSE;
        """,(data.id_paciente,))

        if not cur.fetchone():
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        cur.execute("""
            INSERT INTO antecedentes(
                id_paciente,tipo,codigo,descripcion,registrado_por
            )
            VALUES(%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.id_paciente,data.tipo,data.codigo,data.descripcion,
            u["numero_documento_usuario"]
        ))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"antecedentes",nuevo["id_antecedente"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/pacientes/{documento}/antecedentes",tags=["Antecedentes"])
def listar_antecedentes(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        exigir_paciente_propio(cur,documento,u)

        cur.execute("""
            SELECT *
            FROM antecedentes
            WHERE id_paciente=%s
              AND is_deleted=FALSE
            ORDER BY fecha_registro DESC;
        """,(documento,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/antecedentes/{id_antecedente}",tags=["Antecedentes"])
def editar_antecedente(id_antecedente:int,data:AntecedenteUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"antecedentes","id_antecedente",
        id_antecedente,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@router.delete("/antecedentes/{id_antecedente}",tags=["Antecedentes"])
def eliminar_antecedente(id_antecedente:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"antecedentes","id_antecedente",
        id_antecedente,"registrado_por"
    )

@router.patch("/antecedentes/{id_antecedente}/restaurar",tags=["Antecedentes"])
def restaurar_antecedente(id_antecedente:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"antecedentes","id_antecedente",id_antecedente
    )
