from decimal import Decimal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import registrar_auditoria

router=APIRouter()

class MedicamentoCreate(BaseModel):
    codigo_cum:str=Field(max_length=50)
    nombre:str=Field(max_length=150)
    principio_activo:str|None=Field(default=None,max_length=150)
    concentracion:str|None=Field(default=None,max_length=100)
    forma_farmaceutica:str|None=Field(default=None,max_length=100)
    registro_sanitario:str|None=Field(default=None,max_length=100)
    estado_cum:str|None=Field(default=None,max_length=30)
    precio_unitario:Decimal=Field(ge=0)

@router.post("/medicamentos",tags=["Medicamentos"],status_code=201)
def crear_medicamento(data:MedicamentoCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        d=data.model_dump()
        cols=list(d)
        vals=[d[k] for k in cols]

        cur.execute(
            f"""
            INSERT INTO medicamentos({','.join(cols)})
            VALUES({','.join(['%s']*len(cols))})
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"medicamentos",nuevo["codigo_cum"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Medicamento ya existe")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/medicamentos",tags=["Medicamentos"])
def listar_medicamentos(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM medicamentos
            WHERE is_deleted=FALSE
            ORDER BY nombre;
        """)
        return cur.fetchall()
    finally:
        cur.close()
