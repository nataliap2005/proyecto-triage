# Endpoints de gestión de usuarios.
# El desbloqueo permanece en auth/router.py porque pertenece a la seguridad de acceso.

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from core.eventos import publicar
from core.security import hash_password
from core.cifrado import cifrar,cifrar_campos
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
    # Campos clínicos opcionales usados solo cuando el rol es Paciente.
    # Permiten que crear la cuenta también cree su ficha clínica si aún no existe.
    tipo_documento:str|None=Field(default=None,max_length=20)
    fecha_nacimiento:str|None=None
    genero_fhir:str|None=None
    direccion:str|None=Field(default=None,max_length=200)
    municipio_residencia:str|None=Field(default=None,max_length=100)
    zona_residencia:str|None=None

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

def asegurar_paciente_para_cuenta(cur,data,admin_doc):
    """Para una cuenta con rol Paciente garantiza que exista la ficha clínica.

    - Si la ficha ya existe sin cuenta, la vincula.
    - Si no existe, la crea con el mismo documento y la vincula.
    La atención clínica NO depende de tener cuenta: un médico puede crear la ficha
    por separado para pacientes que llegan a urgencias sin acceso al portal.
    """
    cur.execute("SELECT nombre FROM roles WHERE id_rol=%s;",(data.id_rol,))
    r=cur.fetchone()
    if not r or r["nombre"]!="Paciente":
        return {"vinculado":False,"creado":False}

    cur.execute("""
        SELECT * FROM pacientes
        WHERE numero_documento_paciente=%s AND is_deleted=FALSE;
    """,(data.numero_documento_usuario,))
    p=cur.fetchone()

    if p:
        if p.get("id_usuario") not in (None,data.numero_documento_usuario):
            raise HTTPException(status_code=409,detail="La ficha clínica ya está vinculada a otra cuenta")
        if p.get("id_usuario") is None:
            cur.execute("""
                UPDATE pacientes SET id_usuario=%s,updated_at=now()
                WHERE numero_documento_paciente=%s
                RETURNING *;
            """,(data.numero_documento_usuario,data.numero_documento_usuario))
            p=cur.fetchone()
            registrar_auditoria(cur,"pacientes",data.numero_documento_usuario,"VINCULAR_CUENTA",admin_doc,nuevos=p)
        return {"vinculado":True,"creado":False}

    if not data.tipo_documento:
        raise HTTPException(status_code=400,detail="Para crear una cuenta Paciente nueva debe indicar tipo_documento")

    genero=data.genero_fhir if data.genero_fhir in (None,"male","female","other","unknown") else None
    zona=data.zona_residencia if data.zona_residencia in (None,"urbana","rural_dispersa") else None
    cur.execute("""
        INSERT INTO pacientes(
            numero_documento_paciente,id_usuario,tipo_documento,nombres,apellidos,
            fecha_nacimiento,genero_fhir,telefono,direccion,municipio_residencia,zona_residencia
        ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        RETURNING *;
    """,(
        data.numero_documento_usuario,data.numero_documento_usuario,data.tipo_documento,
        data.nombres,data.apellidos,data.fecha_nacimiento or None,genero,cifrar(data.telefono,"telefono"),
        cifrar(data.direccion,"direccion"),data.municipio_residencia,zona
    ))
    p=cur.fetchone()
    registrar_auditoria(cur,"pacientes",data.numero_documento_usuario,"CREAR",admin_doc,nuevos=p)
    return {"vinculado":True,"creado":True}

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
            data.email,cifrar(data.telefono,"telefono")
        ))

        nuevo=cur.fetchone()
        registrar_auditoria(
            cur,"usuarios",data.numero_documento_usuario,"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        _asignar_especialidad(cur,data.numero_documento_usuario,data.id_rol,data.id_especialidad)
        paciente_info=asegurar_paciente_para_cuenta(
            cur,data,u["numero_documento_usuario"]
        )
        db.commit()

        d=dict(nuevo)
        d.pop("password_hash",None)
        d["paciente_vinculado"]=paciente_info["vinculado"]
        d["paciente_creado"]=paciente_info["creado"]
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
                u.email,u.telefono,u.estado,u.is_deleted,u.id_rol,r.nombre AS rol,
                MIN(ue.id_especialidad) AS id_especialidad,
                EXISTS(SELECT 1 FROM pacientes p WHERE p.numero_documento_paciente=u.numero_documento_usuario AND p.is_deleted=FALSE) AS paciente_registrado,
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
                EXISTS(SELECT 1 FROM pacientes p WHERE p.numero_documento_paciente=u.numero_documento_usuario AND p.is_deleted=FALSE) AS paciente_registrado,
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

        # Un médico con encuentros activos no puede desactivarse ni cambiar de rol por
        # esta ruta: debe usarse DELETE /usuarios/{doc}?medico_reemplazo=... (reasigna).
        if cambios.get("estado") is False or ("id_rol" in cambios and cambios["id_rol"]!=anterior["id_rol"]):
            if _nombre_rol(cur,anterior["id_rol"])=="Medico":
                cur.execute("""
                    SELECT count(*) AS n FROM encuentros
                    WHERE medico_responsable=%s AND is_deleted=FALSE AND estado<>'finalizado';
                """,(documento,))
                if cur.fetchone()["n"]:
                    raise HTTPException(status_code=409,detail="El médico tiene encuentros activos. Use la opción Eliminar para reasignarlos a otro médico antes de desactivarlo o cambiar su rol")

        if "id_rol" in cambios:
            cur.execute(
                "SELECT 1 FROM roles WHERE id_rol=%s AND is_active=TRUE;",
                (cambios["id_rol"],)
            )
            if not cur.fetchone():
                raise HTTPException(status_code=400,detail="Rol inválido")

        campos=[]
        valores=[]

        # R27: el teléfono se guarda cifrado
        for k,v in cifrar_campos(cambios).items():
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


@router.get("/usuarios/{documento}/impacto-desactivacion",tags=["Usuarios"])
def impacto_desactivacion(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT us.numero_documento_usuario,us.username,us.nombres,us.apellidos,r.nombre AS rol
            FROM usuarios us JOIN roles r ON r.id_rol=us.id_rol
            WHERE us.numero_documento_usuario=%s;
        """,(documento,))
        objetivo=cur.fetchone()
        if not objetivo:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        encuentros=[]
        disponibles=[]
        if objetivo["rol"]=="Medico":
            cur.execute("""
                SELECT e.id_encuentro,e.id_paciente,e.estado,e.motivo_consulta,
                       p.nombres AS paciente_nombres,p.apellidos AS paciente_apellidos
                FROM encuentros e
                JOIN pacientes p ON p.numero_documento_paciente=e.id_paciente
                WHERE e.medico_responsable=%s
                  AND e.is_deleted=FALSE
                  AND e.estado<>'finalizado'
                ORDER BY e.fecha_hora_ingreso;
            """,(documento,))
            encuentros=cur.fetchall()
            cur.execute("""
                SELECT us.numero_documento_usuario,us.username,us.nombres,us.apellidos
                FROM usuarios us JOIN roles r ON r.id_rol=us.id_rol
                WHERE r.nombre='Medico'
                  AND us.estado=TRUE AND us.is_deleted=FALSE
                  AND us.numero_documento_usuario<>%s
                ORDER BY us.nombres,us.apellidos;
            """,(documento,))
            disponibles=cur.fetchall()
        return {"usuario":objetivo,"encuentros_activos":encuentros,"medicos_disponibles":disponibles}
    finally:
        cur.close()

@router.delete("/usuarios/{documento}",tags=["Usuarios"])
def eliminar_usuario(documento:int,medico_reemplazo:int|None=None,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    reasignados=[]
    reemplazo_notificar=None
    try:
        anterior=obtener_registro(cur,"usuarios","numero_documento_usuario",documento)
        if not anterior:
            raise HTTPException(status_code=404,detail="Usuario no encontrado")

        cur.execute("SELECT nombre FROM roles WHERE id_rol=%s;",(anterior["id_rol"],))
        rr=cur.fetchone()
        rol=rr["nombre"] if rr else None

        if rol=="Medico":
            cur.execute("""
                SELECT id_encuentro FROM encuentros
                WHERE medico_responsable=%s AND is_deleted=FALSE AND estado<>'finalizado'
                ORDER BY id_encuentro;
            """,(documento,))
            reasignados=[r["id_encuentro"] for r in cur.fetchall()]
            if reasignados:
                if medico_reemplazo is None:
                    raise HTTPException(status_code=409,detail={
                        "codigo":"REASIGNACION_REQUERIDA",
                        "mensaje":"El médico tiene encuentros activos. Debe seleccionar un médico de reemplazo antes de desactivarlo.",
                        "encuentros_activos":len(reasignados)
                    })
                cur.execute("""
                    SELECT 1 FROM usuarios us JOIN roles r ON r.id_rol=us.id_rol
                    WHERE us.numero_documento_usuario=%s AND r.nombre='Medico'
                      AND us.estado=TRUE AND us.is_deleted=FALSE
                      AND us.numero_documento_usuario<>%s;
                """,(medico_reemplazo,documento))
                if not cur.fetchone():
                    raise HTTPException(status_code=400,detail="El médico de reemplazo no es válido o no está activo")

                cur.execute("""
                    UPDATE encuentros
                    SET medico_responsable=%s,updated_at=now()
                    WHERE medico_responsable=%s AND is_deleted=FALSE AND estado<>'finalizado'
                    RETURNING id_encuentro;
                """,(medico_reemplazo,documento))
                reasignados=[r["id_encuentro"] for r in cur.fetchall()]
                for eid in reasignados:
                    registrar_auditoria(
                        cur,"encuentros",eid,"REASIGNAR_MEDICO",u["numero_documento_usuario"],
                        anteriores={"medico_responsable":documento},
                        nuevos={"medico_responsable":medico_reemplazo}
                    )
                reemplazo_notificar=medico_reemplazo

        cur.execute("""
            UPDATE usuarios
            SET is_deleted=TRUE,estado=FALSE,deleted_at=now(),deleted_by=%s,updated_at=now()
            WHERE numero_documento_usuario=%s
            RETURNING *;
        """,(u["numero_documento_usuario"],documento))
        nuevo=cur.fetchone()
        registrar_auditoria(cur,"usuarios",documento,"ELIMINAR",u["numero_documento_usuario"],anterior,nuevo)
        db.commit()
    except:
        db.rollback()
        raise
    finally:
        cur.close()

    if reemplazo_notificar is not None:
        publicar(
            db,[reemplazo_notificar],"reasignacion_medica",
            f"Se le asignaron {len(reasignados)} encuentros activos por desactivación del médico {documento}.",
            datos={"medico_anterior":documento,"encuentros":reasignados}
        )
    return {"mensaje":"Usuario eliminado lógicamente","encuentros_reasignados":reasignados,"medico_reemplazo":medico_reemplazo}

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
