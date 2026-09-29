# Define los endpoints HTTP relacionados con autenticación y seguridad de acceso.
# Incluye login, consulta del usuario autenticado, auditoría de autenticación
# y desbloqueo de cuentas por parte del administrador.

from fastapi import APIRouter,Depends,Query
from pydantic import BaseModel,Field

from core.database import get_db
from auth.service import (
    autenticar_usuario,
    desbloquear_usuario,
    generar_respuesta_login,
    listar_auth_logs,
    requerir_roles,
    usuario_actual
)

# Se usa sin prefix global para conservar /auth/* y permitir que el desbloqueo
# mantenga la ruta /usuarios/{documento}/desbloquear.
router=APIRouter()


class LoginIn(BaseModel):
    username:str=Field(
        min_length=3,
        max_length=50,
        pattern=r"^[A-Za-z0-9._-]+$"
    )
    password:str=Field(min_length=1)


@router.post("/auth/login",tags=["Autenticación"])
def login(datos:LoginIn,db=Depends(get_db)):
    usuario=autenticar_usuario(datos.username,datos.password,db)
    return generar_respuesta_login(usuario)


@router.get("/auth/me",tags=["Autenticación"])
def me(usuario=Depends(usuario_actual)):
    return usuario


@router.get("/auth/logs",tags=["Autenticación"])
def auth_logs(
    limite:int=Query(100,ge=1,le=500),
    db=Depends(get_db),
    admin=Depends(requerir_roles("Admin"))
):
    return listar_auth_logs(db,limite)


@router.patch("/usuarios/{documento}/desbloquear",tags=["Usuarios"])
def desbloquear(
    documento:int,
    db=Depends(get_db),
    admin=Depends(requerir_roles("Admin"))
):
    return desbloquear_usuario(documento,admin,db)
