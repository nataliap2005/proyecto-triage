# R31: endpoints de identidad institucional.
#
#   POST /oauth/token              la institución cambia client_id + client_secret por un token
#   GET  /oauth/eventos            (Admin) bitácora de la autenticación institucional
#   GET  /institucion/yo           devuelve la identidad del token (sirve para probar)
#   POST /institucion/prueba-bundle  ejemplo de endpoint protegido con scope + nonce;
#                                    sin datos clínicos: solo demuestra 401 / 403 / 409.
#
# Los endpoints reales de recepción (Annie, R30/R33) se protegen con:
#     Depends(requerir_institucion("bundle:write", exigir_nonce=True))

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import JSONResponse

from auth.institucional import (
    emitir_token,
    error_oauth,
    listar_eventos,
    requerir_institucion,
)
from auth.service import requerir_roles
from core.database import get_db

router = APIRouter(tags=["R31 · Identidad institucional"])


@router.post("/oauth/token")
def oauth_token(
    grant_type: str = Form(...),
    client_id: str = Form(..., min_length=3, max_length=64),
    client_secret: str = Form(..., min_length=1, max_length=256),
    scope: str | None = Form(default=None, max_length=200),
    db=Depends(get_db),
):
    """OAuth2 client credentials. Cuerpo application/x-www-form-urlencoded."""
    if grant_type != "client_credentials":
        raise error_oauth(400, "unsupported_grant_type",
                           "Solo se admite grant_type=client_credentials")
    respuesta = emitir_token(client_id, client_secret, scope, db)
    # RFC 6749 §5.1: el token no debe guardarse en cachés.
    return JSONResponse(respuesta, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.get("/oauth/eventos")
def oauth_eventos(
    limite: int = Query(100, ge=1, le=500),
    db=Depends(get_db),
    admin=Depends(requerir_roles("Admin")),
):
    return listar_eventos(db, limite)


@router.get("/institucion/yo")
def institucion_yo(inst=Depends(requerir_institucion())):
    return inst


@router.post("/institucion/prueba-bundle")
def institucion_prueba_bundle(
    inst=Depends(requerir_institucion("bundle:write", exigir_nonce=True)),
):
    return {"estado": "autorizado", "institucion": inst["client_id"], "scopes": inst["scopes"]}
