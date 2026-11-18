"""R30: remisiones FHIR R4 transaccionales, consentimiento y receptor autenticado.

El LLM no autoriza ni envía remisiones. Solo se utilizan datos autorizados en Neon.
El intercambio real requiere acuerdo técnico y configuración explícita del socio.
"""
from __future__ import annotations

import hmac
import hashlib
import os
import uuid
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_paciente_propio, registrar_auditoria
from rag.privacidad import proteger_texto

router = APIRouter(prefix="/fhir/remisiones-r30", tags=["R30 · Remisiones FHIR R4"])
LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
LOCAL = "urn:salud-digital:r30"
HEADER = "X-R30-Token"
MAX_ENTRIES = 30


def outcome(mensaje: str, codigo: str = "invalid") -> dict:
    return {"resourceType": "OperationOutcome", "issue": [{"severity": "error", "code": codigo, "diagnostics": mensaje}]}


def rechazo(status: int, mensaje: str, codigo: str = "invalid"):
    return JSONResponse(status_code=status, content=outcome(mensaje, codigo))


def _id_fhir(kind: str, value: int) -> str:
    # La ID FHIR no revela el documento del paciente. Estable para reintentos PUT.
    secreto = os.getenv("R30_IDENTIFICADOR_SECRETO", "")
    if len(secreto) < 32:
        raise HTTPException(status_code=503, detail="R30 no tiene identificador secreto configurado")
    digest = hmac.new(secreto.encode(), f"{kind}:{value}".encode(), hashlib.sha256).hexdigest()[:32]
    return f"r30-{kind}-{digest}"


def _entrada(recurso: dict) -> dict:
    t, i = recurso["resourceType"], recurso["id"]
    return {"fullUrl": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, t + '/' + i)}", "resource": recurso,
            "request": {"method": "PUT", "url": f"{t}/{i}"}}


def _ref(recurso: dict) -> dict:
    return {"reference": f"{recurso['resourceType']}/{recurso['id']}"}


