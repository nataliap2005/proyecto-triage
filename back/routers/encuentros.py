from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_acceso_encuentro,obtener_encuentro,registrar_auditoria

router=APIRouter()

class EncuentroCreate(BaseModel):
    id_paciente:int
    motivo_consulta:str
    tipo_encuentro:str="urgencias"
    servicio:str="URGENCIAS"
    medico_responsable:int|None=None

class TriageUpdate(BaseModel):
    nivel_triage:int=Field(ge=1,le=5)
    dolor_escala:int|None=Field(default=None,ge=0,le=10)
    observaciones_triage:str|None=None

@router.post("/encuentros",tags=["Encuentros"],status_code=201)
def crear_encuentro(data:EncuentroCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
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

        medico=data.medico_responsable

        if u["rol"]=="Medico":
            medico=u["numero_documento_usuario"]

        if medico is not None:
            cur.execute("""
                SELECT 1
                FROM usuarios us
                JOIN roles r ON r.id_rol=us.id_rol
                WHERE us.numero_documento_usuario=%s
                  AND r.nombre='Medico'
                  AND us.estado=TRUE
                  AND us.is_deleted=FALSE;
            """,(medico,))
            if not cur.fetchone():
                raise HTTPException(status_code=400,detail="El médico responsable no es un médico activo válido")

        cur.execute("""
            INSERT INTO encuentros(
                id_paciente,tipo_encuentro,servicio,motivo_consulta,
                medico_responsable,creado_por
            )
            VALUES(%s,%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.id_paciente,data.tipo_encuentro,data.servicio,
            data.motivo_consulta,medico,u["numero_documento_usuario"]
        ))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"encuentros",nuevo["id_encuentro"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="El paciente ya tiene un encuentro activo")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/encuentros",tags=["Encuentros"])
def listar_encuentros(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM encuentros
            WHERE is_deleted=FALSE
            ORDER BY fecha_hora_ingreso DESC;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/encuentros/mios",tags=["Encuentros"])
def mis_encuentros(db=Depends(get_db),u=Depends(requerir_roles("Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT e.*
            FROM encuentros e
            JOIN pacientes p
              ON p.numero_documento_paciente=e.id_paciente
            WHERE p.id_usuario=%s
              AND e.is_deleted=FALSE
            ORDER BY e.fecha_hora_ingreso DESC;
        """,(u["numero_documento_usuario"],))

        return cur.fetchall()
    finally:
        cur.close()

@router.get("/encuentros/{id_encuentro}",tags=["Encuentros"])
def ver_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)
        return e
    finally:cur.close()

@router.put("/encuentros/{id_encuentro}/triage",tags=["Encuentros"])
def registrar_triage(id_encuentro:int,data:TriageUpdate,db=Depends(get_db),u=Depends(requerir_roles("Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_encuentro(cur,id_encuentro,False)

        if not anterior:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if anterior["medico_responsable"] not in (None,u["numero_documento_usuario"]):
            raise HTTPException(status_code=403,detail="El encuentro está asignado a otro médico")

        if anterior["estado"]=="finalizado":
            raise HTTPException(status_code=409,detail="Encuentro finalizado")

        cur.execute("""
            UPDATE encuentros
            SET nivel_triage=%s,
                dolor_escala=%s,
                observaciones_triage=%s,
                fecha_hora_triage=now(),
                clasificado_por=%s,
                medico_responsable=COALESCE(medico_responsable,%s),
                estado='en_atencion',
                updated_at=now()
            WHERE id_encuentro=%s
            RETURNING *;
        """,(
            data.nivel_triage,data.dolor_escala,
            data.observaciones_triage,
            u["numero_documento_usuario"],
            u["numero_documento_usuario"],
            id_encuentro
        ))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"encuentros",id_encuentro,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.patch("/encuentros/{id_encuentro}/finalizar",tags=["Encuentros"])
def finalizar_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_encuentro(cur,id_encuentro,False)

        if not anterior:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if (
            u["rol"]=="Medico"
            and anterior["medico_responsable"]!=u["numero_documento_usuario"]
        ):
            raise HTTPException(status_code=403,detail="Solo el médico responsable puede finalizar el encuentro")

        cur.execute("""
            UPDATE encuentros
            SET estado='finalizado',
                fecha_hora_fin=now(),
                updated_at=now()
            WHERE id_encuentro=%s
            RETURNING *;
        """,(id_encuentro,))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"encuentros",id_encuentro,"FINALIZAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()
