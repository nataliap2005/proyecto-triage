# R21: interoperabilidad reactiva con FHIR.
# HAPI FHIR avisa a la API (Subscription rest-hook) cada vez que llega una Observation.
# La API identifica al paciente, notifica al médico responsable y lo audita con origen FHIR.

import hmac
import logging
import re
import threading
import time

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from psycopg2.extras import Json, RealDictCursor

from auth.service import requerir_roles
from core.config import FHIR_HOOK_TOKEN, FHIR_HOOK_URL, PG_CONNECTION_STRING
from core.eventos import publicar, usuarios_por_rol
from routers.fhir import FHIR_IDENTIFIER_SYSTEM, FHIR_LOCAL_SYSTEM, fhir_get, fhir_put

log = logging.getLogger("uvicorn.error")   # así los mensajes salen en docker compose logs
router = APIRouter()

SUSCRIPCION_ID = "triaje-observaciones"
CABECERA_TOKEN = "X-Triaje-Token"
LOINC = "http://loinc.org"


# ============================================================
# Registro de la Subscription en HAPI
# ============================================================

def construir_suscripcion() -> dict:
    return {
        "status": "requested",
        "reason": "Avisar al sistema de triaje cuando llega una Observation (R21)",
        "criteria": "Observation?",
        "channel": {
            "type": "rest-hook",
            "endpoint": FHIR_HOOK_URL,
            "payload": "application/fhir+json",   # HAPI envía la Observation completa
            "header": [f"{CABECERA_TOKEN}: {FHIR_HOOK_TOKEN}"],
        },
    }


def asegurar_suscripcion() -> dict:
    """PUT con id fijo: crearla dos veces no la duplica (idempotente)."""
    return fhir_put("Subscription", SUSCRIPCION_ID, construir_suscripcion())


def _registrar_con_reintentos(intentos: int = 30, espera: int = 10) -> None:
    # HAPI tarda uno o dos minutos en arrancar: se reintenta hasta que responda.
    for n in range(1, intentos + 1):
        try:
            asegurar_suscripcion()
            log.info("R21: Subscription '%s' registrada en HAPI FHIR", SUSCRIPCION_ID)
            return
        except Exception as e:
            log.info("R21: HAPI aún no disponible (intento %s/%s): %s", n, intentos, e)
            time.sleep(espera)
    log.error("R21: no se pudo registrar la Subscription en HAPI FHIR")


def iniciar_registro_suscripcion() -> None:
    """Se llama al arrancar la API. Corre en un hilo para no retrasar el arranque."""
    if not FHIR_HOOK_TOKEN:
        log.error("R21: falta FHIR_HOOK_TOKEN; no se registra la Subscription")
        return
    threading.Thread(target=_registrar_con_reintentos, daemon=True).start()


@router.put("/fhir/suscripcion", tags=["FHIR"])
def registrar_suscripcion(u=Depends(requerir_roles("Admin"))):
    """Permite al Admin volver a registrar la Subscription manualmente."""
    return asegurar_suscripcion()


# ============================================================
# Lectura de la Observation
# ============================================================

def _es_propia(obs: dict) -> bool:
    # Las Observations que sube nuestra propia API llevan este identifier.
    # No son datos nuevos de un sistema externo: se ignoran para no avisar dos veces.
    return any(i.get("system") == FHIR_LOCAL_SYSTEM for i in obs.get("identifier", []))


def _documento_paciente(referencia: str) -> int | None:
    # Caso normal: nuestros Patient se llaman paciente-{documento}.
    m = re.search(r"Patient/paciente-(\d+)", referencia)
    if m:
        return int(m.group(1))
    # Otro id: se consulta el Patient en HAPI y se lee el documento de su identifier.
    m = re.search(r"Patient/([A-Za-z0-9\-.]{1,64})", referencia)
    if not m:
        return None
    try:
        paciente = fhir_get("Patient", m.group(1))
    except HTTPException:
        return None
    for ident in paciente.get("identifier", []):
        valor = str(ident.get("value", ""))
        if ident.get("system") == FHIR_IDENTIFIER_SYSTEM and valor.isdigit():
            return int(valor)
    return None


