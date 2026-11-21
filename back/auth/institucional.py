# R31: identidad institucional entre sistemas (OAuth2 "client credentials").
#
# Una institución socio se identifica con client_id + client_secret, recibe un
# token firmado de vida corta con permisos (scopes) y lo presenta en cada
# llamada. Aquí viven tres cosas:
#   1. emitir_token(): valida credenciales, bloquea tras intentos fallidos y firma el JWT.
#   2. requerir_institucion(): dependencia de FastAPI que exige token válido,
#      scope suficiente (401 sin token, 403 sin permiso) y, si se pide, un
#      nonce que no se haya usado antes (protección contra repetición).
#   3. Bitácora propia en oauth_eventos para cada decisión.
#   4. Modo de clave fija (API key por institución), que R31 también admite
#      ("client credentials o API key por institución"), para socios que no
#      piden token. Se activa solo con R30_ENTRADA_CLIENT_ID en pass.env: la
#      clave es el client_secret de esa institución (en la base solo está su
#      hash), así que rotarla o desactivarla con el script la revoca al instante
#      y sus permisos son los registrados. Como todo R31, solo abre los
#      endpoints de entrada del socio, nunca la API clínica.
#
# Diseño deliberado:
#  - El token institucional se firma con INSTITUCION_JWT_SECRET, distinto de
#    JWT_SECRET_KEY: un token de usuario no sirve aquí ni viceversa. Además
#    lleva typ="institucional" y una audiencia propia.
#  - Las variables se leen en el momento de uso (no al importar) para no romper
#    el arranque de quien aún no tenga la variable nueva en su pass.env.

import os
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from psycopg2.extras import RealDictCursor

from core.database import get_db
from core.security import hash_password, verificar_password

ALGORITMO = "HS256"
AUDIENCIA = "triaje-api-institucional"
TIPO_TOKEN = "institucional"
ISSUER_DEFECTO = "triaje-uao"

# Permisos que una institución puede tener. R33 usará task:write para devolver
# aceptación/rechazo de una remisión.
# R31: las credenciales del socio solo sirven para el endpoint de entrada; no dan acceso a la API clinica
SCOPES_VALIDOS = ("bundle:write", "task:write")

MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 15
TOKEN_MINUTOS_DEFECTO = 10
TOKEN_MINUTOS_MAXIMO = 30          # los nonces se conservan 1 h: siempre > vida del token
NONCE_RETENCION_HORAS = 1
PATRON_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")

_bearer = HTTPBearer(auto_error=False)
_hash_ficticio = None


# ----------------------------------------------------------------------------
# Configuración y utilidades
# ----------------------------------------------------------------------------
def _secreto() -> str:
    secreto = os.getenv("INSTITUCION_JWT_SECRET", "")
    if len(secreto) < 32:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La autenticación institucional no está configurada",
        )
    if secreto == os.getenv("JWT_SECRET_KEY"):
        # Misma llave que los usuarios: se perdería el aislamiento entre ambos mundos.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="La autenticación institucional está mal configurada",
        )
    return secreto


def _issuer() -> str:
    return os.getenv("INSTITUCION_ISSUER", ISSUER_DEFECTO)


def _minutos_token() -> int:
    try:
        minutos = int(os.getenv("INSTITUCION_TOKEN_MINUTOS", TOKEN_MINUTOS_DEFECTO))
    except ValueError:
        minutos = TOKEN_MINUTOS_DEFECTO
    return max(1, min(minutos, TOKEN_MINUTOS_MAXIMO))


def _verificar_con_hash_ficticio(secreto: str) -> None:
    """Gasta el mismo tiempo que una verificación real cuando el cliente no existe."""
    global _hash_ficticio
    if _hash_ficticio is None:
        _hash_ficticio = hash_password("cliente-inexistente")
    verificar_password(secreto, _hash_ficticio)


def registrar_evento(cur, client_id, evento: str, exitoso: bool, detalle: str | None = None) -> None:
    cur.execute(
        """
        INSERT INTO oauth_eventos(client_id, evento, exitoso, detalle)
        VALUES (%s, %s, %s, %s);
        """,
        ((client_id or None) and str(client_id)[:64], evento, exitoso, detalle),
    )


