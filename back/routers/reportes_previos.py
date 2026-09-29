from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_paciente_propio,registrar_auditoria

router=APIRouter()

class ReporteCreate(BaseModel):
    id_paciente:int
    sintoma_principal:str
    inicio_sintomas:datetime|None=None
    evolucion:str|None=None
    signos_alarma_presentes:bool=False
    descripcion_signos_alarma:str|None=None
    ubicacion_aproximada:str|None=None
    municipio_origen:str|None=None
    distancia_aproximada_km:Decimal|None=Field(default=None,ge=0)
    tiempo_desplazamiento_min:int|None=Field(default=None,ge=0)

@router.post("/reportes-previos",tags=["Reportes previos"],status_code=201)
def crear_reporte(data:ReporteCreate,db=Depends(get_db),u=Depends(requerir_roles("Paciente","Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        if u["rol"]=="Paciente":
            exigir_paciente_propio(cur,data.id_paciente,u)

        if data.signos_alarma_presentes and not data.descripcion_signos_alarma:
            raise HTTPException(status_code=400,detail="Debe describir los signos de alarma")

        d=data.model_dump()
        cols=list(d.keys())+["registrado_por"]
        vals=[d[k] for k in d]+[u["numero_documento_usuario"]]

        cur.execute(
            f"""
            INSERT INTO reportes_previos({','.join(cols)})
            VALUES({','.join(['%s']*len(cols))})
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"reportes_previos",nuevo["id_reporte"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/reportes-previos",tags=["Reportes previos"])
def listar_reportes(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM reportes_previos
            WHERE is_deleted=FALSE
            ORDER BY fecha_hora_reporte DESC;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/reportes-previos/mios",tags=["Reportes previos"])
def mis_reportes(db=Depends(get_db),u=Depends(requerir_roles("Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT rp.*
            FROM reportes_previos rp
            JOIN pacientes p
              ON p.numero_documento_paciente=rp.id_paciente
            WHERE p.id_usuario=%s
              AND rp.is_deleted=FALSE
            ORDER BY rp.fecha_hora_reporte DESC;
        """,(u["numero_documento_usuario"],))

        return cur.fetchall()

    finally:
        cur.close()
