"""R30 · R31 · R32: identidad del socio y cliente HTTP hacia su sistema.

Un solo lugar para todo lo que sale hacia la institución socio:
  - quién es el socio (R30_SOCIO_ID): el client_id con el que él entra a NUESTRO
    sistema (Sarah lo crea con scripts/gestionar_cliente_institucional.py). Con ese
    mismo id se guarda el consentimiento del paciente (R32) y se registra cada envío,
    así solo esa institución puede responder a lo que le enviamos;
  - cómo nos autenticamos ante SU sistema, según lo que ellos nos entreguen:
      a) client credentials (R31):  R30_SOCIO_TOKEN_URL + R30_SOCIO_CLIENT_ID
                                    + R30_SOCIO_CLIENT_SECRET
      b) clave fija (API key):      R30_SOCIO_API_KEY (+ R30_SOCIO_API_KEY_HEADER)
    En ambos casos se manda un x-nonce nuevo en cada petición (anti-repetición).

Variables (back/pass.env; ver example.pass.env):
  R30_SOCIO_ID              client_id del socio en nuestra base (por defecto socio-demo)
  R30_SOCIO_NOMBRE          nombre visible para pacientes y médicos
  R30_SOCIO_URL             endpoint del socio que RECIBE nuestros Bundles
  R30_SOCIO_RESPUESTA_URL   endpoint del socio que RECIBE nuestro Task de respuesta
  R30_INSTITUCION_NOMBRE    cómo nos llamamos en los Task que enviamos
"""
from __future__ import annotations

import os
import secrets
import threading
import time
from urllib.parse import urlparse

import requests

# Hosts sin HTTPS admitidos solo para la autoprueba dentro de Docker o local.
HOSTS_LOCALES = {"localhost", "127.0.0.1", "api", "socio-receptor"}

_cache_token: dict = {}
_candado = threading.Lock()


class SocioNoConfigurado(Exception):
    """Falta configuración para hablar con el socio (se responde 503)."""


class SocioError(Exception):
    """El socio no respondió o rechazó la petición."""

    def __init__(self, mensaje: str, status: int | None = None):
        super().__init__(mensaje)
        self.status = status


def socio_id() -> str:
    return os.getenv("R30_SOCIO_ID", "socio-demo").strip() or "socio-demo"


def socio_nombre() -> str:
    return os.getenv("R30_SOCIO_NOMBRE", "").strip() or "Institución socio"


def institucion_propia() -> str:
    return os.getenv("R30_INSTITUCION_NOMBRE", "").strip() or "Salud Digital · Triaje"


def dias_consentimiento() -> int:
    try:
        return max(1, min(int(os.getenv("R30_CONSENTIMIENTO_DIAS", "365")), 3650))
    except ValueError:
        return 365


def validar_url(url: str, nombre: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if not url or p.scheme not in ("http", "https") or not p.hostname:
        raise SocioNoConfigurado(f"{nombre} no está configurado")
    if p.scheme != "https" and p.hostname not in HOSTS_LOCALES:
        raise SocioNoConfigurado(f"{nombre} debe usar HTTPS fuera de la red de prueba")
    return url


def url_envio() -> str:
    return validar_url(os.getenv("R30_SOCIO_URL", ""), "R30_SOCIO_URL")


def url_respuesta() -> str:
    return validar_url(os.getenv("R30_SOCIO_RESPUESTA_URL", ""), "R30_SOCIO_RESPUESTA_URL")


def _token_oauth(token_url: str, client_id: str, client_secret: str, post) -> str:
    clave = (token_url, client_id)
    with _candado:
        guardado = _cache_token.get(clave)
        if guardado and guardado["vence"] > time.time() + 30:
            return guardado["token"]
    try:
        r = post(token_url, timeout=15, data={
            "grant_type": "client_credentials", "client_id": client_id,
            "client_secret": client_secret})
    except requests.RequestException as e:
        raise SocioError("El servidor de tokens del socio no responde") from e
    if r.status_code != 200:
        raise SocioError(f"El socio rechazó nuestras credenciales (HTTP {r.status_code})", r.status_code)
    try:
        datos = r.json()
        token = datos["access_token"]
        vigencia = int(datos.get("expires_in") or 300)
    except (ValueError, KeyError, TypeError) as e:
        raise SocioError("Respuesta de token inválida del socio") from e
    with _candado:
        _cache_token[clave] = {"token": token, "vence": time.time() + vigencia}
    return token


def olvidar_token() -> None:
    with _candado:
        _cache_token.clear()


def cabeceras(post=None) -> dict:
    """Cabeceras de autenticación ante el socio, con un nonce nuevo."""
    post = post or requests.post
    base = {"Content-Type": "application/fhir+json", "Accept": "application/fhir+json",
            "x-nonce": secrets.token_urlsafe(24)}
    token_url = os.getenv("R30_SOCIO_TOKEN_URL", "").strip()
    client_id = os.getenv("R30_SOCIO_CLIENT_ID", "").strip()
    client_secret = os.getenv("R30_SOCIO_CLIENT_SECRET", "")
    if token_url and client_id and client_secret:
        validar_url(token_url, "R30_SOCIO_TOKEN_URL")
        return {**base, "Authorization": f"Bearer {_token_oauth(token_url, client_id, client_secret, post)}"}
    api_key = os.getenv("R30_SOCIO_API_KEY", "")
    if api_key:
        return {**base, os.getenv("R30_SOCIO_API_KEY_HEADER", "X-API-Key").strip() or "X-API-Key": api_key}
    raise SocioNoConfigurado("No hay credenciales para el socio (R30_SOCIO_CLIENT_ID/SECRET o R30_SOCIO_API_KEY)")


def enviar_fhir(url: str, recurso: dict, post=None, timeout: int = 25):
    """POST de un recurso FHIR al socio. Reintenta una vez si el token venció (401).

    Devuelve la respuesta HTTP; lanza SocioError si no hubo respuesta.
    """
    post = post or requests.post
    for intento in (1, 2):
        try:
            r = post(url, json=recurso, headers=cabeceras(post), timeout=timeout)
        except requests.RequestException as e:
            raise SocioError("El sistema socio no responde") from e
        if r.status_code == 401 and intento == 1:
            olvidar_token()
            continue
        return r
    return r
