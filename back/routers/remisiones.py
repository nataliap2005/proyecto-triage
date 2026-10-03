from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import registrar_auditoria

router=APIRouter()

class RemisionCreate(BaseModel):
    id_paciente:int
    id_encuentro:int
    especialista_destino:int
    id_especialidad:int
    motivo:str=Field(min_length=3,max_length=2000)

class RemisionRespuesta(BaseModel):
    observacion:str|None=Field(default=None,max_length=2000)


def _obtener_remision(cur,id_remision:int):
    cur.execute("""
        SELECT r.*,e.nombre AS especialidad,
               p.nombres AS paciente_nombres,p.apellidos AS paciente_apellidos,
               mr.nombres AS medico_nombres,mr.apellidos AS medico_apellidos,
               esp.nombres AS especialista_nombres,esp.apellidos AS especialista_apellidos
        FROM remisiones r
        JOIN especialidades e ON e.id_especialidad=r.id_especialidad
        JOIN pacientes p ON p.numero_documento_paciente=r.id_paciente
        JOIN usuarios mr ON mr.numero_documento_usuario=r.medico_remitente
        JOIN usuarios esp ON esp.numero_documento_usuario=r.especialista_destino
        WHERE r.id_remision=%s AND r.is_deleted=FALSE;
    """,(id_remision,))
    return cur.fetchone()

