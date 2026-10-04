# Contiene la lógica reutilizable de autenticación y autorización.
# Gestiona validación de credenciales, JWT, control de roles, bloqueo tras
# 3 intentos fallidos y registro de eventos de autenticación en auth_log.

from fastapi import Depends,HTTPException,status
from fastapi.security import HTTPAuthorizationCredentials,HTTPBearer
from psycopg2.extras import RealDictCursor

from core.database import get_db
from core.security import crear_token,decodificar_token,verificar_password
from core.eventos import publicar, usuarios_por_rol

security=HTTPBearer()
MAX_INTENTOS_FALLIDOS=3


def registrar_evento_auth(
    cursor,
    username_intentado:str,
    evento:str,
    exitoso:bool,
    numero_documento_usuario:int|None=None,
    detalle:str|None=None
):
    """Registra un evento de autenticación en la tabla auth_log."""
    cursor.execute("""
        INSERT INTO auth_log(
            numero_documento_usuario,
            username_intentado,
            evento,
            exitoso,
            detalle
        )
        VALUES(%s,%s,%s,%s,%s);
    """,(
        numero_documento_usuario,
        username_intentado,
        evento,
        exitoso,
        detalle
    ))


def autenticar_usuario(username:str,password:str,db):
    """
    Valida credenciales y aplica el control de tres intentos fallidos.
    Si la contraseña es correcta reinicia el contador y registra LOGIN_OK.
    """
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,
                u.username,
                u.password_hash,
                u.estado,
                u.is_deleted,
                u.intentos_fallidos,
                u.bloqueado,
                u.bloqueado_at,
                r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE u.username=%s;
        """,(username,))

        usuario=cur.fetchone()

        # Usuario inexistente: se registra el intento sin revelar si la cuenta existe.
        if not usuario:
            registrar_evento_auth(
                cur,
                username_intentado=username,
                evento="LOGIN_FALLIDO",
                exitoso=False,
                detalle="Credenciales incorrectas"
            )
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales incorrectas"
            )

        documento=usuario["numero_documento_usuario"]

        # Las cuentas eliminadas o deshabilitadas no pueden autenticarse.
        if not usuario["estado"] or usuario["is_deleted"]:
            registrar_evento_auth(
                cur,
                username_intentado=username,
                numero_documento_usuario=documento,
                evento="LOGIN_FALLIDO",
                exitoso=False,
                detalle="Cuenta no disponible"
            )
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Credenciales incorrectas"
            )

        # Una cuenta bloqueada permanece bloqueada aunque la contraseña sea correcta.
        if usuario["bloqueado"]:
            registrar_evento_auth(
                cur,
                username_intentado=username,
                numero_documento_usuario=documento,
                evento="LOGIN_FALLIDO",
                exitoso=False,
                detalle="Intento de acceso a una cuenta bloqueada"
            )
            db.commit()

            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario bloqueado. Contacte al administrador"
            )

        # Contraseña incorrecta: incrementa contador y bloquea al llegar a 3.
        if not verificar_password(password,usuario["password_hash"]):
            nuevos_intentos=int(usuario["intentos_fallidos"] or 0)+1
            debe_bloquear=nuevos_intentos>=MAX_INTENTOS_FALLIDOS

            cur.execute("""
                UPDATE usuarios
                SET intentos_fallidos=%s,
                    bloqueado=%s,
                    bloqueado_at=CASE
                        WHEN %s THEN now()
                        ELSE bloqueado_at
                    END,
                    updated_at=now()
                WHERE numero_documento_usuario=%s;
            """,(
                nuevos_intentos,
                debe_bloquear,
                debe_bloquear,
                documento
            ))

            registrar_evento_auth(
                cur,
                username_intentado=username,
                numero_documento_usuario=documento,
                evento="LOGIN_FALLIDO",
                exitoso=False,
                detalle=f"Intento fallido {nuevos_intentos} de {MAX_INTENTOS_FALLIDOS}"
            )

            if debe_bloquear:
                registrar_evento_auth(
                    cur,
                    username_intentado=username,
                    numero_documento_usuario=documento,
                    evento="USUARIO_BLOQUEADO",
                    exitoso=False,
                    detalle=f"Cuenta bloqueada tras {MAX_INTENTOS_FALLIDOS} intentos fallidos"
                )

            db.commit()

            if debe_bloquear:
                # R19: el bloqueo avisa a todos los Admin, en vivo y en su bandeja.
                publicar(
                    db,
                    usuarios_por_rol(db, "Admin"),
                    tipo="cuenta_bloqueada",
                    mensaje=f"La cuenta '{username}' fue bloqueada tras "
                            f"{MAX_INTENTOS_FALLIDOS} intentos fallidos",
                    datos={
                        "usuario_bloqueado": username,
                        "documento_usuario": documento,
                    },
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Usuario bloqueado. Contacte al administrador"
                )

            restantes=MAX_INTENTOS_FALLIDOS-nuevos_intentos
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Credenciales incorrectas. Intentos restantes: {restantes}"
            )

        # Login correcto: reinicia los intentos fallidos.
        cur.execute("""
            UPDATE usuarios
            SET intentos_fallidos=0,
                bloqueado_at=NULL,
                updated_at=now()
            WHERE numero_documento_usuario=%s;
        """,(documento,))

        registrar_evento_auth(
            cur,
            username_intentado=username,
            numero_documento_usuario=documento,
            evento="LOGIN_OK",
            exitoso=True,
            detalle="Inicio de sesión exitoso"
        )

        db.commit()
        return dict(usuario)

    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def generar_respuesta_login(usuario:dict)->dict:
    """Genera la respuesta estándar del login con token JWT y rol."""
    return {
        "access_token":crear_token(usuario),
        "token_type":"bearer",
        "rol":usuario["rol"]
    }


def usuario_desde_token(token: str, db) -> dict:
    """Valida un JWT y devuelve el usuario activo. Lo usan el Bearer y el canal SSE (?token=)."""
    try:
        payload = decodificar_token(token)
        documento = int(payload["sub"])
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o vencido"
        )

    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT
                u.numero_documento_usuario,
                u.username,
                u.id_rol,
                u.bloqueado,
                r.nombre AS rol
            FROM usuarios u
            JOIN roles r ON r.id_rol=u.id_rol
            WHERE u.numero_documento_usuario=%s
              AND u.estado=TRUE
              AND u.is_deleted=FALSE
              AND u.bloqueado=FALSE;
        """, (documento,))
        usuario = cur.fetchone()
    finally:
        cur.close()

    if not usuario:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuario no disponible"
        )
    return dict(usuario)


