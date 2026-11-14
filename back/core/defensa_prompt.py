"""R25: control por cuenta de intentos de prompt injection en consultas clínicas.

La clasificación es conservadora: solo patrones explícitos de evasión o extracción.
La autorización real continúa exclusivamente en los routers del backend.
No interpreta encabezados X-Forwarded-For no confiables como dirección del atacante.
"""
from __future__ import annotations

import hashlib
import json
import logging
from contextlib import closing

import psycopg2
from starlette.responses import JSONResponse

from core.config import PG_CONNECTION_STRING
from core.security import decodificar_token

log = logging.getLogger('r25_defensa')

from rag.seguridad import detectar_inyeccion

RUTAS = {'/agente/preguntar', '/rag/preguntar', '/agente/herramientas/ejecutar',
         '/observaciones', '/notas-clinicas'}


def _ruta_protegida(metodo: str, ruta: str) -> bool:
    if ruta in RUTAS and metodo == 'POST':
        return True
    if metodo == 'PUT' and (ruta.startswith('/observaciones/') or ruta.startswith('/notas-clinicas/')):
        return ruta.count('/') == 2
    return False
UMBRAL = 3
VENTANA_MINUTOS = 15
BLOQUEO_MINUTOS = 15
MAX_CUERPO = 16_384


def _bloqueado(cur, documento: int) -> bool:
    cur.execute('''SELECT 1 FROM r25_bloqueos_prompt
                   WHERE numero_documento_usuario=%s AND bloqueado_hasta > now()''', (documento,))
    return cur.fetchone() is not None


def _registrar_intento(cur, documento: int, ip: str | None, ruta: str,
                      codigo: str, pregunta: str) -> bool:
    """Inserta un evento sin almacenar pregunta clínica cruda; bloquea al tercer intento."""
    cur.execute('SELECT pg_advisory_xact_lock(%s)', (documento,))
    cur.execute('''INSERT INTO r25_intentos_prompt
                   (numero_documento_usuario, ip_observada, ruta, motivo, huella_texto)
                   VALUES (%s,%s,%s,%s,%s)''',
                (documento, ip, ruta, codigo,
                 hashlib.sha256(pregunta.encode('utf-8')).hexdigest()))
    cur.execute('''SELECT COUNT(*) FROM r25_intentos_prompt
                   WHERE numero_documento_usuario=%s
                     AND fecha_hora >= now() - interval '15 minutes' ''', (documento,))
    total = cur.fetchone()[0]
    if total < UMBRAL:
        return False
    cur.execute('''INSERT INTO r25_bloqueos_prompt
                   (numero_documento_usuario, bloqueado_hasta, ultima_ip, motivo)
                   VALUES (%s, now() + interval '15 minutes', %s, %s)
                   ON CONFLICT (numero_documento_usuario) DO UPDATE
                   SET bloqueado_hasta = GREATEST(r25_bloqueos_prompt.bloqueado_hasta, EXCLUDED.bloqueado_hasta),
                       ultima_ip = EXCLUDED.ultima_ip, motivo = EXCLUDED.motivo''',
                (documento, ip, 'INTENTOS_REPETIDOS'))
    return True


def _token_id(scope) -> int | None:
    auth = next((v for k, v in scope.get('headers', ()) if k.lower() == b'authorization'), b'')
    if not auth.lower().startswith(b'bearer '):
        return None
    try:
        payload = decodificar_token(auth.split(None, 1)[1].decode('ascii'))
        return int(payload['sub'])
    except Exception:
        # Token inválido: la autenticación habitual devolverá 401.
        return None


class DefensaPromptMiddleware:
    """ASGI middleware para LLM y textos clínicos; conserva el body para FastAPI.

    No altera endpoints fuera de R23, R24 y escritura de observaciones/notas. La IP solo sirve como evidencia contextual porque
    detrás de Cloudflare/Nginx request.client puede ser un proxy o red interna.
    El bloqueo es por usuario JWT, evitando denegación a todo un hospital/NAT.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not _ruta_protegida(scope.get('method', ''), scope.get('path', '')):
            return await self.app(scope, receive, send)
        documento = _token_id(scope)
        if documento is None:
            return await self.app(scope, receive, send)
        try:
            with closing(psycopg2.connect(PG_CONNECTION_STRING)) as db:
                with db.cursor() as cur:
                    bloqueado = _bloqueado(cur, documento)
        except psycopg2.Error:
            log.exception('R25 no pudo consultar el registro de bloqueos')
            return await JSONResponse({'detail': 'Protección de seguridad temporalmente no disponible'}, status_code=503)(scope, receive, send)
        if bloqueado:
            return await JSONResponse({'detail': 'Asistente temporalmente bloqueado por seguridad. Intente más tarde.'},
                                      status_code=429, headers={'Retry-After': str(BLOQUEO_MINUTOS * 60)})(scope, receive, send)

        partes = []
        tam = 0
        while True:
            mensaje = await receive()
            if mensaje['type'] == 'http.disconnect':
                return
            if mensaje['type'] != 'http.request':
                return
            parte = mensaje.get('body', b'')
            tam += len(parte)
            if tam > MAX_CUERPO:
                return await JSONResponse({'detail': 'Solicitud demasiado grande'}, status_code=413)(scope, receive, send)
            partes.append(parte)
            if not mensaje.get('more_body', False):
                break
        cuerpo = b''.join(partes)
        try:
            dato = json.loads(cuerpo)
        except (ValueError, UnicodeDecodeError):
            dato = None
        if isinstance(dato, dict):
            campos = ('pregunta', 'motivo', 'especialidad', 'valor_texto', 'nombre', 'contenido')
            senal = next(((codigo, dato[campo]) for campo in campos
                          if isinstance(dato.get(campo), str)
                          if (codigo := detectar_inyeccion(dato[campo]))), None)
        else:
            senal = None
        if senal:
            codigo, texto = senal
            ip = (scope.get('client') or (None,))[0]
            try:
                with closing(psycopg2.connect(PG_CONNECTION_STRING)) as db:
                    with db:
                        with db.cursor() as cur:
                            bloqueo = _registrar_intento(cur, documento, ip, scope['path'], codigo, texto)
            except psycopg2.Error:
                log.exception('R25 no pudo registrar la detección')
                return await JSONResponse({'detail': 'Protección de seguridad temporalmente no disponible'}, status_code=503)(scope, receive, send)
            log.warning('R25: intento %s en %s por cuenta autenticada; bloqueo=%s', codigo, scope['path'], bloqueo)
            if bloqueo:
                return await JSONResponse({'detail': 'Asistente temporalmente bloqueado por seguridad. Intente más tarde.'},
                                          status_code=429, headers={'Retry-After': str(BLOQUEO_MINUTOS * 60)})(scope, receive, send)
            return await JSONResponse({'detail': 'Solicitud rechazada por las políticas de seguridad del asistente.'},
                                      status_code=403)(scope, receive, send)

        enviado = False

        async def reproducir_cuerpo():
            nonlocal enviado
            if not enviado:
                enviado = True
                return {'type': 'http.request', 'body': cuerpo, 'more_body': False}
            return await receive()

        return await self.app(scope, reproducir_cuerpo, send)
