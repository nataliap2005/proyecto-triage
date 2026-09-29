from datetime import datetime,timedelta,timezone

import jwt
from pwdlib import PasswordHash

from core.config import JWT_ALGORITHM,JWT_EXPIRE_MINUTES,JWT_SECRET_KEY

password_hash=PasswordHash.recommended()


def hash_password(password:str)->str:
    return password_hash.hash(password)


def verificar_password(password:str,password_hash_guardado:str)->bool:
    return password_hash.verify(password,password_hash_guardado)


def crear_token(usuario)->str:
    now=datetime.now(timezone.utc)
    payload={
        "sub":str(usuario["numero_documento_usuario"]),
        "username":usuario["username"],
        "rol":usuario["rol"],
        "iat":now,
        "exp":now+timedelta(minutes=JWT_EXPIRE_MINUTES)
    }
    return jwt.encode(payload,JWT_SECRET_KEY,algorithm=JWT_ALGORITHM)


def decodificar_token(token:str)->dict:
    return jwt.decode(
        token,
        JWT_SECRET_KEY,
        algorithms=[JWT_ALGORITHM]
    )