def usuario_actual(
    credenciales: HTTPAuthorizationCredentials = Depends(security),
    db=Depends(get_db)):
    """Dependencia estándar para rutas protegidas con Authorization: Bearer."""
    return usuario_desde_token(credenciales.credentials, db)

def requerir_roles(*roles):
    """Dependencia de FastAPI que permite el acceso solo a los roles indicados."""
    def dependencia(usuario=Depends(usuario_actual)):
        if usuario["rol"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tiene permisos para esta operación"
            )
        return usuario

    return dependencia

def desbloquear_usuario(documento:int,admin:dict,db):
    """
    Desbloquea una cuenta y reinicia sus intentos fallidos.
    Esta función debe invocarse desde un endpoint protegido exclusivamente para Admin.
    """
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                numero_documento_usuario,
                username,
                bloqueado,
                intentos_fallidos,
                is_deleted
            FROM usuarios
            WHERE numero_documento_usuario=%s;
        """,(documento,))

        usuario=cur.fetchone()

        if not usuario:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado"
            )

        if usuario["is_deleted"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No se puede desbloquear un usuario eliminado"
            )

        cur.execute("""
            UPDATE usuarios
            SET intentos_fallidos=0,
                bloqueado=FALSE,
                bloqueado_at=NULL,
                updated_at=now()
            WHERE numero_documento_usuario=%s
            RETURNING
                numero_documento_usuario,
                username,
                bloqueado,
                intentos_fallidos;
        """,(documento,))

        actualizado=cur.fetchone()

        registrar_evento_auth(
            cur,
            username_intentado=usuario["username"],
            numero_documento_usuario=documento,
            evento="USUARIO_DESBLOQUEADO",
            exitoso=True,
            detalle=f"Desbloqueado por Admin {admin['numero_documento_usuario']}"
        )

        db.commit()
        return dict(actualizado)

    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


def listar_auth_logs(db,limite:int=100):
    """Devuelve los eventos de autenticación más recientes para consulta del Admin."""
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT
                al.*,
                u.username AS username_usuario,
                u.nombres,
                u.apellidos
            FROM auth_log al
            LEFT JOIN usuarios u
              ON u.numero_documento_usuario=al.numero_documento_usuario
            ORDER BY al.fecha_hora DESC
            LIMIT %s;
        """,(limite,))

        return cur.fetchall()
    finally:
        cur.close()