def es_jwt(valor: str) -> bool:
    partes = valor.split(".")
    return len(partes) == 3 and all(partes)


def clave_fija_client_id() -> str | None:
    """Institución autorizada a entrar con clave fija, o None si el modo está apagado."""
    return os.getenv("R30_ENTRADA_CLIENT_ID", "").strip() or None


def clave_fija_valida(db, client_id: str, clave: str) -> bool:
    """La clave fija es el client_secret de la institución; se compara contra su hash."""
    if not clave or len(clave) > 256:
        return False
    cur = db.cursor()
    try:
        cur.execute("SELECT secret_hash FROM clientes_institucionales WHERE client_id = %s;", (client_id,))
        fila = cur.fetchone()
    finally:
        cur.close()
    if fila is None:
        _verificar_con_hash_ficticio(clave)
        return False
    try:
        return bool(verificar_password(clave, fila[0]))
    except Exception:
        return False


def error_oauth(codigo_http: int, error: str, descripcion: str, cabeceras: dict | None = None):
    return HTTPException(
        status_code=codigo_http,
        detail={"error": error, "error_description": descripcion},
        headers=cabeceras,
    )


# ----------------------------------------------------------------------------
# 1. Emisión del token
# ----------------------------------------------------------------------------
def emitir_token(client_id: str, client_secret: str, scope_solicitado: str | None, db) -> dict:
    secreto_firma = _secreto()  # falla pronto (503) si falta configuración
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            """
            SELECT client_id, nombre, secret_hash, scopes, activo,
                   intentos_fallidos,
                   (bloqueado_hasta IS NOT NULL AND bloqueado_hasta > now()) AS bloqueado
            FROM clientes_institucionales
            WHERE client_id = %s
            FOR UPDATE;
            """,
            (client_id,),
        )
        cliente = cur.fetchone()

        if cliente is None:
            _verificar_con_hash_ficticio(client_secret)
            registrar_evento(cur, client_id, "CREDENCIAL_INVALIDA", False, "Cliente desconocido")
            db.commit()
            raise error_oauth(401, "invalid_client", "Credenciales inválidas",
                               {"WWW-Authenticate": "Basic"})

        if not cliente["activo"]:
            _verificar_con_hash_ficticio(client_secret)
            registrar_evento(cur, client_id, "CREDENCIAL_INVALIDA", False, "Cliente desactivado")
            db.commit()
            raise error_oauth(401, "invalid_client", "Credenciales inválidas",
                               {"WWW-Authenticate": "Basic"})

        if cliente["bloqueado"]:
            registrar_evento(cur, client_id, "CLIENTE_BLOQUEADO", False,
                             "Intento con el cliente bloqueado temporalmente")
            db.commit()
            raise error_oauth(429, "temporarily_unavailable",
                               "Demasiados intentos fallidos. Intente más tarde",
                               {"Retry-After": str(BLOQUEO_MINUTOS * 60)})

        if not verificar_password(client_secret, cliente["secret_hash"]):
            intentos = int(cliente["intentos_fallidos"] or 0) + 1
            if intentos >= MAX_INTENTOS:
                cur.execute(
                    """
                    UPDATE clientes_institucionales
                    SET intentos_fallidos = 0,
                        bloqueado_hasta = now() + make_interval(mins => %s)
                    WHERE client_id = %s;
                    """,
                    (BLOQUEO_MINUTOS, client_id),
                )
                registrar_evento(cur, client_id, "CLIENTE_BLOQUEADO", False,
                                 f"Bloqueado {BLOQUEO_MINUTOS} min tras {MAX_INTENTOS} intentos fallidos")
            else:
                cur.execute(
                    "UPDATE clientes_institucionales SET intentos_fallidos = %s WHERE client_id = %s;",
                    (intentos, client_id),
                )
            registrar_evento(cur, client_id, "CREDENCIAL_INVALIDA", False,
                             f"Secreto incorrecto (intento {intentos} de {MAX_INTENTOS})")
            db.commit()
            raise error_oauth(401, "invalid_client", "Credenciales inválidas",
                               {"WWW-Authenticate": "Basic"})

        # Credenciales correctas: decidir scopes (solo un subconjunto de los permitidos).
        # Solo se conceden permisos que el sistema aun reconoce (R31: sin acceso a la API clinica)
        permitidos = [s for s in cliente["scopes"] if s in SCOPES_VALIDOS]
        if scope_solicitado and scope_solicitado.strip():
            pedidos = scope_solicitado.split()
            if not set(pedidos).issubset(set(permitidos)):
                registrar_evento(cur, client_id, "SCOPE_INVALIDO", False,
                                 "Pidió permisos que no tiene asignados")
                db.commit()
                raise error_oauth(400, "invalid_scope",
                                   "Alguno de los permisos pedidos no está autorizado")
            concedidos = [s for s in permitidos if s in set(pedidos)]
        else:
            concedidos = permitidos

        minutos = _minutos_token()
        ahora = datetime.now(timezone.utc)
        jti = uuid.uuid4().hex
        token = jwt.encode(
            {
                "iss": _issuer(),
                "aud": AUDIENCIA,
                "sub": client_id,
                "typ": TIPO_TOKEN,
                "scope": " ".join(concedidos),
                "jti": jti,
                "iat": ahora,
                "exp": ahora + timedelta(minutes=minutos),
            },
            secreto_firma,
            algorithm=ALGORITMO,
        )

        cur.execute(
            """
            UPDATE clientes_institucionales
            SET intentos_fallidos = 0, bloqueado_hasta = NULL
            WHERE client_id = %s;
            """,
            (client_id,),
        )
        registrar_evento(cur, client_id, "TOKEN_EMITIDO", True,
                         f"scopes={' '.join(concedidos)}; jti={jti}; vigencia={minutos} min")
        db.commit()
        return {
            "access_token": token,
            "token_type": "Bearer",
            "expires_in": minutos * 60,
            "scope": " ".join(concedidos),
        }
    except HTTPException:
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