@router.post("/remisiones",tags=["Remisiones"],status_code=201)
def crear_remision(data:RemisionCreate,db=Depends(get_db),u=Depends(requerir_roles("Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT * FROM encuentros
            WHERE id_encuentro=%s AND id_paciente=%s AND is_deleted=FALSE;
        """,(data.id_encuentro,data.id_paciente))
        enc=cur.fetchone()
        if not enc:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado para ese paciente")
        if enc["estado"]=="finalizado":
            raise HTTPException(status_code=409,detail="No se puede remitir desde un encuentro finalizado")
        if enc["medico_responsable"] not in (None,u["numero_documento_usuario"]):
            raise HTTPException(status_code=403,detail="Solo el médico responsable puede remitir este encuentro")

        cur.execute("""
            SELECT 1
            FROM usuarios us
            JOIN roles ro ON ro.id_rol=us.id_rol
            JOIN usuario_especialidades ue ON ue.numero_documento_usuario=us.numero_documento_usuario
            WHERE us.numero_documento_usuario=%s
              AND ro.nombre='Especialista'
              AND ue.id_especialidad=%s
              AND us.estado=TRUE AND us.is_deleted=FALSE;
        """,(data.especialista_destino,data.id_especialidad))
        if not cur.fetchone():
            raise HTTPException(status_code=400,detail="El especialista seleccionado no pertenece a esa especialidad o no está activo")

        # Evita duplicar una remisión activa del mismo encuentro a la misma especialidad,
        # aunque el médico intente seleccionar otro especialista de esa especialidad.
        cur.execute("""
            SELECT id_remision,estado
            FROM remisiones
            WHERE id_encuentro=%s
              AND id_paciente=%s
              AND id_especialidad=%s
              AND estado IN ('pendiente','aceptada')
              AND is_deleted=FALSE
            LIMIT 1;
        """,(data.id_encuentro,data.id_paciente,data.id_especialidad))
        activa=cur.fetchone()
        if activa:
            raise HTTPException(
                status_code=409,
                detail=f"Ya existe una remisión {activa['estado']} para esta especialidad en el encuentro"
            )

        cur.execute("""
            INSERT INTO remisiones(
                id_paciente,id_encuentro,medico_remitente,
                especialista_destino,id_especialidad,motivo
            ) VALUES(%s,%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.id_paciente,data.id_encuentro,u["numero_documento_usuario"],
            data.especialista_destino,data.id_especialidad,data.motivo
        ))
        nuevo=cur.fetchone()
        registrar_auditoria(cur,"remisiones",nuevo["id_remision"],"REMITIR",u["numero_documento_usuario"],nuevos=nuevo)
        db.commit()
        return {"id":nuevo["id_remision"],"estado":nuevo["estado"],"remision":nuevo}
    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Ya existe una remisión activa de este encuentro al especialista")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/remisiones",tags=["Remisiones"])
def listar_remisiones(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        where="r.is_deleted=FALSE"
        params=[]
        if u["rol"]=="Medico":
            where+=" AND r.medico_remitente=%s"
            params.append(u["numero_documento_usuario"])
        elif u["rol"]=="Especialista":
            where+=" AND r.especialista_destino=%s"
            params.append(u["numero_documento_usuario"])
        cur.execute(f"""
            SELECT r.id_remision,r.id_paciente,r.id_encuentro,r.medico_remitente,
                   r.especialista_destino,r.id_especialidad,r.motivo,r.estado,
                   r.fecha_remision,r.fecha_respuesta,r.observacion_respuesta,
                   e.nombre AS especialidad,
                   p.nombres AS paciente_nombres,p.apellidos AS paciente_apellidos,
                   mr.nombres AS medico_nombres,mr.apellidos AS medico_apellidos,
                   esp.nombres AS especialista_nombres,esp.apellidos AS especialista_apellidos
            FROM remisiones r
            JOIN especialidades e ON e.id_especialidad=r.id_especialidad
            JOIN pacientes p ON p.numero_documento_paciente=r.id_paciente
            JOIN usuarios mr ON mr.numero_documento_usuario=r.medico_remitente
            JOIN usuarios esp ON esp.numero_documento_usuario=r.especialista_destino
            WHERE {where}
            ORDER BY r.fecha_remision DESC;
        """,params)
        return cur.fetchall()
    finally:
        cur.close()

@router.patch("/remisiones/{id_remision}/aceptar",tags=["Remisiones"])
def aceptar_remision(id_remision:int,data:RemisionRespuesta,db=Depends(get_db),u=Depends(requerir_roles("Especialista"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        anterior=_obtener_remision(cur,id_remision)
        if not anterior:
            raise HTTPException(status_code=404,detail="Remisión no encontrada")
        if anterior["especialista_destino"]!=u["numero_documento_usuario"]:
            raise HTTPException(status_code=403,detail="La remisión pertenece a otro especialista")
        if anterior["estado"]!="pendiente":
            raise HTTPException(status_code=409,detail="La remisión ya fue respondida")
        cur.execute("""
            UPDATE remisiones
            SET estado='aceptada',fecha_respuesta=now(),observacion_respuesta=%s,updated_at=now()
            WHERE id_remision=%s RETURNING *;
        """,(data.observacion,id_remision))
        nuevo=cur.fetchone()
        registrar_auditoria(cur,"remisiones",id_remision,"ACEPTAR_REMISION",u["numero_documento_usuario"],anterior,nuevo)
        db.commit()
        return {"id":id_remision,"estado":"aceptada"}
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.patch("/remisiones/{id_remision}/rechazar",tags=["Remisiones"])
def rechazar_remision(id_remision:int,data:RemisionRespuesta,db=Depends(get_db),u=Depends(requerir_roles("Especialista"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        anterior=_obtener_remision(cur,id_remision)
        if not anterior:
            raise HTTPException(status_code=404,detail="Remisión no encontrada")
        if anterior["especialista_destino"]!=u["numero_documento_usuario"]:
            raise HTTPException(status_code=403,detail="La remisión pertenece a otro especialista")
        if anterior["estado"]!="pendiente":
            raise HTTPException(status_code=409,detail="La remisión ya fue respondida")
        cur.execute("""
            UPDATE remisiones
            SET estado='rechazada',fecha_respuesta=now(),observacion_respuesta=%s,updated_at=now()
            WHERE id_remision=%s RETURNING *;
        """,(data.observacion,id_remision))
        nuevo=cur.fetchone()
        registrar_auditoria(cur,"remisiones",id_remision,"RECHAZAR_REMISION",u["numero_documento_usuario"],anterior,nuevo)
        db.commit()
        return {"id":id_remision,"estado":"rechazada"}
    except:
        db.rollback()
        raise
    finally:
        cur.close()