def _resumen(obs: dict) -> dict:
    code = obs.get("code") or {}
    codings = code.get("coding") or [{}]
    coding = next((c for c in codings if c.get("system") == LOINC), codings[0])
    nombre = code.get("text") or coding.get("display") or coding.get("code") or "Observación"

    if "valueQuantity" in obs:
        q = obs["valueQuantity"]
        valor = f"{q.get('value')} {q.get('unit') or q.get('code') or ''}".strip()
    elif "valueString" in obs:
        valor = obs["valueString"]
    elif "valueCodeableConcept" in obs:
        valor = obs["valueCodeableConcept"].get("text")
    else:
        valor = None

    return {
        "loinc": coding.get("code") if coding.get("system") == LOINC else None,
        "nombre": nombre,
        "valor": valor,
    }


# ============================================================
# Reacción: auditar y notificar
# ============================================================

def procesar_observation(obs: dict) -> None:
    if _es_propia(obs):
        return

    fhir_id_obs = str(obs.get("id"))
    referencia = (obs.get("subject") or {}).get("reference", "")
    documento = _documento_paciente(referencia)
    resumen = _resumen(obs)

    conn = psycopg2.connect(PG_CONNECTION_STRING)
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        paciente, medico = None, None

        if documento:
            cur.execute("""
                SELECT numero_documento_paciente, nombres, apellidos
                FROM pacientes
                WHERE numero_documento_paciente = %s AND is_deleted = FALSE;
            """, (documento,))
            paciente = cur.fetchone()

        if paciente:
            # Médico responsable: primero el del encuentro activo; si no hay,
            # el del encuentro más reciente que tenga uno asignado.
            cur.execute("""
                SELECT medico_responsable
                FROM encuentros
                WHERE id_paciente = %s
                  AND is_deleted = FALSE
                  AND medico_responsable IS NOT NULL
                ORDER BY (estado <> 'finalizado') DESC, fecha_hora_ingreso DESC
                LIMIT 1;
            """, (documento,))
            fila = cur.fetchone()
            medico = fila["medico_responsable"] if fila else None

        # Sin médico identificable, el aviso va a los Admin: nada queda sin dueño.
        destinatarios = [medico] if medico else usuarios_por_rol(conn, "Admin")

        cur.execute("""
            INSERT INTO auditoria_cambios(
                tabla_afectada, registro_id, accion, datos_nuevos, realizado_por, origen
            )
            VALUES ('fhir:Observation', %s, 'RECIBIR_FHIR', %s, NULL, 'FHIR');
        """, (fhir_id_obs, Json({
            **resumen,
            "referencia_paciente": referencia,
            "paciente_id": documento,
            "notificado_a": destinatarios,
        })))
        conn.commit()
        cur.close()

        if paciente and medico:
            mensaje = (f"Nuevo resultado desde FHIR para {paciente['nombres']} "
                       f"{paciente['apellidos']}: {resumen['nombre']} {resumen['valor'] or ''}").strip()
        else:
            mensaje = (f"Llegó una Observation de FHIR ({resumen['nombre']}) sin médico "
                       f"responsable identificable. Referencia: {referencia or 'sin paciente'}")

        publicar(
            conn,
            destinatarios,
            tipo="observacion_fhir",
            mensaje=mensaje,
            paciente_id=documento if paciente else None,
            datos={"origen": "FHIR", "fhir_id": fhir_id_obs, **resumen},
        )
    finally:
        conn.close()


# ============================================================
# Endpoint que llama HAPI
# ============================================================

@router.api_route("/fhir-hook", methods=["POST", "PUT"], include_in_schema=False)
@router.api_route("/fhir-hook/{ruta:path}", methods=["POST", "PUT"], include_in_schema=False)
async def recibir_de_fhir(request: Request, ruta: str = ""):
    # No usa JWT: quien llama es HAPI, no un usuario. Se identifica con el secreto compartido.
    recibido = request.headers.get(CABECERA_TOKEN, "")
    if not FHIR_HOOK_TOKEN or not hmac.compare_digest(recibido, FHIR_HOOK_TOKEN):
        raise HTTPException(status_code=401, detail="Token de integración inválido")

    try:
        recurso = await request.json()
    except Exception:
        recurso = None
    if not recurso:
        # Sin cuerpo: HAPI solo está comprobando que el canal responde.
        return JSONResponse({"recibido": True})

    if recurso.get("resourceType") == "Observation":
        observaciones = [recurso]
    elif recurso.get("resourceType") == "Bundle":
        observaciones = [e["resource"] for e in recurso.get("entry", [])
                         if (e.get("resource") or {}).get("resourceType") == "Observation"]
    else:
        observaciones = []

    for obs in observaciones:
        await run_in_threadpool(procesar_observation, obs)

    # HAPI espera la respuesta de un servidor FHIR: se devuelve el mismo recurso.
    return JSONResponse(content=recurso, media_type="application/fhir+json")