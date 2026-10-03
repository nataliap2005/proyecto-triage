# Endpoints de pacientes y consulta de historia clínica unificada.

from datetime import date
from typing import Literal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_paciente_propio,obtener_registro,registrar_auditoria

router=APIRouter()

GeneroFHIR=Literal["male","female","other","unknown"]
Zona=Literal["urbana","rural_dispersa"]

class PacienteCreate(BaseModel):
    numero_documento_paciente:int
    tipo_documento:str=Field(max_length=20)
    nombres:str=Field(max_length=100)
    apellidos:str=Field(max_length=100)
    fecha_nacimiento:date|None=None
    genero_fhir:GeneroFHIR|None=None
    telefono:str|None=Field(default=None,max_length=30)
    direccion:str|None=Field(default=None,max_length=200)
    municipio_residencia:str|None=Field(default=None,max_length=100)
    zona_residencia:Zona|None=None

class PacienteUpdate(BaseModel):
    tipo_documento:str|None=Field(default=None,max_length=20)
    nombres:str|None=Field(default=None,max_length=100)
    apellidos:str|None=Field(default=None,max_length=100)
    fecha_nacimiento:date|None=None
    genero_fhir:GeneroFHIR|None=None
    telefono:str|None=Field(default=None,max_length=30)
    direccion:str|None=Field(default=None,max_length=200)
    municipio_residencia:str|None=Field(default=None,max_length=100)
    zona_residencia:Zona|None=None

@router.post("/pacientes",tags=["Pacientes"],status_code=201)
def crear_paciente(data:PacienteCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT numero_documento_usuario
            FROM usuarios
            WHERE numero_documento_usuario=%s
              AND id_rol=(SELECT id_rol FROM roles WHERE nombre='Paciente')
              AND is_deleted=FALSE;
        """,(data.numero_documento_paciente,))

        cuenta=cur.fetchone()

        cur.execute("""
            INSERT INTO pacientes(
                numero_documento_paciente,id_usuario,tipo_documento,nombres,
                apellidos,fecha_nacimiento,genero_fhir,telefono,direccion,
                municipio_residencia,zona_residencia
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.numero_documento_paciente,
            cuenta["numero_documento_usuario"] if cuenta else None,
            data.tipo_documento,data.nombres,data.apellidos,
            data.fecha_nacimiento,
            data.genero_fhir,data.telefono,data.direccion,
            data.municipio_residencia,data.zona_residencia
        ))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",data.numero_documento_paciente,"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Paciente ya registrado")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/pacientes",tags=["Pacientes"])
def listar_pacientes(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT *
            FROM pacientes
            WHERE is_deleted=FALSE
            ORDER BY apellidos,nombres;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/pacientes/{documento}",tags=["Pacientes"])
def ver_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM pacientes
            WHERE numero_documento_paciente=%s
              AND is_deleted=FALSE;
        """,(documento,))

        p=cur.fetchone()

        if not p:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        exigir_paciente_propio(cur,documento,u)
        return p

    finally:
        cur.close()

@router.put("/pacientes/{documento}",tags=["Pacientes"])
def editar_paciente(documento:int,data:PacienteUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cambios=data.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        campos=[]
        vals=[]

        for k,v in cambios.items():
            campos.append(f"{k}=%s")
            vals.append(v)

        vals.append(documento)

        cur.execute(
            f"""
            UPDATE pacientes
            SET {','.join(campos)},updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.delete("/pacientes/{documento}",tags=["Pacientes"])
def eliminar_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        cur.execute("""
            UPDATE pacientes
            SET is_deleted=TRUE,
                deleted_at=now(),
                deleted_by=%s,
                updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
        """,(u["numero_documento_usuario"],documento))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"ELIMINAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Paciente eliminado lógicamente"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.patch("/pacientes/{documento}/restaurar",tags=["Pacientes"])
def restaurar_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        cur.execute("""
            UPDATE pacientes
            SET is_deleted=FALSE,
                deleted_at=NULL,
                deleted_by=NULL,
                updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
        """,(documento,))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"RESTAURAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Paciente restaurado"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/pacientes/{documento}/historia-clinica",tags=["Historia clínica"])
def historia_clinica(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM pacientes
            WHERE numero_documento_paciente=%s
              AND is_deleted=FALSE;
        """,(documento,))

        p=cur.fetchone()

        if not p:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        exigir_paciente_propio(cur,documento,u)

        cur.execute("""
            SELECT *
            FROM antecedentes
            WHERE id_paciente=%s
              AND is_deleted=FALSE
            ORDER BY fecha_registro DESC;
        """,(documento,))

        antecedentes=cur.fetchall()

        cur.execute("""
            SELECT *
            FROM encuentros
            WHERE id_paciente=%s
              AND is_deleted=FALSE
            ORDER BY fecha_hora_ingreso DESC;
        """,(documento,))

        encuentros=cur.fetchall()
        episodios=[]

        for e in encuentros:
            ide=e["id_encuentro"]

            cur.execute("""
                SELECT *
                FROM observaciones
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_hora_observacion;
            """,(ide,))
            obs=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM diagnosticos
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_diagnostico;
            """,(ide,))
            dx=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM notas_clinicas
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_hora;
            """,(ide,))
            notas=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM examenes
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_solicitud;
            """,(ide,))
            exam=cur.fetchall()

            cur.execute("""
                SELECT
                    pr.*,m.nombre AS medicamento,
                    m.principio_activo,m.concentracion,
                    m.forma_farmaceutica
                FROM prescripciones pr
                JOIN medicamentos m
                  ON m.codigo_cum=pr.codigo_cum
                WHERE pr.id_encuentro=%s
                  AND pr.is_deleted=FALSE
                ORDER BY pr.fecha_prescripcion;
            """,(ide,))
            pres=cur.fetchall()

            ep=dict(e)

            ep["triage"]={
                "nivel_triage":e["nivel_triage"],
                "fecha_hora_triage":e["fecha_hora_triage"],
                "dolor_escala":e["dolor_escala"],
                "observaciones_triage":e["observaciones_triage"],
                "clasificado_por":e["clasificado_por"]
            }

            ep["observaciones"]=obs
            ep["diagnosticos"]=dx
            ep["notas_clinicas"]=notas
            ep["examenes"]=exam
            ep["prescripciones"]=pres

            episodios.append(ep)

        return {
            "paciente":p,
            "antecedentes":antecedentes,
            "encuentros":episodios
        }

    finally:
        cur.close()
