import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Literal

import jwt
import psycopg2
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json, RealDictCursor
from pwdlib import PasswordHash
from pydantic import BaseModel, Field

load_dotenv("pass.env", override=True)

PG_CONNECTION_STRING=os.getenv("PG_CONNECTION_STRING")
JWT_SECRET_KEY=os.getenv("JWT_SECRET_KEY")
JWT_ALGORITHM="HS256"
JWT_EXPIRE_MINUTES=60

if not PG_CONNECTION_STRING:
    raise RuntimeError("Falta PG_CONNECTION_STRING en pass.env")
if not JWT_SECRET_KEY:
    raise RuntimeError("Falta JWT_SECRET_KEY en pass.env")

app=FastAPI(
    title="API de Triaje Hospitalario",
    version="2.0.0",
    description="API clínica y administrativa alineada con la BD corregida."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

security=HTTPBearer()
password_hash=PasswordHash.recommended()

def get_db():
    conn=psycopg2.connect(PG_CONNECTION_STRING)
    try:
        yield conn
    finally:
        conn.close()

def jsonable_row(row):
    if row is None:
        return None
    d=dict(row)
    for k,v in d.items():
        if isinstance(v,Decimal):
            d[k]=float(v)
        elif isinstance(v,(datetime,date)):
            d[k]=v.isoformat()
    return d

def registrar_auditoria(cursor,tabla,registro_id,accion,usuario,anteriores=None,nuevos=None):
    cursor.execute(
        """
        INSERT INTO auditoria_cambios(
            tabla_afectada,registro_id,accion,datos_anteriores,datos_nuevos,realizado_por
        ) VALUES(%s,%s,%s,%s,%s,%s);
        """,
        (
            tabla,str(registro_id),accion,
            Json(jsonable_row(anteriores)) if anteriores else None,
            Json(jsonable_row(nuevos)) if nuevos else None,
            usuario
        )
    )

def crear_token(usuario):
    now=datetime.now(timezone.utc)
    payload={
        "sub":str(usuario["numero_documento_usuario"]),
        "username":usuario["username"],
        "rol":usuario["rol"],
        "iat":now,
        "exp":now+timedelta(minutes=JWT_EXPIRE_MINUTES)
    }
    return jwt.encode(payload,JWT_SECRET_KEY,algorithm=JWT_ALGORITHM)

def usuario_actual(
    credenciales:HTTPAuthorizationCredentials=Depends(security),
    db=Depends(get_db)
):
    try:
        payload=jwt.decode(credenciales.credentials,JWT_SECRET_KEY,algorithms=[JWT_ALGORITHM])
        documento=int(payload["sub"])
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,detail="Token inválido o vencido")

    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT u.numero_documento_usuario,u.username,u.id_rol,r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE u.numero_documento_usuario=%s
              AND u.estado=TRUE
              AND u.is_deleted=FALSE;
        """,(documento,))
        u=cur.fetchone()
    finally:
        cur.close()

    if not u:
        raise HTTPException(status_code=401,detail="Usuario no disponible")

    return dict(u)

def requerir_roles(*roles):
    def dep(u=Depends(usuario_actual)):
        if u["rol"] not in roles:
            raise HTTPException(status_code=403,detail="No tiene permisos para esta operación")
        return u
    return dep

def es_paciente_propio(cursor,id_paciente,u):
    cursor.execute("""
        SELECT 1
        FROM pacientes
        WHERE numero_documento_paciente=%s
          AND id_usuario=%s
          AND is_deleted=FALSE;
    """,(id_paciente,u["numero_documento_usuario"]))
    return cursor.fetchone() is not None

def exigir_paciente_propio(cursor,id_paciente,u):
    if u["rol"]=="Paciente" and not es_paciente_propio(cursor,id_paciente,u):
        raise HTTPException(status_code=403,detail="Solo puede consultar su propia información")

def obtener_encuentro(cursor,id_encuentro,incluir_eliminado=True):
    q="SELECT * FROM encuentros WHERE id_encuentro=%s"
    if not incluir_eliminado:
        q+=" AND is_deleted=FALSE"
    cursor.execute(q+";",(id_encuentro,))
    r=cursor.fetchone()
    return dict(r) if r else None

def exigir_acceso_encuentro(cursor,encuentro,u):
    if not encuentro:
        raise HTTPException(status_code=404,detail="Encuentro no encontrado")
    exigir_paciente_propio(cursor,encuentro["id_paciente"],u)

def exigir_autor_o_admin(registro,campo_autor,u):
    if u["rol"]=="Admin":
        return
    if u["rol"]!="Medico" or registro[campo_autor]!=u["numero_documento_usuario"]:
        raise HTTPException(
            status_code=403,
            detail="El médico solo puede modificar o eliminar registros creados por él mismo"
        )

def obtener_registro(cursor,tabla,pk,id_registro):
    cursor.execute(f"SELECT * FROM {tabla} WHERE {pk}=%s;",(id_registro,))
    r=cursor.fetchone()
    return dict(r) if r else None

@app.get("/",tags=["Sistema"])
def raiz():
    return {"mensaje":"API de Triaje Hospitalario","version":"2.0.0"}

@app.get("/estado-bd",tags=["Sistema"])
def estado_bd(db=Depends(get_db)):
    cur=db.cursor()
    try:
        cur.execute("SELECT current_database(),current_user;")
        bd,usuario=cur.fetchone()
        return {"estado":"ok","base_datos":bd,"usuario":usuario}
    finally:
        cur.close()

class LoginIn(BaseModel):
    username:str
    password:str

@app.post("/auth/login",tags=["Autenticación"])
def login(datos:LoginIn,db=Depends(get_db)):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,u.username,u.password_hash,
                u.estado,u.is_deleted,r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE u.username=%s;
        """,(datos.username,))
        u=cur.fetchone()
    finally:
        cur.close()

    if (
        not u
        or not u["estado"]
        or u["is_deleted"]
        or not password_hash.verify(datos.password,u["password_hash"])
    ):
        raise HTTPException(status_code=401,detail="Credenciales incorrectas")

    return {"access_token":crear_token(u),"token_type":"bearer","rol":u["rol"]}

@app.get("/auth/me",tags=["Autenticación"])
def me(u=Depends(usuario_actual)):
    return u