def validar_bundle(bundle: dict) -> None:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle" or bundle.get("type") != "transaction":
        raise ValueError("Se requiere Bundle FHIR R4 de tipo transaction")
    entradas = bundle.get("entry")
    if not isinstance(entradas, list) or not 2 <= len(entradas) <= MAX_ENTRIES:
        raise ValueError("Número inválido de recursos del Bundle")
    tipos = []
    ids = set()
    for entrada in entradas:
        if not isinstance(entrada, dict):
            raise ValueError("Entrada FHIR inválida")
        recurso = entrada.get("resource", {})
        peticion = entrada.get("request", {})
        if not isinstance(recurso, dict) or not isinstance(peticion, dict):
            raise ValueError("Estructura de entrada inválida")
        tipo, rid = recurso.get("resourceType"), recurso.get("id")
        if tipo not in {"Patient", "ServiceRequest", "Observation", "DiagnosticReport", "Consent", "Task"}:
            raise ValueError("Tipo de recurso no permitido para remisiones")
        if not isinstance(rid, str) or not re.fullmatch(r"r30-(pac|ref|obs|rep|con|task)-[0-9a-f]{32}", rid):
            raise ValueError("Identificador FHIR inválido")
        if peticion.get("method") != "PUT" or peticion.get("url") != f"{tipo}/{rid}":
            raise ValueError("Todas las entradas deben ser PUT con URL e ID coincidentes")
        prefijos = {"Patient": "r30-pac-", "ServiceRequest": "r30-ref-", "Observation": "r30-obs-", "DiagnosticReport": "r30-rep-", "Consent": "r30-con-", "Task": "r30-task-"}
        if not rid.startswith(prefijos[tipo]):
            raise ValueError("Identificador no corresponde al tipo de recurso")
        if (tipo, rid) in ids:
            raise ValueError("Recurso duplicado")
        ids.add((tipo, rid))
        tipos.append(tipo)
        if tipo == "Observation":
            codigo = recurso.get("code", {}).get("coding", [{}])[0]
            if codigo.get("system") != LOINC or not codigo.get("code"):
                raise ValueError("Observation requiere código LOINC")
            if recurso.get("status") not in {"final", "amended", "corrected"}:
                raise ValueError("Estado de Observation inválido")
            if not recurso.get("subject", {}).get("reference"):
                raise ValueError("Observation sin paciente")
        elif tipo == "ServiceRequest":
            codigo = recurso.get("code", {}).get("coding", [{}])[0]
            if codigo.get("system") != SNOMED or codigo.get("code") != "306206005":
                raise ValueError("ServiceRequest requiere SNOMED CT de remisión")
            if recurso.get("status") != "active" or recurso.get("intent") != "order":
                raise ValueError("ServiceRequest debe ser una orden activa")
            if not recurso.get("subject", {}).get("reference"):
                raise ValueError("ServiceRequest sin paciente")
        elif tipo == "DiagnosticReport":
            if recurso.get("status") != "final":
                raise ValueError("Solo se transfieren reportes finales aprobados")
            if not recurso.get("subject", {}).get("reference") or not recurso.get("code"):
                raise ValueError("DiagnosticReport incompleto")
        elif tipo == "Consent":
            if recurso.get("status") != "active":
                raise ValueError("Solo se permite Consent activo")
            if recurso.get("scope", {}).get("coding", [{}])[0].get("code") != "patient-privacy":
                raise ValueError("Consent debe cubrir privacidad del paciente")
            if not recurso.get("category") or recurso.get("provision", {}).get("type") != "permit":
                raise ValueError("Consent sin categoría o sin permiso explícito")
            if not recurso.get("policyRule") and not recurso.get("policy"):
                raise ValueError("Consent requiere política aplicable")
        elif tipo == "Task":
            if recurso.get("status") != "requested" or recurso.get("intent") != "order":
                raise ValueError("Task inicial debe ser requested/order")
            if not recurso.get("focus", {}).get("reference") or not recurso.get("for", {}).get("reference"):
                raise ValueError("Task sin remisión o paciente")
    if any(tipos.count(tipo) != 1 for tipo in ("Patient", "ServiceRequest", "Consent", "Task")):
        raise ValueError("Se requiere exactamente un Patient, ServiceRequest, Consent y Task")
    pac = next(e["resource"] for e in entradas if e["resource"]["resourceType"] == "Patient")
    pid = f"Patient/{pac['id']}"
    for e in entradas:
        r = e["resource"]
        tipo = r["resourceType"]
        if tipo in {"ServiceRequest", "Observation", "DiagnosticReport"} and r.get("subject", {}).get("reference") != pid:
            raise ValueError("Los recursos deben pertenecer al mismo paciente")
        if tipo == "Consent" and r.get("patient", {}).get("reference") != pid:
            raise ValueError("Consent no pertenece al paciente")
        if tipo == "Task" and r.get("for", {}).get("reference") != pid:
            raise ValueError("Task no pertenece al paciente")
    sr = next(e["resource"] for e in entradas if e["resource"]["resourceType"] == "ServiceRequest")
    task = next(e["resource"] for e in entradas if e["resource"]["resourceType"] == "Task")
    if task["focus"]["reference"] != f"ServiceRequest/{sr['id']}":
        raise ValueError("Task no apunta a ServiceRequest del Bundle")
    consent = next(e["resource"] for e in entradas if e["resource"]["resourceType"] == "Consent")
    if consent.get("provision", {}).get("period", {}).get("end"):
        try:
            fin = datetime.fromisoformat(consent["provision"]["period"]["end"].replace("Z", "+00:00"))
            if fin <= datetime.now(timezone.utc):
                raise ValueError("Consent FHIR expirado")
        except (TypeError, ValueError) as e:
            raise ValueError("Consent con vigencia inválida o expirada") from e
    # No se incluyen datos de identidad directa en el intercambio sintético.
    if any(k in pac for k in ("name", "telecom", "address", "birthDate")):
        raise ValueError("Datos demográficos no autorizados para este canal")


