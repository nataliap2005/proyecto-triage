# R27: frontera de traducción del documento de identidad (ver core/identidad.py).
#
# ENTRADA: el documento real que llega en la ruta, en la consulta o en el cuerpo
#          JSON se cambia por el número interno antes de llegar a las rutas.
# SALIDA:  en las respuestas JSON y en los eventos en vivo (SSE), cada número
#          interno se cambia por el documento real antes de salir.
#
# Solo se traducen campos que son de una persona (lista CAMPOS_PERSONA) y las
# rutas /pacientes/{documento}, /usuarios/{documento}, /practitioners/{documento}
# y /ia/analizar/{documento}. Los demás números (ids de remisión, alertas,
# valores clínicos) no se tocan.
#
# Mientras la base no esté migrada (identidad.activa() es False) no hace nada.

import json
import re
from urllib.parse import parse_qsl, urlencode

from core import identidad

# Campos que contienen el documento de una persona en peticiones de la API.
CAMPOS_PERSONA = {
    "documento", "numero_documento_paciente", "numero_documento_usuario",
    "id_paciente", "paciente_id", "medico_responsable", "especialista_destino",
    "medico_reemplazo",
}
# Al crear una persona, su documento se guarda en la bóveda.
CAMPOS_ALTA = {"numero_documento_paciente", "numero_documento_usuario"}

PATRON_RUTA = re.compile(r"(/(?:pacientes|usuarios|practitioners|analizar)/)(\d{1,15})(?=/|$)")

# Entradas de otros sistemas (socio R30/R31, webhook FHIR): llevan FHIR, no
# campos nuestros, y no se reescriben.
RUTAS_EXCLUIDAS = ("/fhir/remisiones-r30/recibir", "/fhir/remisiones-r30/respuesta",
                   "/oauth/", "/institucion/", "/fhir/suscripcion", "/fhir-hook")

TIPOS_TRADUCIBLES = ("application/json", "text/event-stream", "text/plain")


def _a_interno(valor, alta: bool):
    if isinstance(valor, bool) or valor is None:
        return valor
    if isinstance(valor, int) or (isinstance(valor, str) and valor.isdigit() and len(valor) <= 15):
        numero = int(valor)
        if numero <= 0:
            return valor
        nuevo = identidad.registrar(numero) if alta else identidad.interno(numero)
        return nuevo if isinstance(valor, int) else str(nuevo)
    return valor


def _traducir_entrada(obj, alta_permitida: bool):
    if isinstance(obj, dict):
        nuevo = {}
        for clave, valor in obj.items():
            if clave in CAMPOS_PERSONA and not isinstance(valor, (dict, list)):
                nuevo[clave] = _a_interno(valor, alta_permitida and clave in CAMPOS_ALTA)
            else:
                nuevo[clave] = _traducir_entrada(valor, alta_permitida)
        return nuevo
    if isinstance(obj, list):
        return [_traducir_entrada(v, alta_permitida) for v in obj]
    return obj


def traducir_ruta(ruta: str) -> str:
    return PATRON_RUTA.sub(lambda m: m.group(1) + str(identidad.interno(int(m.group(2)))), ruta)


def traducir_consulta(consulta: str) -> str:
    if not consulta:
        return consulta
    pares = parse_qsl(consulta, keep_blank_values=True)
    if not any(k in CAMPOS_PERSONA for k, _ in pares):
        return consulta
    return urlencode([(k, _a_interno(v, False) if k in CAMPOS_PERSONA else v) for k, v in pares])


class IdentidadMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not identidad.activa():
            return await self.app(scope, receive, send)

        ruta = scope.get("path", "")
        excluida = any(r in ruta for r in RUTAS_EXCLUIDAS)

        if not excluida:
            scope = dict(scope)
            nueva_ruta = traducir_ruta(ruta)
            if nueva_ruta != ruta:
                scope["path"] = nueva_ruta
                scope["raw_path"] = nueva_ruta.encode("utf-8")
            consulta = scope.get("query_string", b"").decode("latin-1")
            nueva_consulta = traducir_consulta(consulta)
            if nueva_consulta != consulta:
                scope["query_string"] = nueva_consulta.encode("latin-1")

            cabeceras = dict(scope.get("headers") or [])
            tipo = cabeceras.get(b"content-type", b"").decode("latin-1")
            if "application/json" in tipo and scope.get("method") in ("POST", "PUT", "PATCH"):
                receive = await self._cuerpo_traducido(scope, receive)

        await self.app(scope, receive, self._envio_traducido(send))

    async def _cuerpo_traducido(self, scope, receive):
        partes, mas = [], True
        while mas:
            mensaje = await receive()
            if mensaje["type"] != "http.request":
                break
            partes.append(mensaje.get("body", b""))
            mas = mensaje.get("more_body", False)
        cuerpo = b"".join(partes)
        try:
            datos = json.loads(cuerpo) if cuerpo else None
            alta = scope.get("method") == "POST"
            nuevo = json.dumps(_traducir_entrada(datos, alta)).encode("utf-8") if datos is not None else cuerpo
        except (ValueError, UnicodeDecodeError):
            nuevo = cuerpo  # no es JSON válido: la ruta responderá el error de siempre

        # Se corrige Content-Length porque el cuerpo cambió de tamaño.
        scope["headers"] = [(k, v) for k, v in scope.get("headers", []) if k != b"content-length"]
        scope["headers"].append((b"content-length", str(len(nuevo)).encode()))
        enviado = False

        async def receive_nuevo():
            nonlocal enviado
            if not enviado:
                enviado = True
                return {"type": "http.request", "body": nuevo, "more_body": False}
            return await receive()
        return receive_nuevo

    def _envio_traducido(self, send):
        estado = {"traducir": False, "inicio": None, "partes": []}

        async def send_nuevo(mensaje):
            if mensaje["type"] == "http.response.start":
                cabeceras = dict(mensaje.get("headers") or [])
                tipo = cabeceras.get(b"content-type", b"").decode("latin-1")
                estado["traducir"] = any(t in tipo for t in TIPOS_TRADUCIBLES)
                estado["stream"] = "text/event-stream" in tipo
                if not estado["traducir"] or estado["stream"]:
                    return await send(mensaje)
                estado["inicio"] = mensaje  # se envía cuando se conozca el nuevo tamaño
                return
            if mensaje["type"] != "http.response.body" or not estado["traducir"]:
                return await send(mensaje)

            if estado["stream"]:
                # SSE: cada evento sale traducido apenas se produce.
                cuerpo = mensaje.get("body", b"")
                if cuerpo:
                    mensaje = dict(mensaje)
                    mensaje["body"] = identidad.traducir_texto(cuerpo.decode("utf-8")).encode("utf-8")
                return await send(mensaje)

            estado["partes"].append(mensaje.get("body", b""))
            if mensaje.get("more_body", False):
                return
            cuerpo = identidad.traducir_texto(b"".join(estado["partes"]).decode("utf-8")).encode("utf-8")
            inicio = dict(estado["inicio"])
            inicio["headers"] = [(k, v) for k, v in inicio.get("headers", []) if k != b"content-length"]
            inicio["headers"].append((b"content-length", str(len(cuerpo)).encode()))
            await send(inicio)
            await send({"type": "http.response.body", "body": cuerpo, "more_body": False})

        return send_nuevo
