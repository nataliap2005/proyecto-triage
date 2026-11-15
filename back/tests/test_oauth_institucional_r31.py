"""Pruebas puras de R31 (identidad institucional). No usan base de datos ni red.

Desde back/:  python -m pytest tests/test_oauth_institucional_r31.py -q
La verificación completa contra la API real está en scripts/prueba_r31_http.py.
"""
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException

from auth import institucional as inst

SECRETO = "secreto-institucional-de-prueba-no-real-0123456789"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("INSTITUCION_JWT_SECRET", SECRETO)
    monkeypatch.setenv("JWT_SECRET_KEY", "llave-de-usuarios-distinta-de-prueba-0123456789")
    monkeypatch.delenv("INSTITUCION_ISSUER", raising=False)
    monkeypatch.delenv("INSTITUCION_TOKEN_MINUTOS", raising=False)


def token(**cambios):
    ahora = datetime.now(timezone.utc)
    claims = {
        "iss": "triaje-uao", "aud": inst.AUDIENCIA, "sub": "socio-demo", "typ": inst.TIPO_TOKEN,
        "scope": "bundle:write", "jti": "abc", "iat": ahora, "exp": ahora + timedelta(minutes=5),
    }
    claims.update(cambios)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, SECRETO, algorithm="HS256")


def test_token_valido_se_decodifica():
    assert inst.decodificar_token(token())["sub"] == "socio-demo"


@pytest.mark.parametrize("cambios", [
    {"exp": datetime.now(timezone.utc) - timedelta(minutes=1)},   # vencido
    {"aud": "otra-audiencia"},                                    # audiencia equivocada
    {"iss": "otro-emisor"},                                       # emisor equivocado
    {"typ": "usuario"},                                           # tipo equivocado
    {"typ": None},                                                # sin tipo
    {"scope": None},                                              # sin scope
])
def test_token_invalido_se_rechaza(cambios):
    with pytest.raises(jwt.PyJWTError):
        inst.decodificar_token(token(**cambios))


def test_token_firmado_con_otra_llave_se_rechaza():
    falso = jwt.encode({"sub": "x"}, "otra-llave-cualquiera-de-mas-de-32-caracteres", algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        inst.decodificar_token(falso)


def test_token_de_usuario_no_sirve_como_institucional():
    # Mismo formato JWT pero firmado con la llave de los usuarios.
    ahora = datetime.now(timezone.utc)
    de_usuario = jwt.encode(
        {"sub": "123", "username": "x", "rol": "Admin", "iat": ahora, "exp": ahora + timedelta(minutes=5)},
        "llave-de-usuarios-distinta-de-prueba-0123456789", algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        inst.decodificar_token(de_usuario)


def test_algoritmo_none_se_rechaza():
    sin_firma = jwt.encode({"sub": "socio-demo"}, None, algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        inst.decodificar_token(sin_firma)


def test_sin_secreto_configurado_responde_503(monkeypatch):
    monkeypatch.delenv("INSTITUCION_JWT_SECRET")
    with pytest.raises(HTTPException) as e:
        inst.decodificar_token(token())
    assert e.value.status_code == 503


def test_secreto_corto_responde_503(monkeypatch):
    monkeypatch.setenv("INSTITUCION_JWT_SECRET", "corto")
    with pytest.raises(HTTPException) as e:
        inst.decodificar_token(token())
    assert e.value.status_code == 503


def test_secreto_igual_al_de_usuarios_responde_503(monkeypatch):
    monkeypatch.setenv("INSTITUCION_JWT_SECRET", "llave-de-usuarios-distinta-de-prueba-0123456789")
    with pytest.raises(HTTPException) as e:
        inst.decodificar_token(token())
    assert e.value.status_code == 503


@pytest.mark.parametrize("valor,esperado", [
    (None, 15), ("5", 5), ("0", 1), ("-3", 1), ("999", 30), ("abc", 15),
])
def test_vigencia_del_token_se_limita(monkeypatch, valor, esperado):
    if valor is None:
        monkeypatch.delenv("INSTITUCION_TOKEN_MINUTOS", raising=False)
    else:
        monkeypatch.setenv("INSTITUCION_TOKEN_MINUTOS", valor)
    assert inst._minutos_token() == esperado


def test_vigencia_maxima_menor_que_retencion_de_nonces():
    # Si un nonce se olvidara antes de que venza el token, se podría repetir la solicitud.
    assert inst.TOKEN_MINUTOS_MAXIMO < inst.NONCE_RETENCION_HORAS * 60


@pytest.mark.parametrize("nonce,valido", [
    ("a" * 16, True), ("Abc_def-123456789", True), ("a" * 128, True),
    ("a" * 15, False), ("a" * 129, False), ("con espacios 123456789", False),
    ("raro;DROP TABLE x;--", False), ("", False),
])
def test_formato_del_nonce(nonce, valido):
    assert bool(inst.PATRON_NONCE.match(nonce)) is valido


def test_scope_desconocido_se_detecta_al_declarar_el_endpoint():
    with pytest.raises(ValueError):
        inst.requerir_institucion("borrar:todo")


def test_scopes_declarados_son_los_esperados():
    assert set(inst.SCOPES_VALIDOS) == {"bundle:write", "task:write", "patient:read"}
    