def construir_bundle(remision: dict, observaciones: list[dict], reportes: list[dict], consentimiento: dict) -> dict:
    # Nunca crear Consent a partir de un valor predeterminado o una suposición.
    if not consentimiento or consentimiento.get("vigente") is not True:
        raise ValueError("Se requiere consentimiento explícito vigente")
    fin = consentimiento.get("expira_at")
    if fin and fin <= datetime.now(timezone.utc):
        raise ValueError("Consentimiento expirado")
    inicio = consentimiento.get("actualizado_at")
    if not inicio:
        raise ValueError("Consentimiento sin fecha verificable")
    paciente = {"resourceType": "Patient", "id": _id_fhir("pac", remision["id_paciente"]), "active": True}
    sr = {"resourceType": "ServiceRequest", "id": _id_fhir("ref", remision["id_remision"]),
          "status": "active", "intent": "order", "subject": _ref(paciente),
          "authoredOn": remision["fecha_remision"].isoformat(),
          "code": {"coding": [{"system": SNOMED, "code": "306206005", "display": "Referral to service"}]},
          "reasonCode": [{"text": proteger_texto(remision["motivo"][:1000])}],
          "note": [{"text": "Especialidad: " + proteger_texto(remision["especialidad"][:120])}]}
    consentimiento_fhir = {
        "resourceType": "Consent", "id": _id_fhir("con", remision["id_paciente"]),
        "status": "active",
        "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                              "code": "patient-privacy"}]},
        "category": [{"coding": [{"system": LOINC, "code": "59284-0", "display": "Consent Document"}]}],
        "patient": _ref(paciente), "dateTime": inicio.isoformat(),
        "performer": [_ref(paciente)],
        "policyRule": {"text": "Consentimiento explícito para intercambio interinstitucional de remisión; socio-piloto"},
        "provision": {"type": "permit", "period": {
            "start": inicio.isoformat(), **({"end": fin.isoformat()} if fin else {})},
            "purpose": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActReason", "code": "TREAT"}]}
    }
    tarea = {
        "resourceType": "Task", "id": _id_fhir("task", remision["id_remision"]),
        "status": "requested", "intent": "order", "for": _ref(paciente),
        "focus": _ref(sr), "basedOn": [_ref(sr)],
        "authoredOn": remision["fecha_remision"].isoformat(),
        "description": "Seguimiento interinstitucional de remisión; pendiente de aceptación por el socio"
    }
    recursos = [paciente, consentimiento_fhir, sr, tarea]
    for ob in observaciones:
        if not ob.get("codigo_loinc") or ob.get("valor_numerico") is None:
            continue
        recursos.append({"resourceType": "Observation", "id": _id_fhir("obs", ob["id_observacion"]),
            "status": "final", "subject": _ref(paciente),
            "code": {"coding": [{"system": LOINC, "code": ob["codigo_loinc"], "display": proteger_texto(ob["nombre"])}]},
            "valueQuantity": {"value": float(ob["valor_numerico"]), "unit": ob["unidad"] or ""}})
    for rep in reportes:
        # Únicamente reportes aprobados; verificación repetida por defensa en profundidad.
        if rep["estado"] != "aprobado":
            continue
        recursos.append({"resourceType": "DiagnosticReport", "id": _id_fhir("rep", rep["id_reporte"]),
            "status": "final", "subject": _ref(paciente),
            "code": {"text": "Evaluación de apoyo mediante IA, revisada y aprobada por profesional"},
            "conclusion": "Categoría revisada: " + rep["categoria"],
            "issued": rep["revisado_at"].isoformat()})
    bundle = {"resourceType": "Bundle", "type": "transaction", "entry": [_entrada(x) for x in recursos]}
    validar_bundle(bundle)
    return bundle


def _cargar(cur, id_remision: int, usuario: dict):
    cur.execute("""SELECT r.*, e.medico_responsable, esp.nombre AS especialidad,
                   p.origen AS origen_paciente
                   FROM remisiones r
                   JOIN encuentros e ON e.id_encuentro=r.id_encuentro AND e.id_paciente=r.id_paciente
                   JOIN especialidades esp ON esp.id_especialidad=r.id_especialidad
                   JOIN pacientes p ON p.numero_documento_paciente=r.id_paciente
                   WHERE r.id_remision=%s AND r.is_deleted=FALSE AND e.is_deleted=FALSE AND p.is_deleted=FALSE""", (id_remision,))
    r = cur.fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Remisión no encontrada")
    if r["medico_remitente"] != usuario["numero_documento_usuario"]:
        raise HTTPException(status_code=403, detail="Solo el médico remitente puede exportar esta remisión")
    if r["estado"] not in ("pendiente", "aceptada"):
        raise HTTPException(status_code=409, detail="La remisión no está activa")
    if r["origen_paciente"] != "sintetico":
        raise HTTPException(status_code=403, detail="R30 piloto solo admite pacientes sintéticos")
    cur.execute("""SELECT vigente, expira_at, actualizado_at FROM r30_consentimientos
                   WHERE id_paciente=%s AND socio=%s""", (r["id_paciente"], "socio-piloto"))
    c = cur.fetchone()
    if not c or not c["vigente"] or (c["expira_at"] and c["expira_at"] <= datetime.now(timezone.utc)):
        raise HTTPException(status_code=403, detail="No existe consentimiento vigente para interoperabilidad")
    cur.execute("""SELECT id_observacion,codigo_loinc,nombre,valor_numerico,unidad
                   FROM observaciones WHERE id_encuentro=%s AND is_deleted=FALSE
                   AND tipo_observacion='signo_vital' AND codigo_loinc IS NOT NULL
                   AND valor_numerico IS NOT NULL ORDER BY fecha_hora_observacion DESC LIMIT 12""", (r["id_encuentro"],))
    obs = cur.fetchall()
    cur.execute("""SELECT id_reporte, estado, categoria, revisado_at FROM reportes_ia
                   WHERE id_encuentro=%s AND id_paciente=%s AND estado='aprobado'
                   AND revisado_at IS NOT NULL ORDER BY revisado_at DESC LIMIT 3""", (r["id_encuentro"], r["id_paciente"]))
    reps = cur.fetchall()
    return r, obs, reps, c


class Consentimiento(BaseModel):
    id_paciente: int
    autoriza: bool


@router.get("/consentimiento/estado")
def consultar_estado_consentimiento(db=Depends(get_db), u=Depends(requerir_roles("Paciente"))):
    """Estado persistido del consentimiento propio; nunca acepta IDs de terceros."""
    id_paciente = int(u["numero_documento_usuario"])
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        exigir_paciente_propio(cur, id_paciente, u)
        cur.execute("""SELECT vigente, actualizado_at
                       FROM r30_consentimientos
                       WHERE id_paciente=%s AND socio='socio-piloto'""", (id_paciente,))
        fila = cur.fetchone()
        return {
            "registrado": fila is not None,
            "consentimiento_vigente": bool(fila["vigente"]) if fila else False,
            "socio": "socio-piloto",
            "actualizado_at": fila["actualizado_at"].isoformat() if fila and fila["actualizado_at"] else None,
        }
    finally:
        cur.close()


@router.post("/consentimiento")
def consentimiento(body: Consentimiento, db=Depends(get_db), u=Depends(requerir_roles("Paciente"))):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        exigir_paciente_propio(cur, body.id_paciente, u)
        cur.execute("""INSERT INTO r30_consentimientos(id_paciente,socio,vigente,registrado_por,actualizado_at)
                       VALUES (%s,'socio-piloto',%s,%s,now())
                       ON CONFLICT(id_paciente,socio) DO UPDATE SET vigente=EXCLUDED.vigente,
                       registrado_por=EXCLUDED.registrado_por, actualizado_at=now()""",
                    (body.id_paciente,body.autoriza,u["numero_documento_usuario"]))
        registrar_auditoria(cur, "r30_consentimientos", str(body.id_paciente), "EDITAR",
                           u["numero_documento_usuario"], nuevos={
                               "socio": "socio-piloto", "vigente": body.autoriza})
        db.commit()
        return {"consentimiento_vigente": body.autoriza, "socio": "socio-piloto"}
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


@router.get("/{id_remision}/bundle")
def vista_previa(id_remision: int, db=Depends(get_db), u=Depends(requerir_roles("Medico"))):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        r, obs, rep, c = _cargar(cur,id_remision,u)
        return construir_bundle(r,obs,rep,c)
    finally:
        cur.close()


def _config_receptor():
    url = os.getenv("R30_SOCIO_URL", "").strip().rstrip("/")
    token = os.getenv("R30_SOCIO_TOKEN", "")
    parsed = urlparse(url)
    if not url or not token or parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise HTTPException(status_code=503, detail="Receptor R30 no configurado")
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "socio-receptor", "api"}:
        raise HTTPException(status_code=503, detail="El socio requiere HTTPS fuera de la red de prueba")
    return url, token


