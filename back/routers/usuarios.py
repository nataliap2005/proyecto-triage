# Endpoints de gestión de usuarios.
# El desbloqueo permanece en auth/router.py porque pertenece a la seguridad de acceso.

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from core.security import hash_password
from routers.common import obtener_registro,registrar_auditoria

router=APIRouter()

class UsuarioCreate(BaseModel):
    numero_documento_usuario:int
    id_rol:int
    username:str=Field(min_length=3,max_length=50,pattern=r"^[A-Za-z0-9._-]+$")
    password:str=Field(min_length=8,max_length=128)
    nombres:str=Field(min_length=1,max_length=100)
    apellidos:str=Field(min_length=1,max_length=100)
    email:str|None=None
    telefono:str|None=Field(default=None,max_length=30)
    id_especialidad:int|None=None

class UsuarioUpdate(BaseModel):
    username:str|None=Field(default=None,min_length=3,max_length=50,pattern=r"^[A-Za-z0-9._-]+$")
    nombres:str|None=Field(default=None,max_length=100)
    apellidos:str|None=Field(default=None,max_length=100)
    email:str|None=None
    telefono:str|None=Field(default=None,max_length=30)
    estado:bool|None=None
    id_rol:int|None=None
    id_especialidad:int|None=None

def _nombre_rol(cur,rol_id:int):
    cur.execute("SELECT nombre FROM roles WHERE id_rol=%s AND is_active=TRUE;",(rol_id,))
    r=cur.fetchone()
    return r["nombre"] if r else None

def _asignar_especialidad(cur,documento:int,rol_id:int,id_especialidad:int|None):
    rol=_nombre_rol(cur,rol_id)
    if rol!="Especialista":
        cur.execute("DELETE FROM usuario_especialidades WHERE numero_documento_usuario=%s;",(documento,))
        return
    if id_especialidad is None:
        cur.execute("SELECT 1 FROM usuario_especialidades WHERE numero_documento_usuario=%s LIMIT 1;",(documento,))
        if cur.fetchone():
            return
        raise HTTPException(status_code=400,detail="Un usuario Especialista debe tener una especialidad")
    cur.execute("SELECT 1 FROM especialidades WHERE id_especialidad=%s AND activo=TRUE;",(id_especialidad,))
    if not cur.fetchone():
        raise HTTPException(status_code=400,detail="Especialidad inválida")
    cur.execute("DELETE FROM usuario_especialidades WHERE numero_documento_usuario=%s;",(documento,))
    cur.execute("INSERT INTO usuario_especialidades(numero_documento_usuario,id_especialidad) VALUES(%s,%s);",(documento,id_especialidad))

def vincular_paciente(cur,documento,rol_id,admin_doc):
    """Si el usuario es Paciente y ya existe un registro clínico con su mismo
    documento sin cuenta, lo vincula para que vea su historia."""
    cur.execute("SELECT nombre FROM roles WHERE id_rol=%s;",(rol_id,))
    r=cur.fetchone()
    if not r or r["nombre"]!="Paciente":
        return False

    cur.execute("""
        UPDATE pacientes
        SET id_usuario=%s,
            updated_at=now()
        WHERE numero_documento_paciente=%s
          AND id_usuario IS NULL
          AND is_deleted=FALSE
        RETURNING *;
    """,(documento,documento))
    p=cur.fetchone()

    if not p:
        return False

    registrar_auditoria(
        cur,"pacientes",documento,"VINCULAR_CUENTA",
        admin_doc,nuevos=p
    )
    return True

@router.post("/usuarios",tags=["Usuarios"],status_code=201)
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
            hash_password(data.password),data.nombres,data.apellidos,
            data.email,data.telefono
        ))

        nuevo=cur.fetchone()
        registrar_auditoria(
            cur,"usuarios",data.numero_documento_usuario,"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        _asignar_especialidad(cur,data.numero_documento_usuario,data.id_rol,data.id_especialidad)
        vinculado=vincular_paciente(
            cur,data.numero_documento_usuario,data.id_rol,
            u["numero_documento_usuario"]
        )
        db.commit()

        d=dict(nuevo)
        d.pop("password_hash",None)
        d["paciente_vinculado"]=vinculado
        return d

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Documento, usuario o correo ya registrado")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/usuarios",tags=["Usuarios"])
def listar_usuarios(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,u.username,u.nombres,u.apellidos,
                u.email,u.telefono,u.estado,u.is_deleted,r.nombre AS rol,
                COALESCE(string_agg(e.nombre, ', ' ORDER BY e.nombre),'') AS especialidades
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            LEFT JOIN usuario_especialidades ue ON ue.numero_documento_usuario=u.numero_documento_usuario
            LEFT JOIN especialidades e ON e.id_especialidad=ue.id_especialidad
            GROUP BY u.numero_documento_usuario,r.nombre
            ORDER BY u.apellidos,u.nombres;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/usuarios/{documento}",tags=["Usuarios"])
def ver_usuario(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,u.username,u.nombres,u.apellidos,
                u.email,u.telefono,u.estado,u.is_deleted,r.nombre AS rol,
                COALESCE(string_agg(e.nombre, ', ' ORDER BY e.nombre),'') AS especialidades
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            LEFT JOIN usuario_especialidades ue ON ue.numero_documento_usuario=u.numero_documento_usuario
            LEFT JOIN especialidades e ON e.id_especialidad=ue.id_especialidad
            WHERE u.numero_documento_usuario=%s
            GROUP BY u.numero_documento_usuario,r.nombre;
        """,(documento,))
        r=cur.fetchone()
        if not r:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")
        return r
    finally:
        cur.close()

@router.put("/usuarios/{documento}",tags=["Usuarios"])
def editar_usuario(documento:int,data:UsuarioUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cambios=data.model_dump(exclude_unset=True)
    id_especialidad=cambios.pop("id_especialidad",None)

    if not cambios and id_especialidad is None:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"usuarios","numero_documento_usuario",documento)
        if not anterior:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        if "id_rol" in cambios:
            cur.execute(
                "SELECT 1 FROM roles WHERE id_rol=%s AND is_active=TRUE;",
                (cambios["id_rol"],)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400,detail="Rol inválido")

        campos=[]
        valores=[]

        for k,v in cambios.items():
            campos.append(f"{k}=%s")
            valores.append(v)

        if campos:
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
        else:
            cur.execute(
                "UPDATE usuarios SET updated_at=now() WHERE numero_documento_usuario=%s RETURNING *;",
                (documento,)
            )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"usuarios",documento,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        rol_final=cambios.get("id_rol",anterior["id_rol"])
        if "id_rol" in cambios or id_especialidad is not None:
            _asignar_especialidad(cur,documento,rol_final,id_especialidad)
        if "id_rol" in cambios:
            vincular_paciente(cur,documento,cambios["id_rol"],u["numero_documento_usuario"])

        db.commit()

        d=dict(nuevo)
        d.pop("password_hash",None)
        return d

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.delete("/usuarios/{documento}",tags=["Usuarios"])
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

@router.patch("/usuarios/{documento}/restaurar",tags=["Usuarios"])
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