# ----------------------------------------------------------------------------
# 2. Verificación en cada llamada
# ----------------------------------------------------------------------------
def decodificar_token(token: str) -> dict:
    """Devuelve los claims si el token institucional es válido; si no, lanza jwt.PyJWTError."""
    claims = jwt.decode(
        token,
        _secreto(),
        algorithms=[ALGORITMO],
        audience=AUDIENCIA,
        issuer=_issuer(),
        options={"require": ["exp", "iat", "sub", "scope", "jti", "iss", "aud", "typ"]},
    )
    if claims.get("typ") != TIPO_TOKEN:
        raise jwt.InvalidTokenError("Tipo de token incorrecto")
    return claims


def _no_autenticado(detalle: str):
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detalle,
        headers={"WWW-Authenticate": 'Bearer error="invalid_token"'},
    )


def requerir_institucion(scope: str | None = None, exigir_nonce: bool = False):
    """
    Dependencia de FastAPI para endpoints que consumen otras instituciones.

        @router.post("/algo")
        def algo(inst=Depends(requerir_institucion("bundle:write", exigir_nonce=True))): ...

    401: falta el token, está vencido o fue alterado, o la institución fue desactivada.
    403: el token es válido pero no tiene el scope pedido.
    400/409: falta el nonce, o ya se usó (repetición).
    """
    if scope is not None and scope not in SCOPES_VALIDOS:
        raise ValueError(f"Scope desconocido: {scope}")

    def dependencia(
        credenciales: HTTPAuthorizationCredentials | None = Depends(_bearer),
        x_nonce: str | None = Header(default=None),
        x_system_key: str | None = Header(default=None),
        x_api_key: str | None = Header(default=None),
        db=Depends(get_db),
    ) -> dict:
        def rechazar(client_id, evento: str, detalle: str, mensaje: str):
            cur_e = db.cursor()
            try:
                registrar_evento(cur_e, client_id, evento, False, detalle)
                db.commit()
            finally:
                cur_e.close()
            raise _no_autenticado(mensaje)

        bearer = (credenciales.credentials.strip()
                  if credenciales is not None and credenciales.scheme.lower() == "bearer" else None)
        # Una clave fija llega en X-System-Key, X-API-Key o como Bearer que no es un JWT.
        clave = (x_system_key or x_api_key or "").strip() or (
            bearer if bearer and not es_jwt(bearer) else None)

        if clave is not None:
            client_id = clave_fija_client_id()
            if not client_id or not clave_fija_valida(db, client_id, clave):
                rechazar(client_id, "CLAVE_RECHAZADA", "Clave fija inválida o modo no habilitado",
                         "Clave institucional inválida")
            modo_clave, scopes_token = True, None
        elif bearer is None:
            raise _no_autenticado("Falta la credencial institucional")
        else:
            try:
                claims = decodificar_token(bearer)
            except HTTPException:
                raise                                   # configuración (503)
            except jwt.PyJWTError:
                rechazar(None, "TOKEN_RECHAZADO", "Token inválido o vencido",
                         "Token institucional inválido o vencido")
            client_id = claims["sub"]
            modo_clave, scopes_token = False, set(claims["scope"].split())
        cur = db.cursor(cursor_factory=RealDictCursor)
        try:
            # El token solo vale si la institución sigue activa y conserva el permiso HOY:
            # así desactivar o quitar un scope surte efecto sin esperar a que venza el token.
            cur.execute(
                "SELECT nombre, scopes, activo FROM clientes_institucionales WHERE client_id = %s;",
                (client_id,),
            )
            cliente = cur.fetchone()
            if cliente is None or not cliente["activo"]:
                registrar_evento(cur, client_id, "TOKEN_RECHAZADO", False,
                                 "Institución desactivada o inexistente")
                db.commit()
                raise _no_autenticado("Token institucional inválido o vencido")

            # Con clave fija, los permisos son los que la institución tiene registrados.
            scopes_vigentes = (set(cliente["scopes"]) if scopes_token is None
                               else scopes_token.intersection(cliente["scopes"]))

            if scope is not None and scope not in scopes_vigentes:
                registrar_evento(cur, client_id, "SCOPE_DENEGADO", False,
                                 f"Requería {scope}; tenía {' '.join(sorted(scopes_vigentes)) or 'ninguno'}")
                db.commit()
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="La institución no tiene permiso para esta operación",
                    headers={"WWW-Authenticate": f'Bearer error="insufficient_scope", scope="{scope}"'},
                )

            # Con clave fija el nonce es opcional (ese socio no lo envía); si llega se
            # valida igual. Una remisión repetida se sigue rechazando con 409.
            if exigir_nonce and not (modo_clave and not x_nonce):
                if not x_nonce or not PATRON_NONCE.match(x_nonce):
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Falta la cabecera X-Nonce (16 a 128 caracteres: letras, números, - y _)",
                    )
                cur.execute(
                    "DELETE FROM oauth_nonces WHERE usado_en < now() - make_interval(hours => %s);",
                    (NONCE_RETENCION_HORAS,),
                )
                cur.execute(
                    """
                    INSERT INTO oauth_nonces(client_id, nonce)
                    VALUES (%s, %s)
                    ON CONFLICT (client_id, nonce) DO NOTHING
                    RETURNING 1;
                    """,
                    (client_id, x_nonce),
                )
                if cur.fetchone() is None:
                    registrar_evento(cur, client_id, "NONCE_REPETIDO", False,
                                     "Solicitud repetida: el nonce ya se había usado")
                    db.commit()
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="Solicitud repetida: el nonce ya fue usado",
                    )
            if modo_clave:
                registrar_evento(cur, client_id, "CLAVE_ACEPTADA", True,
                                 f"Acceso con clave fija ({scope or 'sin permiso específico'})")
            db.commit()
            return {
                "client_id": client_id,
                "nombre": cliente["nombre"],
                "scopes": sorted(scopes_vigentes),
                "autenticacion": "clave_fija" if modo_clave else "token",
            }
        except HTTPException:
            raise
        except Exception:
            db.rollback()
            raise
        finally:
            cur.close()

    return dependencia


# ----------------------------------------------------------------------------
# 3. Consulta para el Admin
# ----------------------------------------------------------------------------
def listar_eventos(db, limite: int = 100) -> list:
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(
            "SELECT * FROM oauth_eventos ORDER BY fecha_hora DESC, id_evento DESC LIMIT %s;",
            (limite,),
        )
        return cur.fetchall()
    finally:
        cur.close()