@router.get("/{id_remision}/estado-envio")
def estado_envio(id_remision: int, db=Depends(get_db), u=Depends(requerir_roles("Medico"))):
    """Consulta el estado de transmisión del médico remitente, sin exponer tokens."""
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""SELECT r.id_remision, r.medico_remitente, r.estado,
                              p.origen AS origen_paciente
                       FROM remisiones r JOIN pacientes p
                       ON p.numero_documento_paciente=r.id_paciente
                       WHERE r.id_remision=%s AND r.is_deleted=FALSE""", (id_remision,))
        fila = cur.fetchone()
        if not fila:
            raise HTTPException(status_code=404, detail="Remisión no encontrada")
        if fila["medico_remitente"] != u["numero_documento_usuario"]:
            raise HTTPException(status_code=403, detail="Solo el médico remitente puede consultar el envío")
        if fila["origen_paciente"] != "sintetico":
            raise HTTPException(status_code=403, detail="R30 piloto solo admite pacientes sintéticos")
        cur.execute("""SELECT estado, recursos, fecha_hora
                       FROM r30_envios WHERE id_remision=%s AND socio='socio-piloto'
                       AND estado='confirmado' ORDER BY fecha_hora DESC LIMIT 1""", (id_remision,))
        enviado = cur.fetchone()
        if enviado:
            return {"id_remision": id_remision, "confirmado": True,
                    "puede_enviar": False, "estado": "confirmado",
                    "recursos": enviado["recursos"],
                    "fecha_hora": enviado["fecha_hora"].isoformat() if enviado["fecha_hora"] else None}
        # Verificación real antes de ofrecer el botón (se vuelve a validar en POST).
        _cargar(cur, id_remision, u)
        return {"id_remision": id_remision, "confirmado": False,
                "puede_enviar": True, "estado": "sin_enviar", "recursos": None, "fecha_hora": None}
    finally:
        cur.close()


@router.post("/{id_remision}/enviar")
def enviar(id_remision: int, db=Depends(get_db), u=Depends(requerir_roles("Medico"))):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        # Verificar identidad ANTES de consultar si otra persona ya la envió.
        cur.execute("""SELECT r.medico_remitente, p.origen AS origen_paciente
                       FROM remisiones r JOIN pacientes p
                       ON p.numero_documento_paciente=r.id_paciente
                       WHERE r.id_remision=%s AND r.is_deleted=FALSE""", (id_remision,))
        titular = cur.fetchone()
        if titular is None:
            raise HTTPException(status_code=404, detail="Remisión no encontrada")
        if titular["medico_remitente"] != u["numero_documento_usuario"]:
            raise HTTPException(status_code=403, detail="Solo el médico remitente puede enviar la remisión")
        if titular["origen_paciente"] != "sintetico":
            raise HTTPException(status_code=403, detail="R30 piloto solo admite pacientes sintéticos")
        # Bloqueo transaccional: dos solicitudes concurrentes de la misma remisión
        # no pueden crear dos envíos confirmados.
        cur.execute("SELECT pg_advisory_xact_lock(%s, %s)", (30030, id_remision))
        cur.execute("""SELECT 1 FROM r30_envios WHERE id_remision=%s
                       AND socio='socio-piloto' AND estado='confirmado' LIMIT 1""", (id_remision,))
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="Esta remisión FHIR ya tiene un envío confirmado")
        r, obs, rep, c = _cargar(cur,id_remision,u)
        bundle = construir_bundle(r,obs,rep,c)
        url, token = _config_receptor()
        try:
            response = requests.post(url, json=bundle, headers={HEADER: token,
                "Content-Type": "application/fhir+json", "Accept": "application/fhir+json"}, timeout=20)
        except requests.RequestException:
            return rechazo(503,"Receptor FHIR no disponible","transient")
        if response.status_code not in (200,201):
            # No revelar mensajes remotos potencialmente sensibles en logs o respuestas.
            return rechazo(502, "El sistema socio rechazó la transacción", "processing")
        try:
            confirmado = response.json()
        except ValueError:
            return rechazo(502,"Respuesta FHIR no válida","processing")
        if confirmado.get("resourceType") != "Bundle" or confirmado.get("type") != "transaction-response":
            return rechazo(502,"El socio no confirmó una transacción FHIR", "processing")
        entradas = confirmado.get("entry", [])
        if len(entradas) != len(bundle["entry"]) or any(
            not str(e.get("response",{}).get("status","")).startswith(("200", "201")) for e in entradas
        ):
            return rechazo(502,"Respuesta transaccional parcial o inválida", "processing")
        cur.execute("""INSERT INTO r30_envios(id_remision,socio,remitido_por,estado,recursos,fecha_hora)
                       VALUES (%s,'socio-piloto',%s,'confirmado',%s,now())""",
                    (id_remision,u["numero_documento_usuario"],len(bundle["entry"])))
        registrar_auditoria(cur, "r30_envios", str(id_remision), "REMITIR",
                           u["numero_documento_usuario"], nuevos={
                               "socio": "socio-piloto", "estado": "confirmado",
                               "recursos": len(bundle["entry"]),
                               "task_fhir_id": _id_fhir("task", id_remision),
                               "consent_fhir_id": _id_fhir("con", r["id_paciente"])})
        db.commit()
        # R17/R18: notificación interna al médico remitente, después de la confirmación.
        # La confirmación de notificación del SOCIO pertenece a la prueba R33.
        from core.eventos import publicar
        publicar(db, [u["numero_documento_usuario"]],
                 tipo="remision_fhir_confirmada",
                 mensaje="El sistema socio confirmó la remisión FHIR",
                 datos={"remision_id": id_remision, "recursos": len(bundle["entry"])})
        return {"estado":"confirmado", "id_remision":id_remision,
                "recursos":len(bundle["entry"]),"respuesta_fhir":"transaction-response",
                "task_fhir_id":_id_fhir("task", id_remision)}
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()


# El receptor de remisiones externas (POST /fhir/remisiones-r30/recibir) se movió a
# routers/recepcion_externa.py (Annie). Ahora exige credenciales institucionales
# R31 (Bearer + permiso bundle:write + x-nonce) en lugar de X-R30-Token, guarda la
# remisión en la base, la audita con origen SOCIO y avisa al especialista.