class UsuarioCreate(BaseModel):
    numero_documento_usuario:int
    id_rol:int
    username:str=Field(min_length=3,max_length=50)
    password:str=Field(min_length=8)
    nombres:str=Field(min_length=1,max_length=100)
    apellidos:str=Field(min_length=1,max_length=100)
    email:str|None=None
    telefono:str|None=Field(default=None,max_length=30)

class UsuarioUpdate(BaseModel):
    username:str|None=Field(default=None,min_length=3,max_length=50)
    nombres:str|None=Field(default=None,max_length=100)
    apellidos:str|None=Field(default=None,max_length=100)
    email:str|None=None
    telefono:str|None=Field(default=None,max_length=30)
    estado:bool|None=None
    id_rol:int|None=None

@app.post("/usuarios",tags=["Usuarios"],status_code=201)
def crear_usuario(data:UsuarioCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT 1 FROM roles WHERE id_rol=%s AND is_active=TRUE;",(data.id_rol,))
        if not cur.fetchone():
            raise HTTPException(status_code=400,detail="Rol inválido")

        cur.execute("""
            INSERT INTO usuarios(
                numero_documento_usuario,id_rol,username,password_hash,
                nombres,apellidos,email,telefono
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.numero_documento_usuario,data.id_rol,data.username,
            password_hash.hash(data.password),data.nombres,data.apellidos,
            data.email,data.telefono
        ))

        nuevo=cur.fetchone()
        registrar_auditoria(
            cur,"usuarios",data.numero_documento_usuario,"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )
        db.commit()

        d=dict(nuevo)
        d.pop("password_hash",None)
        return d

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Documento, usuario o correo ya registrado")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@app.get("/usuarios",tags=["Usuarios"])
def listar_usuarios(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,u.username,u.nombres,u.apellidos,
                u.email,u.telefono,u.estado,u.is_deleted,r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            ORDER BY u.apellidos,u.nombres;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@app.get("/usuarios/{documento}",tags=["Usuarios"])
def ver_usuario(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,u.username,u.nombres,u.apellidos,
                u.email,u.telefono,u.estado,u.is_deleted,r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE numero_documento_usuario=%s;
        """,(documento,))
        r=cur.fetchone()
        if not r:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")
        return r
    finally:
        cur.close()

@app.put("/usuarios/{documento}",tags=["Usuarios"])
def editar_usuario(documento:int,data:UsuarioUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cambios=data.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"usuarios","numero_documento_usuario",documento)
        if not anterior:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        campos=[]
        valores=[]

        for k,v in cambios.items():
            campos.append(f"{k}=%s")
            valores.append(v)

        valores.append(documento)

        cur.execute(
            f"""
            UPDATE usuarios
            SET {','.join(campos)},updated_at=now()
            WHERE numero_documento_usuario=%s
            RETURNING *;
            """,
            valores
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"usuarios",documento,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()

        d=dict(nuevo)
        d.pop("password_hash",None)
        return d

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@app.delete("/usuarios/{documento}",tags=["Usuarios"])
def eliminar_usuario(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"usuarios","numero_documento_usuario",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        cur.execute("""
            UPDATE usuarios
            SET is_deleted=TRUE,
                estado=FALSE,
                deleted_at=now(),
                deleted_by=%s,
                updated_at=now()
            WHERE numero_documento_usuario=%s
            RETURNING *;
        """,(u["numero_documento_usuario"],documento))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"usuarios",documento,"ELIMINAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Usuario eliminado lógicamente"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@app.patch("/usuarios/{documento}/restaurar",tags=["Usuarios"])
def restaurar_usuario(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"usuarios","numero_documento_usuario",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        cur.execute("""
            UPDATE usuarios
            SET is_deleted=FALSE,
                estado=TRUE,
                deleted_at=NULL,
                deleted_by=NULL,
                updated_at=now()
            WHERE numero_documento_usuario=%s
            RETURNING *;
        """,(documento,))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"usuarios",documento,"RESTAURAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Usuario restaurado"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

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

@app.post("/pacientes",tags=["Pacientes"],status_code=201)
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

@app.get("/pacientes",tags=["Pacientes"])
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

@app.get("/pacientes/{documento}",tags=["Pacientes"])
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

@app.put("/pacientes/{documento}",tags=["Pacientes"])
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

@app.delete("/pacientes/{documento}",tags=["Pacientes"])
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

@app.patch("/pacientes/{documento}/restaurar",tags=["Pacientes"])
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

def clinical_create(db,u,tabla,pk,data:dict,campo_autor="registrado_por"):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        enc=obtener_encuentro(cur,data["id_encuentro"],False)

        if not enc:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if enc["estado"]=="finalizado":
            raise HTTPException(status_code=409,detail="El encuentro está finalizado")

        if (
            u["rol"]=="Medico"
            and enc["medico_responsable"] not in (None,u["numero_documento_usuario"])
        ):
            raise HTTPException(status_code=403,detail="El encuentro está asignado a otro médico")

        data[campo_autor]=u["numero_documento_usuario"]

        cols=list(data.keys())
        vals=[data[c] for c in cols]

        cur.execute(
            f"""
            INSERT INTO {tabla}({','.join(cols)})
            VALUES({','.join(['%s']*len(cols))})
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,nuevo[pk],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_update(db,u,tabla,pk,id_registro,campo_autor,cambios):
    if not cambios:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior or anterior["is_deleted"]:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        exigir_autor_o_admin(anterior,campo_autor,u)

        campos=[]
        vals=[]

        for k,v in cambios.items():
            campos.append(f"{k}=%s")
            vals.append(v)

        vals.append(id_registro)

        cur.execute(
            f"""
            UPDATE {tabla}
            SET {','.join(campos)},updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_delete(db,u,tabla,pk,id_registro,campo_autor):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior or anterior["is_deleted"]:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        exigir_autor_o_admin(anterior,campo_autor,u)

        cur.execute(
            f"""
            UPDATE {tabla}
            SET is_deleted=TRUE,
                deleted_at=now(),
                deleted_by=%s,
                updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            (u["numero_documento_usuario"],id_registro)
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"ELIMINAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Registro eliminado lógicamente"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_restore(db,u,tabla,pk,id_registro):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        cur.execute(
            f"""
            UPDATE {tabla}
            SET is_deleted=FALSE,
                deleted_at=NULL,
                deleted_by=NULL,
                updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            (id_registro,)
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"RESTAURAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

class AntecedenteCreate(BaseModel):
    id_paciente:int
    tipo:str=Field(max_length=50)
    codigo:str|None=Field(default=None,max_length=50)
    descripcion:str

class AntecedenteUpdate(BaseModel):
    tipo:str|None=Field(default=None,max_length=50)
    codigo:str|None=Field(default=None,max_length=50)
    descripcion:str|None=None

@app.post("/antecedentes",tags=["Antecedentes"],status_code=201)
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

@app.get("/pacientes/{documento}/antecedentes",tags=["Antecedentes"])
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

@app.put("/antecedentes/{id_antecedente}",tags=["Antecedentes"])
def editar_antecedente(id_antecedente:int,data:AntecedenteUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"antecedentes","id_antecedente",
        id_antecedente,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@app.delete("/antecedentes/{id_antecedente}",tags=["Antecedentes"])
def eliminar_antecedente(id_antecedente:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"antecedentes","id_antecedente",
        id_antecedente,"registrado_por"
    )

@app.patch("/antecedentes/{id_antecedente}/restaurar",tags=["Antecedentes"])
def restaurar_antecedente(id_antecedente:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"antecedentes","id_antecedente",id_antecedente
    )

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

@app.post("/reportes-previos",tags=["Reportes previos"],status_code=201)
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

@app.get("/reportes-previos",tags=["Reportes previos"])
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

@app.get("/reportes-previos/mios",tags=["Reportes previos"])
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

@app.post("/encuentros",tags=["Encuentros"],status_code=201)
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

@app.get("/encuentros",tags=["Encuentros"])
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

@app.get("/encuentros/mios",tags=["Encuentros"])
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

@app.get("/encuentros/{id_encuentro}",tags=["Encuentros"])
def ver_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)
        return e
    finally:cur.close()

@app.put("/encuentros/{id_encuentro}/triage",tags=["Encuentros"])
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

@app.patch("/encuentros/{id_encuentro}/finalizar",tags=["Encuentros"])
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

@app.post("/observaciones",tags=["Observaciones"],status_code=201)
def crear_observacion(data:ObservacionCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    d=data.model_dump()
    validar_observacion(d)
    return clinical_create(db,u,"observaciones","id_observacion",d)

@app.get("/encuentros/{id_encuentro}/observaciones",tags=["Observaciones"])
def observaciones_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
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

@app.put("/observaciones/{id_observacion}",tags=["Observaciones"])
def editar_observacion(id_observacion:int,data:ObservacionUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
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

@app.delete("/observaciones/{id_observacion}",tags=["Observaciones"])
def eliminar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"observaciones","id_observacion",
        id_observacion,"registrado_por"
    )

@app.patch("/observaciones/{id_observacion}/restaurar",tags=["Observaciones"])
def restaurar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"observaciones","id_observacion",id_observacion
    )

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

@app.post("/diagnosticos",tags=["Diagnósticos"],status_code=201)
def crear_diagnostico(data:DiagnosticoCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_create(
        db,u,"diagnosticos","id_diagnostico",data.model_dump()
    )

@app.get("/encuentros/{id_encuentro}/diagnosticos",tags=["Diagnósticos"])
def diagnosticos_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
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

@app.put("/diagnosticos/{id_diagnostico}",tags=["Diagnósticos"])
def editar_diagnostico(id_diagnostico:int,data:DiagnosticoUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"diagnosticos","id_diagnostico",
        id_diagnostico,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@app.delete("/diagnosticos/{id_diagnostico}",tags=["Diagnósticos"])
def eliminar_diagnostico(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"diagnosticos","id_diagnostico",
        id_diagnostico,"registrado_por"
    )

@app.patch("/diagnosticos/{id_diagnostico}/restaurar",tags=["Diagnósticos"])
def restaurar_diagnostico(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"diagnosticos","id_diagnostico",id_diagnostico
    )

class NotaCreate(BaseModel):
    id_encuentro:int
    tipo_nota:Literal["evolucion","valoracion","nota_clinica"]
    contenido:str

class NotaUpdate(BaseModel):
    tipo_nota:Literal["evolucion","valoracion","nota_clinica"]|None=None
    contenido:str|None=None

@app.post("/notas-clinicas",tags=["Notas clínicas"],status_code=201)
def crear_nota(data:NotaCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_create(
        db,u,"notas_clinicas","id_nota",data.model_dump()
    )

@app.get("/encuentros/{id_encuentro}/notas-clinicas",tags=["Notas clínicas"])
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

@app.put("/notas-clinicas/{id_nota}",tags=["Notas clínicas"])
def editar_nota(id_nota:int,data:NotaUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_update(
        db,u,"notas_clinicas","id_nota",
        id_nota,"registrado_por",
        data.model_dump(exclude_unset=True)
    )

@app.delete("/notas-clinicas/{id_nota}",tags=["Notas clínicas"])
def eliminar_nota(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"notas_clinicas","id_nota",
        id_nota,"registrado_por"
    )

@app.patch("/notas-clinicas/{id_nota}/restaurar",tags=["Notas clínicas"])
def restaurar_nota(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"notas_clinicas","id_nota",id_nota
    )

EstadoExamen=Literal[
    "draft","active","on-hold","revoked",
    "completed","entered-in-error","unknown"
]

class ExamenCreate(BaseModel):
    id_encuentro:int
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str=Field(max_length=150)
    categoria:str|None=Field(default=None,max_length=100)

class ExamenUpdate(BaseModel):
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str|None=Field(default=None,max_length=150)
    categoria:str|None=Field(default=None,max_length=100)
    estado:EstadoExamen|None=None
    resultado:str|None=None
    conclusion:str|None=None
    fecha_resultado:datetime|None=None

@app.post("/examenes",tags=["Exámenes"],status_code=201)
def crear_examen(data:ExamenCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    d=data.model_dump()
    d["estado"]="active"
    return clinical_create(
        db,u,"examenes","id_examen",d,"solicitado_por"
    )

@app.get("/encuentros/{id_encuentro}/examenes",tags=["Exámenes"])
def examenes_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM examenes
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_solicitud;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@app.put("/examenes/{id_examen}",tags=["Exámenes"])
def editar_examen(id_examen:int,data:ExamenUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cambios=data.model_dump(exclude_unset=True)

    if cambios.get("estado")=="completed":
        cambios["registrado_resultado_por"]=u["numero_documento_usuario"]

        if cambios.get("fecha_resultado") is None:
            cambios["fecha_resultado"]=datetime.now(timezone.utc)

    return clinical_update(
        db,u,"examenes","id_examen",
        id_examen,"solicitado_por",cambios
    )

@app.delete("/examenes/{id_examen}",tags=["Exámenes"])
def eliminar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"examenes","id_examen",
        id_examen,"solicitado_por"
    )

@app.patch("/examenes/{id_examen}/restaurar",tags=["Exámenes"])
def restaurar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"examenes","id_examen",id_examen
    )

class MedicamentoCreate(BaseModel):
    codigo_cum:str=Field(max_length=50)
    nombre:str=Field(max_length=150)
    principio_activo:str|None=Field(default=None,max_length=150)
    concentracion:str|None=Field(default=None,max_length=100)
    forma_farmaceutica:str|None=Field(default=None,max_length=100)
    registro_sanitario:str|None=Field(default=None,max_length=100)
    estado_cum:str|None=Field(default=None,max_length=30)
    precio_unitario:Decimal=Field(ge=0)

@app.post("/medicamentos",tags=["Medicamentos"],status_code=201)
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

@app.get("/medicamentos",tags=["Medicamentos"])
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

@app.post("/prescripciones",tags=["Prescripciones"],status_code=201)
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

@app.get("/prescripciones",tags=["Prescripciones"])
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

@app.get("/encuentros/{id_encuentro}/prescripciones",tags=["Prescripciones"])
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

@app.put("/prescripciones/{id_prescripcion}",tags=["Prescripciones"])
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

@app.patch("/prescripciones/{id_prescripcion}/dispensar",tags=["Prescripciones"])
def dispensar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return cambiar_estado_prescripcion(
        id_prescripcion,"dispensada","DISPENSAR",db,u
    )

@app.patch("/prescripciones/{id_prescripcion}/anular",tags=["Prescripciones"])
def anular_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return cambiar_estado_prescripcion(
        id_prescripcion,"anulada","ANULAR",db,u
    )

@app.delete("/prescripciones/{id_prescripcion}",tags=["Prescripciones"])
def eliminar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    return clinical_delete(
        db,u,"prescripciones","id_prescripcion",
        id_prescripcion,"prescrito_por"
    )

@app.patch("/prescripciones/{id_prescripcion}/restaurar",tags=["Prescripciones"])
def restaurar_prescripcion(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"prescripciones","id_prescripcion",id_prescripcion
    )

class DetalleAdicional(BaseModel):
    concepto:str=Field(max_length=200)
    cantidad:int=Field(default=1,gt=0)
    valor_unitario:Decimal=Field(ge=0)

class FacturaCreate(BaseModel):
    id_encuentro:int
    numero_factura:str=Field(max_length=50)
    concepto:str|None=None
    incluir_prescripciones_dispensadas:bool=True
    incluir_examenes_completados:bool=True
    detalles_adicionales:list[DetalleAdicional]=Field(default_factory=list)

@app.post("/facturas",tags=["Facturación"],status_code=201)
def crear_factura(data:FacturaCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Administrativo"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,data.id_encuentro,False)

        if not e:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if e["estado"]!="finalizado":
            raise HTTPException(status_code=409,detail="Solo se factura un encuentro finalizado")

        cur.execute("""
            INSERT INTO facturas(
                id_paciente,id_encuentro,numero_factura,
                concepto,total,creado_por
            )
            VALUES(%s,%s,%s,%s,0,%s)
            RETURNING *;
        """,(
            e["id_paciente"],e["id_encuentro"],
            data.numero_factura,data.concepto,
            u["numero_documento_usuario"]
        ))

        f=cur.fetchone()
        detalles=[]

        if data.incluir_prescripciones_dispensadas:
            cur.execute("""
                SELECT
                    pr.id_prescripcion,pr.cantidad,
                    m.nombre,m.precio_unitario
                FROM prescripciones pr
                JOIN medicamentos m ON m.codigo_cum=pr.codigo_cum
                WHERE pr.id_encuentro=%s
                  AND pr.estado='dispensada'
                  AND pr.is_deleted=FALSE;
            """,(e["id_encuentro"],))

            for pr in cur.fetchall():
                detalles.append((
                    pr["id_prescripcion"],None,
                    f"Medicamento: {pr['nombre']}",
                    pr["cantidad"],pr["precio_unitario"]
                ))

        if data.incluir_examenes_completados:
            cur.execute("""
                SELECT id_examen,nombre
                FROM examenes
                WHERE id_encuentro=%s
                  AND estado='completed'
                  AND is_deleted=FALSE;
            """,(e["id_encuentro"],))

            for ex in cur.fetchall():
                detalles.append((
                    None,ex["id_examen"],
                    f"Examen: {ex['nombre']}",
                    1,Decimal("0")
                ))

        for d in data.detalles_adicionales:
            detalles.append((
                None,None,d.concepto,
                d.cantidad,d.valor_unitario
            ))

        total=Decimal("0")

        for idp,idx,concepto,cantidad,valor in detalles:
            vt=Decimal(cantidad)*Decimal(valor)
            total+=vt

            cur.execute("""
                INSERT INTO factura_detalle(
                    id_factura,id_encuentro,id_prescripcion,id_examen,
                    concepto,cantidad,valor_unitario,valor_total,creado_por
                )
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s);
            """,(
                f["id_factura"],e["id_encuentro"],
                idp,idx,concepto,cantidad,
                valor,vt,u["numero_documento_usuario"]
            ))

        cur.execute("""
            UPDATE facturas
            SET total=%s,
                updated_at=now()
            WHERE id_factura=%s
            RETURNING *;
        """,(total,f["id_factura"]))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"facturas",nuevo["id_factura"],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ya existe una factura activa para el encuentro o el número está repetido"
        )
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@app.get("/facturas",tags=["Facturación"])
def listar_facturas(db=Depends(get_db),u=Depends(requerir_roles("Admin","Administrativo"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM facturas
            WHERE is_deleted=FALSE
            ORDER BY fecha_emision DESC;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@app.get("/facturas/{id_factura}",tags=["Facturación"])
def ver_factura(id_factura:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Administrativo"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM facturas
            WHERE id_factura=%s
              AND is_deleted=FALSE;
        """,(id_factura,))

        f=cur.fetchone()

        if not f:
            raise HTTPException(status_code=404,detail="Factura no encontrada")

        cur.execute("""
            SELECT *
            FROM factura_detalle
            WHERE id_factura=%s
              AND is_deleted=FALSE
            ORDER BY id_detalle;
        """,(id_factura,))

        d=dict(f)
        d["detalles"]=cur.fetchall()
        return d

    finally:
        cur.close()

@app.get("/pacientes/{documento}/historia-clinica",tags=["Historia clínica"])
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

TablaAuditoria=Literal[
    "usuarios","pacientes","antecedentes","reportes_previos",
    "encuentros","observaciones","diagnosticos","notas_clinicas",
    "examenes","medicamentos","prescripciones","facturas",
    "factura_detalle"
]

@app.get("/auditoria",tags=["Auditoría"])
def auditoria(
    limite:int=Query(100,ge=1,le=500),
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin"))
):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                a.*,u.username,r.nombre AS rol
            FROM auditoria_cambios a
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario=a.realizado_por
            LEFT JOIN roles r
              ON r.id_rol=u.id_rol
            ORDER BY a.fecha_hora DESC
            LIMIT %s;
        """,(limite,))

        return cur.fetchall()

    finally:
        cur.close()

@app.get("/auditoria/{tabla}/{registro_id}",tags=["Auditoría"])
def auditoria_registro(
    tabla:TablaAuditoria,
    registro_id:str,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin"))
):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM auditoria_cambios
            WHERE tabla_afectada=%s
              AND registro_id=%s
            ORDER BY fecha_hora;
        """,(tabla,registro_id))

        return cur.fetchall()

    finally:
        cur.close()


# ============================================================
# FHIR R4 - INTEROPERABILIDAD CON HAPI FHIR
# ============================================================
import base64
import re
import requests

HAPI_FHIR_URL=os.getenv("HAPI_FHIR_URL","http://localhost:8080/fhir").rstrip("/")
FHIR_IDENTIFIER_SYSTEM="urn:salud-digital:documento"
FHIR_CUM_SYSTEM="urn:salud-digital:cum"
FHIR_LOCAL_SYSTEM="urn:salud-digital:local"

def fhir_id(prefijo,valor):
    limpio=re.sub(r"[^A-Za-z0-9.-]","-",str(valor))
    return f"{prefijo}-{limpio}"[:64]

def fhir_put(resource_type,resource_id,resource):
    resource=dict(resource)
    resource["resourceType"]=resource_type
    resource["id"]=resource_id
    try:
        r=requests.put(
            f"{HAPI_FHIR_URL}/{resource_type}/{resource_id}",
            json=resource,
            headers={"Accept":"application/fhir+json","Content-Type":"application/fhir+json"},
            timeout=20
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"No fue posible conectar con HAPI FHIR: {e}")
    if r.status_code not in (200,201):
        try: detalle=r.json()
        except Exception: detalle=r.text
        raise HTTPException(status_code=502,detail={
            "mensaje":"HAPI FHIR rechazó el recurso",
            "resourceType":resource_type,
            "id":resource_id,
            "status_code":r.status_code,
            "respuesta":detalle
        })
    return r.json()

def fhir_get(resource_type,resource_id):
    try:
        r=requests.get(
            f"{HAPI_FHIR_URL}/{resource_type}/{resource_id}",
            headers={"Accept":"application/fhir+json"},
            timeout=20
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"No fue posible conectar con HAPI FHIR: {e}")
    if r.status_code==404:
        raise HTTPException(status_code=404,detail="Recurso FHIR no encontrado")
    if r.status_code!=200:
        raise HTTPException(status_code=502,detail=f"Error consultando HAPI FHIR: HTTP {r.status_code}")
    return r.json()

def ref_patient(documento): return f"Patient/{fhir_id('paciente',documento)}"
def ref_encounter(id_encuentro): return f"Encounter/{fhir_id('encuentro',id_encuentro)}"
def ref_practitioner(documento): return f"Practitioner/{fhir_id('practitioner',documento)}"
def ref_medication(codigo_cum): return f"Medication/{fhir_id('medicamento',codigo_cum)}"

def map_encounter_status(estado):
    return {"en_triage":"triaged","en_atencion":"in-progress","en_observacion":"in-progress","finalizado":"finished"}.get(estado,"unknown")

def map_medication_request_status(estado):
    return {"activa":"active","dispensada":"completed","anulada":"cancelled"}.get(estado,"unknown")

def map_invoice_status(estado):
    return {"pendiente":"issued","pagada":"balanced","anulada":"cancelled"}.get(estado,"draft")

def build_patient(p):
    r={
        "identifier":[{"system":FHIR_IDENTIFIER_SYSTEM,"value":str(p["numero_documento_paciente"])}],
        "active":not p["is_deleted"],
        "name":[{"use":"official","family":p["apellidos"],"given":[p["nombres"]]}]
    }
    if p["genero_fhir"]: r["gender"]=p["genero_fhir"]
    if p["fecha_nacimiento"]: r["birthDate"]=p["fecha_nacimiento"].isoformat()
    if p["telefono"]: r["telecom"]=[{"system":"phone","value":p["telefono"]}]
    if p["direccion"] or p["municipio_residencia"]:
        r["address"]=[{"text":p["direccion"] or "","city":p["municipio_residencia"]}]
    return r

def build_practitioner(u):
    r={
        "identifier":[{"system":FHIR_IDENTIFIER_SYSTEM,"value":str(u["numero_documento_usuario"])}],
        "active":bool(u["estado"] and not u["is_deleted"]),
        "name":[{"family":u["apellidos"],"given":[u["nombres"]]}]
    }
    telecom=[]
    if u["telefono"]: telecom.append({"system":"phone","value":u["telefono"]})
    if u["email"]: telecom.append({"system":"email","value":u["email"]})
    if telecom: r["telecom"]=telecom
    return r

def build_encounter(e):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(e["id_encuentro"])}],
        "status":map_encounter_status(e["estado"]),
        "class":{"system":"http://terminology.hl7.org/CodeSystem/v3-ActCode","code":"EMER","display":"emergency"},
        "subject":{"reference":ref_patient(e["id_paciente"])},
        "period":{"start":e["fecha_hora_ingreso"].isoformat()}
    }
    if e["fecha_hora_fin"]: r["period"]["end"]=e["fecha_hora_fin"].isoformat()
    if e["motivo_consulta"]: r["reasonCode"]=[{"text":e["motivo_consulta"]}]
    if e["medico_responsable"]:
        r["participant"]=[{"individual":{"reference":ref_practitioner(e["medico_responsable"])}}]
    return r

def build_observation(o,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(o["id_observacion"])}],
        "status":"final",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(o["id_encuentro"])},
        "effectiveDateTime":o["fecha_hora_observacion"].isoformat(),
        "performer":[{"reference":ref_practitioner(o["registrado_por"])}]
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":o["codigo_loinc"],"display":o["nombre"]}],"text":o["nombre"]} if o["codigo_loinc"] else {"text":o["nombre"]}
    if o["valor_numerico"] is not None:
        r["valueQuantity"]={"value":float(o["valor_numerico"])}
        if o["unidad"]: r["valueQuantity"]["unit"]=o["unidad"]
    else:
        r["valueString"]=o["valor_texto"]
    return r

def build_condition(d,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(d["id_diagnostico"])}],
        "clinicalStatus":{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-clinical","code":d["estado_clinico"]}]},
        "verificationStatus":{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-ver-status","code":"confirmed"}]},
        "category":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-category","code":"encounter-diagnosis","display":"Encounter Diagnosis"}]}],
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(d["id_encuentro"])},
        "recordedDate":d["fecha_diagnostico"].isoformat(),
        "recorder":{"reference":ref_practitioner(d["registrado_por"])}
    }
    r["code"]={"coding":[{"system":"http://hl7.org/fhir/sid/icd-10","code":d["codigo_cie10"],"display":d["descripcion"]}],"text":d["descripcion"]} if d["codigo_cie10"] else {"text":d["descripcion"]}
    return r

def build_medication(m):
    r={
        "identifier":[{"system":FHIR_CUM_SYSTEM,"value":m["codigo_cum"]}],
        "status":"active" if not m["is_deleted"] else "inactive",
        "code":{"coding":[{"system":FHIR_CUM_SYSTEM,"code":m["codigo_cum"],"display":m["nombre"]}],"text":m["nombre"]}
    }
    if m["forma_farmaceutica"]: r["form"]={"text":m["forma_farmaceutica"]}
    return r

def build_medication_request(p,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(p["id_prescripcion"])}],
        "status":map_medication_request_status(p["estado"]),
        "intent":"order",
        "medicationReference":{"reference":ref_medication(p["codigo_cum"])},
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(p["id_encuentro"])},
        "authoredOn":p["fecha_prescripcion"].isoformat(),
        "requester":{"reference":ref_practitioner(p["prescrito_por"])}
    }
    partes=[]
    if p["dosis"]: partes.append(f"Dosis: {p['dosis']}")
    if p["frecuencia"]: partes.append(f"Frecuencia: {p['frecuencia']}")
    if p["via_administracion"]: partes.append(f"Vía: {p['via_administracion']}")
    partes.append(f"Cantidad: {p['cantidad']}")
    r["dosageInstruction"]=[{"text":". ".join(partes)}]
    return r

def build_service_request(ex,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(ex["id_examen"])}],
        "status":ex["estado"],
        "intent":"order",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(ex["id_encuentro"])},
        "authoredOn":ex["fecha_solicitud"].isoformat(),
        "requester":{"reference":ref_practitioner(ex["solicitado_por"])}
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":ex["codigo_loinc"],"display":ex["nombre"]}],"text":ex["nombre"]} if ex["codigo_loinc"] else {"text":ex["nombre"]}
    if ex["categoria"]: r["category"]=[{"text":ex["categoria"]}]
    return r

def build_diagnostic_report(ex,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(ex["id_examen"])}],
        "basedOn":[{"reference":f"ServiceRequest/{fhir_id('examen',ex['id_examen'])}"}],
        "status":"final" if ex["estado"]=="completed" else "preliminary",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(ex["id_encuentro"])}
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":ex["codigo_loinc"],"display":ex["nombre"]}],"text":ex["nombre"]} if ex["codigo_loinc"] else {"text":ex["nombre"]}
    if ex["fecha_resultado"]:
        r["effectiveDateTime"]=ex["fecha_resultado"].isoformat()
        r["issued"]=ex["fecha_resultado"].isoformat()
    if ex["conclusion"]: r["conclusion"]=ex["conclusion"]
    if ex["resultado"]:
        r["presentedForm"]=[{"contentType":"text/plain","data":base64.b64encode(ex["resultado"].encode("utf-8")).decode("ascii"),"title":f"Resultado de {ex['nombre']}"}]
    return r

def build_document_reference(n,id_paciente):
    contenido=base64.b64encode(n["contenido"].encode("utf-8")).decode("ascii")
    return {
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(n["id_nota"])}],
        "status":"current",
        "type":{"text":n["tipo_nota"]},
        "subject":{"reference":ref_patient(id_paciente)},
        "context":{"encounter":[{"reference":ref_encounter(n["id_encuentro"])}]},
        "date":n["fecha_hora"].isoformat(),
        "author":[{"reference":ref_practitioner(n["registrado_por"])}],
        "content":[{"attachment":{"contentType":"text/plain","data":contenido,"title":n["tipo_nota"]}}]
    }

def build_questionnaire_response(r):
    def item(link,text,value_key,value):
        if value is None: return None
        return {"linkId":link,"text":text,"answer":[{value_key:value}]}
    items=[
        item("sintoma-principal","Síntoma principal","valueString",r["sintoma_principal"]),
        item("evolucion","Evolución","valueString",r["evolucion"]),
        item("signos-alarma","Signos de alarma presentes","valueBoolean",r["signos_alarma_presentes"]),
        item("descripcion-signos-alarma","Descripción de signos de alarma","valueString",r["descripcion_signos_alarma"]),
        item("municipio-origen","Municipio de origen","valueString",r["municipio_origen"]),
        item("distancia-aproximada-km","Distancia aproximada en km","valueDecimal",float(r["distancia_aproximada_km"]) if r["distancia_aproximada_km"] is not None else None),
        item("tiempo-desplazamiento-min","Tiempo de desplazamiento en minutos","valueInteger",r["tiempo_desplazamiento_min"])
    ]
    return {
        "identifier":{"system":FHIR_LOCAL_SYSTEM,"value":str(r["id_reporte"])},
        "status":"completed",
        "subject":{"reference":ref_patient(r["id_paciente"])},
        "authored":r["fecha_hora_reporte"].isoformat(),
        "item":[x for x in items if x is not None]
    }

def build_invoice(f):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":f["numero_factura"]}],
        "status":map_invoice_status(f["estado"]),
        "subject":{"reference":ref_patient(f["id_paciente"])},
        "date":f["fecha_emision"].isoformat(),
        "totalNet":{"value":float(f["total"]),"currency":"COP"}
    }
    if f["concepto"]: r["type"]={"text":f["concepto"]}
    return r

@app.get("/fhir/estado",tags=["FHIR"])
def estado_fhir(u=Depends(requerir_roles("Admin","Medico"))):
    try:
        r=requests.get(f"{HAPI_FHIR_URL}/metadata",headers={"Accept":"application/fhir+json"},timeout=20)
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"HAPI FHIR no disponible: {e}")
    if r.status_code!=200:
        raise HTTPException(status_code=502,detail=f"HAPI FHIR respondió HTTP {r.status_code}")
    metadata=r.json()
    return {"estado":"ok","url":HAPI_FHIR_URL,"fhirVersion":metadata.get("fhirVersion"),"software":metadata.get("software",{}).get("name")}


@app.put("/fhir/practitioners/{documento}",tags=["FHIR"])
def sincronizar_practitioner(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT u.*
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE u.numero_documento_usuario=%s
              AND r.nombre='Medico'
              AND u.estado=TRUE
              AND u.is_deleted=FALSE;
        """,(documento,))
        medico=cur.fetchone()
        if not medico:
            raise HTTPException(status_code=404,detail="Médico no encontrado")
        return fhir_put(
            "Practitioner",
            fhir_id("practitioner",documento),
            build_practitioner(medico)
        )
    finally:
        cur.close()

@app.get("/fhir/practitioners/{documento}",tags=["FHIR"])
def consultar_practitioner(documento:int,u=Depends(requerir_roles("Admin","Medico"))):
    return fhir_get("Practitioner",fhir_id("practitioner",documento))

@app.put("/fhir/pacientes/{documento}",tags=["FHIR"])
def sincronizar_patient(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM pacientes WHERE numero_documento_paciente=%s;",(documento,))
        p=cur.fetchone()
        if not p: raise HTTPException(status_code=404,detail="Paciente no encontrado")
        return fhir_put("Patient",fhir_id("paciente",documento),build_patient(p))
    finally: cur.close()

@app.get("/fhir/pacientes/{documento}",tags=["FHIR"])
def consultar_patient(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try: exigir_paciente_propio(cur,documento,u)
    finally: cur.close()
    return fhir_get("Patient",fhir_id("paciente",documento))

@app.put("/fhir/encuentros/{id_encuentro}",tags=["FHIR"])
def sincronizar_encounter(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        e=obtener_encuentro(cur,id_encuentro,True)
        if not e: raise HTTPException(status_code=404,detail="Encuentro no encontrado")
        return fhir_put("Encounter",fhir_id("encuentro",id_encuentro),build_encounter(e))
    finally: cur.close()

@app.get("/fhir/encuentros/{id_encuentro}",tags=["FHIR"])
def consultar_encounter(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        e=obtener_encuentro(cur,id_encuentro,True)
        exigir_acceso_encuentro(cur,e,u)
    finally:
        cur.close()
    return fhir_get("Encounter",fhir_id("encuentro",id_encuentro))

@app.put("/fhir/observaciones/{id_observacion}",tags=["FHIR"])
def sincronizar_observation(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT o.*,e.id_paciente FROM observaciones o JOIN encuentros e ON e.id_encuentro=o.id_encuentro WHERE o.id_observacion=%s;",(id_observacion,))
        o=cur.fetchone()
        if not o: raise HTTPException(status_code=404,detail="Observación no encontrada")
        return fhir_put("Observation",fhir_id("observacion",id_observacion),build_observation(o,o["id_paciente"]))
    finally: cur.close()

@app.get("/fhir/observaciones/{id_observacion}",tags=["FHIR"])
def consultar_observation(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT o.*,e.id_paciente
            FROM observaciones o
            JOIN encuentros e ON e.id_encuentro=o.id_encuentro
            WHERE o.id_observacion=%s;
        """,(id_observacion,))
        o=cur.fetchone()
        if not o:
            raise HTTPException(status_code=404,detail="Observación no encontrada")
        e=obtener_encuentro(cur,o["id_encuentro"],True)
        exigir_acceso_encuentro(cur,e,u)
    finally:
        cur.close()
    return fhir_get("Observation",fhir_id("observacion",id_observacion))

@app.put("/fhir/diagnosticos/{id_diagnostico}",tags=["FHIR"])
def sincronizar_condition(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT d.*,e.id_paciente FROM diagnosticos d JOIN encuentros e ON e.id_encuentro=d.id_encuentro WHERE d.id_diagnostico=%s;",(id_diagnostico,))
        d=cur.fetchone()
        if not d: raise HTTPException(status_code=404,detail="Diagnóstico no encontrado")
        return fhir_put("Condition",fhir_id("diagnostico",id_diagnostico),build_condition(d,d["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/medicamentos/{codigo_cum}",tags=["FHIR"])
def sincronizar_medication(codigo_cum:str,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM medicamentos WHERE codigo_cum=%s;",(codigo_cum,))
        m=cur.fetchone()
        if not m: raise HTTPException(status_code=404,detail="Medicamento no encontrado")
        return fhir_put("Medication",fhir_id("medicamento",codigo_cum),build_medication(m))
    finally: cur.close()

@app.put("/fhir/prescripciones/{id_prescripcion}",tags=["FHIR"])
def sincronizar_medication_request(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT p.*,e.id_paciente FROM prescripciones p JOIN encuentros e ON e.id_encuentro=p.id_encuentro WHERE p.id_prescripcion=%s;",(id_prescripcion,))
        p=cur.fetchone()
        if not p: raise HTTPException(status_code=404,detail="Prescripción no encontrada")
        return fhir_put("MedicationRequest",fhir_id("prescripcion",id_prescripcion),build_medication_request(p,p["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/examenes/{id_examen}",tags=["FHIR"])
def sincronizar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT ex.*,e.id_paciente FROM examenes ex JOIN encuentros e ON e.id_encuentro=ex.id_encuentro WHERE ex.id_examen=%s;",(id_examen,))
        ex=cur.fetchone()
        if not ex: raise HTTPException(status_code=404,detail="Examen no encontrado")
        service=fhir_put("ServiceRequest",fhir_id("examen",id_examen),build_service_request(ex,ex["id_paciente"]))
        diagnostic=None
        if ex["estado"]=="completed" or ex["resultado"] or ex["conclusion"]:
            diagnostic=fhir_put("DiagnosticReport",fhir_id("resultado-examen",id_examen),build_diagnostic_report(ex,ex["id_paciente"]))
        return {"ServiceRequest":service,"DiagnosticReport":diagnostic}
    finally: cur.close()

@app.put("/fhir/notas-clinicas/{id_nota}",tags=["FHIR"])
def sincronizar_document_reference(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT n.*,e.id_paciente FROM notas_clinicas n JOIN encuentros e ON e.id_encuentro=n.id_encuentro WHERE n.id_nota=%s;",(id_nota,))
        n=cur.fetchone()
        if not n: raise HTTPException(status_code=404,detail="Nota clínica no encontrada")
        return fhir_put("DocumentReference",fhir_id("nota",id_nota),build_document_reference(n,n["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/reportes-previos/{id_reporte}",tags=["FHIR"])
def sincronizar_questionnaire_response(id_reporte:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM reportes_previos WHERE id_reporte=%s;",(id_reporte,))
        r=cur.fetchone()
        if not r: raise HTTPException(status_code=404,detail="Reporte previo no encontrado")
        return fhir_put("QuestionnaireResponse",fhir_id("reporte-previo",id_reporte),build_questionnaire_response(r))
    finally: cur.close()

@app.put("/fhir/facturas/{id_factura}",tags=["FHIR"])
def sincronizar_invoice(id_factura:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM facturas WHERE id_factura=%s;",(id_factura,))
        f=cur.fetchone()
        if not f: raise HTTPException(status_code=404,detail="Factura no encontrada")
        return fhir_put("Invoice",fhir_id("factura",id_factura),build_invoice(f))
    finally: cur.close()

@app.post("/fhir/sincronizar-todo",tags=["FHIR"])
def sincronizar_todo_fhir(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    resumen={"Practitioner":0,"Patient":0,"Medication":0,"Encounter":0,"Observation":0,"Condition":0,"MedicationRequest":0,"ServiceRequest":0,"DiagnosticReport":0,"DocumentReference":0,"QuestionnaireResponse":0,"Invoice":0}
    try:
        cur.execute("SELECT u.* FROM usuarios u JOIN roles r ON r.id_rol=u.id_rol WHERE r.nombre='Medico' AND u.is_deleted=FALSE;")
        for med in cur.fetchall():
            fhir_put("Practitioner",fhir_id("practitioner",med["numero_documento_usuario"]),build_practitioner(med)); resumen["Practitioner"]+=1
        cur.execute("SELECT * FROM pacientes WHERE is_deleted=FALSE;")
        for p in cur.fetchall():
            fhir_put("Patient",fhir_id("paciente",p["numero_documento_paciente"]),build_patient(p)); resumen["Patient"]+=1
        cur.execute("SELECT * FROM medicamentos WHERE is_deleted=FALSE;")
        for m in cur.fetchall():
            fhir_put("Medication",fhir_id("medicamento",m["codigo_cum"]),build_medication(m)); resumen["Medication"]+=1
        cur.execute("SELECT * FROM encuentros WHERE is_deleted=FALSE;")
        for e in cur.fetchall():
            fhir_put("Encounter",fhir_id("encuentro",e["id_encuentro"]),build_encounter(e)); resumen["Encounter"]+=1
        cur.execute("SELECT o.*,e.id_paciente FROM observaciones o JOIN encuentros e ON e.id_encuentro=o.id_encuentro WHERE o.is_deleted=FALSE;")
        for o in cur.fetchall():
            fhir_put("Observation",fhir_id("observacion",o["id_observacion"]),build_observation(o,o["id_paciente"])); resumen["Observation"]+=1
        cur.execute("SELECT d.*,e.id_paciente FROM diagnosticos d JOIN encuentros e ON e.id_encuentro=d.id_encuentro WHERE d.is_deleted=FALSE;")
        for d in cur.fetchall():
            fhir_put("Condition",fhir_id("diagnostico",d["id_diagnostico"]),build_condition(d,d["id_paciente"])); resumen["Condition"]+=1
        cur.execute("SELECT p.*,e.id_paciente FROM prescripciones p JOIN encuentros e ON e.id_encuentro=p.id_encuentro WHERE p.is_deleted=FALSE;")
        for p in cur.fetchall():
            fhir_put("MedicationRequest",fhir_id("prescripcion",p["id_prescripcion"]),build_medication_request(p,p["id_paciente"])); resumen["MedicationRequest"]+=1
        cur.execute("SELECT ex.*,e.id_paciente FROM examenes ex JOIN encuentros e ON e.id_encuentro=ex.id_encuentro WHERE ex.is_deleted=FALSE;")
        for ex in cur.fetchall():
            fhir_put("ServiceRequest",fhir_id("examen",ex["id_examen"]),build_service_request(ex,ex["id_paciente"])); resumen["ServiceRequest"]+=1
            if ex["estado"]=="completed" or ex["resultado"] or ex["conclusion"]:
                fhir_put("DiagnosticReport",fhir_id("resultado-examen",ex["id_examen"]),build_diagnostic_report(ex,ex["id_paciente"])); resumen["DiagnosticReport"]+=1
        cur.execute("SELECT n.*,e.id_paciente FROM notas_clinicas n JOIN encuentros e ON e.id_encuentro=n.id_encuentro WHERE n.is_deleted=FALSE;")
        for n in cur.fetchall():
            fhir_put("DocumentReference",fhir_id("nota",n["id_nota"]),build_document_reference(n,n["id_paciente"])); resumen["DocumentReference"]+=1
        cur.execute("SELECT * FROM reportes_previos WHERE is_deleted=FALSE;")
        for r in cur.fetchall():
            fhir_put("QuestionnaireResponse",fhir_id("reporte-previo",r["id_reporte"]),build_questionnaire_response(r)); resumen["QuestionnaireResponse"]+=1
        cur.execute("SELECT * FROM facturas WHERE is_deleted=FALSE;")
        for f in cur.fetchall():
            fhir_put("Invoice",fhir_id("factura",f["id_factura"]),build_invoice(f)); resumen["Invoice"]+=1
        return {"mensaje":"Sincronización FHIR R4 completada","hapi_fhir_url":HAPI_FHIR_URL,"recursos":resumen}
    finally: cur.close()