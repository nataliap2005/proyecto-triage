"""R29 · R30 · R33: recepción de remisiones FHIR que llegan de la institución socio.

Flujo (lado B del enunciado):
    1. El socio se autentica con credenciales de sistema (R31, Sarah):
       Authorization: Bearer <token>, permiso bundle:write y cabecera x-nonce única.
    2. Se valida el Bundle ANTES de escribir nada. Un Bundle inválido se rechaza
       con 400/413/415/422 y un OperationOutcome, y el rechazo queda auditado.
    3. Los ids del socio se reescriben a ids propios ("ext-..."): el socio nunca
       puede pisar un Patient u Observation nuestro en HAPI FHIR.
    4. Se guarda en HAPI (una sola transacción) y en remisiones_externas, de forma
       que un fallo en cualquiera de los dos no deja datos a medias.
    5. Se audita con origen 'SOCIO' y se avisa en vivo al especialista (R17-R19).

Devolución (secciones 8 y 9):
    - nuestro especialista acepta o rechaza y el socio recibe un Task
      accepted/rejected en su endpoint (R30_SOCIO_RESPUESTA_URL);
    - el socio responde a lo que NOSOTROS enviamos en /fhir/remisiones-r30/respuesta
      (permiso task:write) y el médico remitente recibe el aviso en vivo.
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from psycopg2.errors import UniqueViolation
from psycopg2.extras import Json, RealDictCursor
from pydantic import BaseModel, Field

from auth.institucional import requerir_institucion
from auth.service import requerir_roles
from core.database import get_db
from core.eventos import publicar, usuarios_por_rol
from core.socio_cliente import (SocioError, SocioNoConfigurado, enviar_fhir,
                                institucion_propia, socio_id, url_respuesta)
from routers.common import registrar_auditoria

log = logging.getLogger("uvicorn.error")
router = APIRouter(tags=["R30 · Recepción de remisiones externas"])

LOINC = "http://loinc.org"
SNOMED = "http://snomed.info/sct"
TAG_ORIGEN = "urn:salud-digital:origen-institucion"

MAX_BYTES = 2 * 1024 * 1024        # 2 MB: una remisión no necesita más (DoS)
MAX_ENTRADAS = 50
MAX_PROFUNDIDAD = 40               # JSON anidado a propósito para agotar la pila
MAX_TEXTO = 2000

# Solo lo que tiene sentido en una remisión. Cualquier otro tipo (Subscription,
# Bundle anidado, AuditEvent...) se rechaza: el socio no puede crear lo que quiera en HAPI.
TIPOS_PERMITIDOS = {
    "Patient", "ServiceRequest", "Observation", "DiagnosticReport", "Consent", "Task",
    "Practitioner", "PractitionerRole", "Organization", "Condition",
}
ESTADOS_OBSERVACION = {"final", "amended", "corrected"}
ESTADOS_REPORTE = {"final", "amended", "corrected"}      # solo reportes aprobados
INTENTOS_SR = {"order", "original-order", "plan", "proposal"}
PRIORIDADES = {"routine", "urgent", "asap", "stat"}

PATRON_ID = re.compile(r"^[A-Za-z0-9\-.]{1,64}$")
PATRON_REF = re.compile(
    r"(?:^|/)([A-Z][A-Za-z]+)/([A-Za-z0-9\-.]{1,64})(?:/_history/[A-Za-z0-9\-.]{1,64})?$")
PATRON_ESPECIALIDAD_NOTA = re.compile(r"especialidad\s*:\s*(.+)", re.IGNORECASE)


# =====================================================================
# Respuestas FHIR
# =====================================================================

def outcome(mensaje: str, codigo: str = "invalid") -> dict:
    return {"resourceType": "OperationOutcome",
            "issue": [{"severity": "error", "code": codigo, "diagnostics": mensaje}]}


def rechazo(status: int, mensaje: str, codigo: str = "invalid") -> JSONResponse:
    return JSONResponse(status_code=status, content=outcome(mensaje, codigo),
                        media_type="application/fhir+json")


class ErrorValidacion(Exception):
    """El Bundle no cumple el contrato. Lleva el código HTTP y el código FHIR del issue."""

    def __init__(self, mensaje: str, status: int = 422, codigo: str = "invalid"):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.status = status
        self.codigo = codigo


# =====================================================================
# 1. Validación del Bundle (no escribe nada)
# =====================================================================

@dataclass
class Entrada:
    tipo: str
    clave: str                 # "Tipo/id" si trae id; si no, su fullUrl (urn:uuid:...)
    claves: list[str]          # todas las formas en que otro recurso puede referirse a esta
    recurso: dict


@dataclass
class BundleValidado:
    entradas: list[Entrada]
    indice: dict[str, int] = field(default_factory=dict)   # clave -> posición en entradas
    paciente: int = -1
    solicitud: int = -1
    tarea: int | None = None
    consentimiento: int | None = None

    def resolver(self, referencia) -> int | None:
        """Posición del recurso del Bundle al que apunta la referencia, o None."""
        if not isinstance(referencia, str) or not referencia:
            return None
        if referencia in self.indice:
            return self.indice[referencia]
        m = PATRON_REF.search(referencia)
        if m:
            return self.indice.get(f"{m.group(1)}/{m.group(2)}")
        return None

    def recurso(self, posicion: int | None) -> dict:
        return self.entradas[posicion].recurso if posicion is not None else {}


def _profundidad(obj, nivel: int = 0) -> None:
    if nivel > MAX_PROFUNDIDAD:
        raise ErrorValidacion("El Bundle está anidado más de lo permitido", 422, "too-costly")
    if isinstance(obj, dict):
        for valor in obj.values():
            _profundidad(valor, nivel + 1)
    elif isinstance(obj, list):
        for valor in obj:
            _profundidad(valor, nivel + 1)


def _codings(concepto) -> list[dict]:
    if not isinstance(concepto, dict):
        return []
    return [c for c in concepto.get("coding") or [] if isinstance(c, dict)]


def _tiene_codigo(concepto, sistemas: set[str]) -> bool:
    return any(c.get("system") in sistemas and str(c.get("code") or "").strip()
               for c in _codings(concepto))


def _ref(recurso: dict, campo: str):
    valor = recurso.get(campo)
    return valor.get("reference") if isinstance(valor, dict) else None


def validar_bundle_entrante(bundle, exigir_consentimiento: bool = True) -> BundleValidado:
    """Comprueba el contrato de entrada. Lanza ErrorValidacion con el primer problema."""
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise ErrorValidacion("Se esperaba un recurso Bundle de FHIR R4")
    tipo_bundle = bundle.get("type")
    if tipo_bundle not in ("transaction", "collection"):
        raise ErrorValidacion("El Bundle debe ser de tipo transaction o collection")
    _profundidad(bundle)

    crudas = bundle.get("entry")
    if not isinstance(crudas, list) or not 2 <= len(crudas) <= MAX_ENTRADAS:
        raise ErrorValidacion(f"El Bundle debe traer entre 2 y {MAX_ENTRADAS} recursos")

    v = BundleValidado(entradas=[])
    for n, cruda in enumerate(crudas, start=1):
        if not isinstance(cruda, dict) or not isinstance(cruda.get("resource"), dict):
            raise ErrorValidacion(f"La entrada {n} no trae un recurso")
        recurso = cruda["resource"]
        tipo = recurso.get("resourceType")
        if tipo not in TIPOS_PERMITIDOS:
            raise ErrorValidacion(f"Tipo de recurso no permitido en una remisión: {tipo}")
        for contenido in recurso.get("contained") or []:
            if not isinstance(contenido, dict) or contenido.get("resourceType") not in TIPOS_PERMITIDOS:
                raise ErrorValidacion(f"La entrada {n} contiene un recurso no permitido")

        rid = recurso.get("id")
        if rid is not None and (not isinstance(rid, str) or not PATRON_ID.match(rid)):
            raise ErrorValidacion(f"La entrada {n} tiene un id FHIR inválido")
        full_url = cruda.get("fullUrl")
        if full_url is not None and (not isinstance(full_url, str) or len(full_url) > 255):
            raise ErrorValidacion(f"La entrada {n} tiene un fullUrl inválido")
        if rid is None and not full_url:
            raise ErrorValidacion(f"La entrada {n} no tiene id ni fullUrl")

        if tipo_bundle == "transaction":
            peticion = cruda.get("request")
            if not isinstance(peticion, dict):
                raise ErrorValidacion(f"La entrada {n} de la transacción no trae request")
            metodo, url = peticion.get("method"), str(peticion.get("url") or "")
            # Solo se crean o actualizan recursos: nada de DELETE, GET o PATCH.
            if metodo == "PUT":
                if rid is None or url.split("?")[0] != f"{tipo}/{rid}":
                    raise ErrorValidacion(f"La entrada {n}: PUT con URL que no coincide con el recurso")
            elif metodo == "POST":
                if url.split("?")[0] != tipo:
                    raise ErrorValidacion(f"La entrada {n}: POST con URL que no coincide con el tipo")
            else:
                raise ErrorValidacion(f"La entrada {n}: método {metodo} no permitido")

        claves = []
        if rid is not None:
            claves.append(f"{tipo}/{rid}")
        if full_url:
            claves.append(full_url)
        for clave in claves:
            if clave in v.indice:
                raise ErrorValidacion(f"Recurso repetido en el Bundle: {clave}")
            v.indice[clave] = len(v.entradas)
        v.entradas.append(Entrada(tipo=tipo, clave=claves[0], claves=claves, recurso=recurso))

    tipos = [e.tipo for e in v.entradas]
    if tipos.count("Patient") != 1:
        raise ErrorValidacion("Se requiere exactamente un Patient")
    if tipos.count("ServiceRequest") != 1:
        raise ErrorValidacion("Se requiere exactamente un ServiceRequest (una remisión por Bundle)")
    if tipos.count("Task") > 1:
        raise ErrorValidacion("Se admite como máximo un Task")
    if tipos.count("Consent") > 1:
        raise ErrorValidacion("Se admite como máximo un Consent")
    v.paciente = tipos.index("Patient")
    v.solicitud = tipos.index("ServiceRequest")
    v.tarea = tipos.index("Task") if "Task" in tipos else None
    v.consentimiento = tipos.index("Consent") if "Consent" in tipos else None

    def del_paciente(referencia) -> bool:
        return v.resolver(referencia) == v.paciente

    for e in v.entradas:
        r = e.recurso
        if e.tipo == "ServiceRequest":
            if r.get("status") != "active":
                raise ErrorValidacion("El ServiceRequest debe estar activo (status = active)")
            if r.get("intent") not in INTENTOS_SR:
                raise ErrorValidacion("El ServiceRequest tiene un intent no válido para una remisión")
            if not _tiene_codigo(r.get("code"), {SNOMED, LOINC}):
                raise ErrorValidacion("El ServiceRequest requiere un código SNOMED CT o LOINC")
            if not del_paciente(_ref(r, "subject")):
                raise ErrorValidacion("El ServiceRequest no apunta al Patient del Bundle")
        elif e.tipo == "Observation":
            if not _tiene_codigo(r.get("code"), {LOINC}):
                raise ErrorValidacion("Cada Observation requiere un código LOINC")
            if r.get("status") not in ESTADOS_OBSERVACION:
                raise ErrorValidacion("Observation con estado no válido (final, amended o corrected)")
            if not del_paciente(_ref(r, "subject")):
                raise ErrorValidacion("Una Observation no pertenece al Patient del Bundle")
        elif e.tipo == "DiagnosticReport":
            # El enunciado: solo viaja el DiagnosticReport de IA APROBADO.
            if r.get("status") not in ESTADOS_REPORTE:
                raise ErrorValidacion("Solo se reciben DiagnosticReport finales (aprobados)")
            codigo = r.get("code")
            if not isinstance(codigo, dict) or not (_codings(codigo) or codigo.get("text")):
                raise ErrorValidacion("DiagnosticReport sin código")
            if not del_paciente(_ref(r, "subject")):
                raise ErrorValidacion("Un DiagnosticReport no pertenece al Patient del Bundle")
        elif e.tipo == "Consent":
            if r.get("status") != "active":
                raise ErrorValidacion("El Consent debe estar activo")
            if not del_paciente(_ref(r, "patient")):
                raise ErrorValidacion("El Consent no pertenece al Patient del Bundle")
            provision = r.get("provision") if isinstance(r.get("provision"), dict) else {}
            if provision.get("type") != "permit":
                raise ErrorValidacion("El Consent no concede permiso (provision.type = permit)")
            fin = (provision.get("period") or {}).get("end")
            if fin:
                try:
                    vence = datetime.fromisoformat(str(fin).replace("Z", "+00:00"))
                    if vence.tzinfo is None:
                        vence = vence.replace(tzinfo=timezone.utc)
                except ValueError:
                    raise ErrorValidacion("El Consent tiene una vigencia inválida")
                if vence <= datetime.now(timezone.utc):
                    raise ErrorValidacion("El Consent está vencido")
        elif e.tipo == "Task":
            if r.get("status") != "requested":
                raise ErrorValidacion("El Task de una remisión nueva debe estar en requested")
            if v.resolver(_ref(r, "focus")) != v.solicitud:
                raise ErrorValidacion("El Task no apunta al ServiceRequest del Bundle")
            if not del_paciente(_ref(r, "for")):
                raise ErrorValidacion("El Task no pertenece al Patient del Bundle")

    # R32: el socio solo puede remitir con consentimiento del paciente.
    if exigir_consentimiento and v.consentimiento is None:
        raise ErrorValidacion("Falta el Consent del paciente para compartir con esta institución")
    return v


# =====================================================================
# 2. Reescritura para nuestro HAPI FHIR
# =====================================================================

def id_local(client_id: str, tipo: str, clave: str) -> str:
    """Id propio, estable para el mismo socio y recurso, y distinto entre socios."""
    huella = hashlib.sha256(f"{client_id}|{tipo}|{clave}".encode()).hexdigest()[:40]
    return f"ext-{huella}"


def _reescribir_referencias(obj, v: BundleValidado, nuevas: list[str]) -> None:
    if isinstance(obj, dict):
        referencia = obj.get("reference")
        if isinstance(referencia, str) and not referencia.startswith("#"):
            posicion = v.resolver(referencia)
            if posicion is not None:
                obj["reference"] = nuevas[posicion]
            else:
                # Apunta a algo que no vino en el Bundle (un Practitioner del socio, su
                # Organization...). Se conserva como texto para no dejar una referencia
                # colgante en HAPI.
                obj.pop("reference")
                obj.setdefault("display", f"{referencia} (en la institución de origen)"[:200])
        for valor in obj.values():
            _reescribir_referencias(valor, v, nuevas)
    elif isinstance(obj, list):
        for valor in obj:
            _reescribir_referencias(valor, v, nuevas)


def reescribir_para_hapi(v: BundleValidado, client_id: str) -> tuple[dict, dict]:
    """Devuelve (Bundle transaction para HAPI, {referencia de origen: referencia local})."""
    nuevas = [f"{e.tipo}/{id_local(client_id, e.tipo, e.clave)}" for e in v.entradas]
    entradas = []
    for e, nueva in zip(v.entradas, nuevas):
        recurso = copy.deepcopy(e.recurso)
        recurso["id"] = nueva.split("/", 1)[1]
        # El narrativo XHTML no se guarda (no se muestra y es superficie de inyección).
        recurso.pop("text", None)
        # meta del socio (versiones, fechas) se reemplaza por la procedencia.
        recurso["meta"] = {"source": f"urn:salud-digital:socio:{client_id}",
                           "tag": [{"system": TAG_ORIGEN, "code": client_id}]}
        _reescribir_referencias(recurso, v, nuevas)
        entradas.append({
            "fullUrl": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, client_id + '/' + nueva)}",
            "resource": recurso,
            "request": {"method": "PUT", "url": nueva},
        })
    mapa = {e.clave: nueva for e, nueva in zip(v.entradas, nuevas)}
    return {"resourceType": "Bundle", "type": "transaction", "entry": entradas}, mapa


# =====================================================================
# 3. Resumen para la bandeja del especialista
# =====================================================================

def _texto(valor, limite: int = MAX_TEXTO) -> str:
    return re.sub(r"\s+", " ", str(valor or "")).strip()[:limite]


def _nombre_concepto(concepto) -> str:
    if not isinstance(concepto, dict):
        return ""
    if concepto.get("text"):
        return _texto(concepto["text"], 200)
    for c in _codings(concepto):
        if c.get("display"):
            return _texto(c["display"], 200)
    return ""


def _valor_observacion(r: dict) -> tuple[str | None, str | None]:
    if isinstance(r.get("valueQuantity"), dict):
        q = r["valueQuantity"]
        return (str(q.get("value")) if q.get("value") is not None else None,
                _texto(q.get("unit") or q.get("code"), 30) or None)
    if r.get("valueString") is not None:
        return _texto(r["valueString"], 200), None
    if isinstance(r.get("valueCodeableConcept"), dict):
        return _nombre_concepto(r["valueCodeableConcept"]) or None, None
    for clave in ("valueInteger", "valueBoolean"):
        if clave in r:
            return str(r[clave]), None
    return None, None


def extraer_resumen(v: BundleValidado) -> dict:
    paciente = v.recurso(v.paciente)
    sr = v.recurso(v.solicitud)

    nombre = ""
    for n in paciente.get("name") or []:
        if isinstance(n, dict):
            nombre = _texto(n.get("text"), 150) or _texto(
                " ".join([*(n.get("given") or []), n.get("family") or ""]), 150)
            if nombre:
                break

    motivos = [_nombre_concepto(c) for c in sr.get("reasonCode") or []]
    motivos = [m for m in motivos if m]
    notas = [_texto(n.get("text"), 500) for n in sr.get("note") or [] if isinstance(n, dict)]
    notas = [n for n in notas if n]
    motivo = " · ".join(motivos) or " · ".join(notas) or _nombre_concepto(sr.get("code"))

    # Lugar estándar: ServiceRequest.performerType. Respaldo: una nota
    # "Especialidad: X", que es como la envía hoy el Bundle de Natalia.
    especialidad = _nombre_concepto(sr.get("performerType"))
    if not especialidad:
        for nota in notas:
            m = PATRON_ESPECIALIDAD_NOTA.search(nota)
            if m:
                especialidad = _texto(m.group(1), 150)
                break

    observaciones = []
    reportes = []
    for e in v.entradas:
        r = e.recurso
        if e.tipo == "Observation" and len(observaciones) < 30:
            loinc = next((c.get("code") for c in _codings(r.get("code")) if c.get("system") == LOINC), None)
            valor, unidad = _valor_observacion(r)
            observaciones.append({"loinc": loinc, "nombre": _nombre_concepto(r.get("code")) or loinc,
                                  "valor": valor, "unidad": unidad,
                                  "fecha": _texto(r.get("effectiveDateTime"), 40) or None})
        elif e.tipo == "DiagnosticReport" and len(reportes) < 10:
            reportes.append({"nombre": _nombre_concepto(r.get("code")),
                             "conclusion": _texto(r.get("conclusion"), 1000) or None,
                             "estado": r.get("status"),
                             "emitido": _texto(r.get("issued"), 40) or None})

    consentimiento = None
    if v.consentimiento is not None:
        c = v.recurso(v.consentimiento)
        periodo = (c.get("provision") or {}).get("period") or {}
        consentimiento = {"estado": c.get("status"), "inicio": periodo.get("start"),
                          "fin": periodo.get("end")}

    return {
        "motivo": _texto(motivo) or "Sin motivo declarado",
        "especialidad_texto": especialidad or None,
        "prioridad": sr.get("priority") if sr.get("priority") in PRIORIDADES else None,
        "resumen": {
            "paciente": {"nombre": nombre or None, "genero": paciente.get("gender"),
                         "nacimiento": paciente.get("birthDate")},
            "observaciones": observaciones,
            "reportes": reportes,
            "consentimiento": consentimiento,
            "task_estado": v.recurso(v.tarea).get("status") if v.tarea is not None else None,
        },
    }


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def mapear_especialidad(cur, texto: str | None) -> int | None:
    """Busca la especialidad pedida en el catálogo local, sin tildes ni mayúsculas."""
    buscado = _normalizar(texto or "")
    if len(buscado) < 4:
        return None
    cur.execute("SELECT id_especialidad, nombre FROM especialidades WHERE activo = TRUE;")
    catalogo = [(f["id_especialidad"], _normalizar(f["nombre"])) for f in cur.fetchall()]
    for id_esp, nombre in catalogo:
        if nombre == buscado:
            return id_esp
    for id_esp, nombre in catalogo:
        if nombre in buscado or buscado in nombre:
            return id_esp
    return None


# =====================================================================
# 4. Auditoría y avisos
# =====================================================================

def auditar_externo(cur, tabla: str, registro_id, accion: str, datos: dict) -> None:
    """Hecho causado por otra institución: sin usuario humano, origen 'SOCIO' (006, R28)."""
    cur.execute("""
        INSERT INTO auditoria_cambios(tabla_afectada, registro_id, accion,
                                      datos_nuevos, realizado_por, origen)
        VALUES (%s, %s, %s, %s, NULL, 'SOCIO');
    """, (tabla, str(registro_id)[:100], accion, Json(datos)))


def ip_cliente(request: Request) -> str | None:
    # Cloudflare -> Nginx -> API. Solo es contexto para la auditoría: la identidad
    # del socio la da el token, nunca la IP.
    for cabecera in ("cf-connecting-ip", "x-real-ip"):
        valor = request.headers.get(cabecera)
        if valor:
            return valor[:64]
    return request.client.host if request.client else None


def registrar_rechazo(db, inst: dict, error: ErrorValidacion, ip: str | None,
                      notificar: bool = True) -> None:
    """Audita el rechazo en su propia transacción y avisa a los Admin. Nunca lanza."""
    try:
        db.rollback()
        cur = db.cursor()
        try:
            auditar_externo(cur, "interop_entrada", inst["client_id"], "RECHAZO_VALIDACION_EXTERNA", {
                "client_id": inst["client_id"], "institucion": inst.get("nombre"),
                "http": error.status, "codigo": error.codigo,
                "motivo": error.mensaje[:300], "ip": ip,
            })
            db.commit()
        finally:
            cur.close()
        if notificar:
            publicar(db, usuarios_por_rol(db, "Admin"),
                     tipo="remision_externa_invalida",
                     mensaje=f"Se rechazó una remisión de {inst.get('nombre') or inst['client_id']}: "
                             f"{error.mensaje[:200]}",
                     datos={"client_id": inst["client_id"], "http": error.status,
                            "motivo": error.mensaje[:300]})
    except Exception:
        db.rollback()
        log.exception("No se pudo auditar el rechazo de una remisión externa")


def _destinatarios(cur, id_especialidad: int | None) -> list[int]:
    if id_especialidad is not None:
        cur.execute("""
            SELECT u.numero_documento_usuario
            FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            JOIN usuario_especialidades ue ON ue.numero_documento_usuario = u.numero_documento_usuario
            WHERE r.nombre = 'Especialista' AND ue.id_especialidad = %s
              AND u.estado = TRUE AND u.is_deleted = FALSE;
        """, (id_especialidad,))
        ids = [f["numero_documento_usuario"] for f in cur.fetchall()]
        if ids:
            return ids
    # Especialidad desconocida o sin especialistas: nadie queda sin enterarse.
    cur.execute("""
        SELECT u.numero_documento_usuario
        FROM usuarios u JOIN roles r ON r.id_rol = u.id_rol
        WHERE r.nombre IN ('Especialista', 'Admin') AND u.estado = TRUE AND u.is_deleted = FALSE;
    """)
    return [f["numero_documento_usuario"] for f in cur.fetchall()]


# =====================================================================
# 5. HAPI FHIR
# =====================================================================

def _hapi_url() -> str:
    from core.config import HAPI_FHIR_URL
    return HAPI_FHIR_URL


def _evaluar_respuesta_hapi(respuesta, esperadas: int) -> tuple[dict | None, ErrorValidacion | None]:
    if respuesta.status_code not in (200, 201):
        detalle = "El servidor FHIR rechazó la transacción"
        try:
            cuerpo = respuesta.json()
            issue = (cuerpo.get("issue") or [{}])[0] if isinstance(cuerpo, dict) else {}
            if issue.get("diagnostics"):
                detalle += ": " + _texto(issue["diagnostics"], 300)
        except ValueError:
            pass
        if 400 <= respuesta.status_code < 500:
            return None, ErrorValidacion(detalle, 422, "processing")
        return None, ErrorValidacion("El servidor FHIR no pudo procesar la transacción", 502, "exception")
    try:
        cuerpo = respuesta.json()
    except ValueError:
        return None, ErrorValidacion("Respuesta inválida del servidor FHIR", 502, "exception")
    entradas = cuerpo.get("entry") or [] if isinstance(cuerpo, dict) else []
    if (not isinstance(cuerpo, dict) or cuerpo.get("resourceType") != "Bundle"
            or cuerpo.get("type") != "transaction-response" or len(entradas) != esperadas
            or any(not str((e.get("response") or {}).get("status", "")).startswith(("200", "201"))
                   for e in entradas)):
        return None, ErrorValidacion("El servidor FHIR no confirmó todas las entradas", 502, "exception")
    return cuerpo, None


def _compensar_hapi(mapa: dict, hapi_post) -> None:
    """Si la base falla DESPUÉS de que HAPI confirmó, se deshace lo escrito en HAPI.

    Va en UNA transacción de DELETE: así HAPI borra el Patient junto con las
    Observation que lo referencian (borrarlos uno por uno fallaría por integridad).
    """
    deshacer = {"resourceType": "Bundle", "type": "transaction",
                "entry": [{"request": {"method": "DELETE", "url": ref}} for ref in mapa.values()]}
    try:
        respuesta = hapi_post(_hapi_url(), json=deshacer, timeout=25, headers={
            "Content-Type": "application/fhir+json", "Accept": "application/fhir+json"})
        if respuesta.status_code not in (200, 201):
            raise requests.RequestException(f"HTTP {respuesta.status_code}")
    except requests.RequestException:
        log.error("R30: no se pudo deshacer en HAPI %s; revisar a mano", list(mapa.values()))


# =====================================================================
# 6. Proceso completo
# =====================================================================

def _exigir_consentimiento() -> bool:
    return os.getenv("R30_EXIGIR_CONSENT", "true").strip().lower() not in ("false", "0", "no")


# ---------------------------------------------------------------------
# Compatibilidad con socios de clave fija (R31 "API key por institución")
# ---------------------------------------------------------------------
# SNOMED CT 3457005 "Patient referral": el ServiceRequest ES una remisión.
CODIGO_REMISION = {"system": SNOMED, "code": "3457005", "display": "Patient referral"}
CAMPOS_AJENOS = ("security_envelope",)


def es_ping(cuerpo, cabecera_ping: str | None) -> bool:
    """Prueba de conexión del socio: cabecera X-Interop-Ping o un Parameters vacío."""
    if str(cabecera_ping or "").strip().lower() in ("true", "1", "yes"):
        return True
    return isinstance(cuerpo, dict) and cuerpo.get("resourceType") == "Parameters"


def adaptar_bundle_socio(bundle):
    """Completa SOLO lo que falta en el Bundle de un socio de clave fija, sin
    cambiar nada de lo que sí trae: luego pasa por la misma validación de siempre
    (un valor presente e inválido se sigue rechazando con 422).

    - Quita campos ajenos a FHIR (security_envelope) para que HAPI no los rechace.
    - Entrada sin id ni fullUrl: se le asigna un urn:uuid.
    - ServiceRequest sin status/intent: active/order; con solo code.text: se le
      agrega el código SNOMED CT de remisión y se conserva su texto.
    - Observation sin status: final.
    - Sin referencia al paciente: se apunta al único Patient del Bundle.
    - Consent activo sin provision.type: permit (un deny se sigue rechazando).
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get("entry"), list):
        return bundle
    for campo in CAMPOS_AJENOS:
        bundle.pop(campo, None)
    entradas = [e for e in bundle["entry"] if isinstance(e, dict) and isinstance(e.get("resource"), dict)]
    for e in entradas:
        for campo in CAMPOS_AJENOS:
            e.pop(campo, None)
            e["resource"].pop(campo, None)
        r = e["resource"]
        if r.get("id") is None and not e.get("fullUrl"):
            e["fullUrl"] = f"urn:uuid:{uuid.uuid4()}"

    pacientes = [e for e in entradas if e["resource"].get("resourceType") == "Patient"]
    ref_paciente = None
    if len(pacientes) == 1:
        p = pacientes[0]
        ref_paciente = (f"Patient/{p['resource']['id']}" if p["resource"].get("id") is not None
                        else p.get("fullUrl"))

    def con_paciente(r, campo):
        if ref_paciente and not (isinstance(r.get(campo), dict) and r[campo].get("reference")):
            r[campo] = {"reference": ref_paciente}

    for e in entradas:
        r, tipo = e["resource"], e["resource"].get("resourceType")
        if tipo == "ServiceRequest":
            r.setdefault("status", "active")
            r.setdefault("intent", "order")
            con_paciente(r, "subject")
            codigo = r.get("code") if isinstance(r.get("code"), dict) else None
            if codigo is not None and not _tiene_codigo(codigo, {SNOMED, LOINC}) and codigo.get("text"):
                codigo.setdefault("coding", []).append(dict(CODIGO_REMISION))
            elif codigo is None:
                r["code"] = {"coding": [dict(CODIGO_REMISION)], "text": "Remisión"}
        elif tipo == "Observation":
            r.setdefault("status", "final")
            con_paciente(r, "subject")
        elif tipo == "DiagnosticReport":
            con_paciente(r, "subject")
        elif tipo == "Consent":
            con_paciente(r, "patient")
            provision = r.get("provision")
            if not isinstance(provision, dict):
                r["provision"] = provision = {}
            provision.setdefault("type", "permit")
    return bundle


def _content_type_valido(content_type: str | None) -> bool:
    principal = (content_type or "").split(";")[0].strip().lower()
    return principal in ("application/fhir+json", "application/json")


def procesar_recepcion(db, inst: dict, crudo: bytes, content_type: str | None, ip: str | None,
                       hapi_post=None, cabecera_ping: str | None = None) -> JSONResponse:
    hapi_post = hapi_post or requests.post
    client_id = inst["client_id"]

    # --- a. Validación: nada se escribe todavía ---------------------------
    try:
        if not _content_type_valido(content_type):
            raise ErrorValidacion("Content-Type debe ser application/fhir+json", 415, "not-supported")
        if len(crudo) > MAX_BYTES:
            raise ErrorValidacion("El Bundle supera el tamaño máximo (2 MB)", 413, "too-costly")
        try:
            bundle = json.loads(crudo)
        except (ValueError, RecursionError):
            raise ErrorValidacion("El cuerpo no es JSON válido", 400, "structure")
        if es_ping(bundle, cabecera_ping):
            # La credencial ya fue validada por R31: solo se confirma la conexión.
            return JSONResponse(status_code=200, media_type="application/fhir+json", content={
                "resourceType": "OperationOutcome",
                "issue": [{"severity": "information", "code": "informational",
                           "diagnostics": f"Conexión verificada con {inst.get('nombre') or client_id}"}]})
        if inst.get("autenticacion") == "clave_fija":
            bundle = adaptar_bundle_socio(bundle)
        validado = validar_bundle_entrante(bundle, _exigir_consentimiento())
    except ErrorValidacion as error:
        registrar_rechazo(db, inst, error, ip)
        return rechazo(error.status, error.mensaje, error.codigo)

    transaccion, mapa = reescribir_para_hapi(validado, client_id)
    datos = extraer_resumen(validado)
    sr_ref = validado.entradas[validado.solicitud].clave
    task_ref = validado.entradas[validado.tarea].clave if validado.tarea is not None else None
    paciente_ref = validado.entradas[validado.paciente].clave

    # --- b. Base + HAPI, con la transacción de la base abierta -------------
    # Si HAPI falla, rollback: no queda la remisión en la base.
    # Si la base falla después de HAPI, se borra lo escrito en HAPI.
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT pg_advisory_xact_lock(30031, hashtext(%s));", (f"{client_id}|{sr_ref}",))
        cur.execute("""SELECT id_remision_externa FROM remisiones_externas
                       WHERE socio_client_id = %s AND sr_ref_origen = %s;""", (client_id, sr_ref))
        if cur.fetchone():
            error = ErrorValidacion("Esta remisión ya fue recibida", 409, "duplicate")
            registrar_rechazo(db, inst, error, ip, notificar=False)
            return rechazo(error.status, error.mensaje, error.codigo)

        id_especialidad = mapear_especialidad(cur, datos["especialidad_texto"])
        cur.execute("""
            INSERT INTO remisiones_externas(
                socio_client_id, sr_ref_origen, task_ref_origen, paciente_ref_origen,
                ids_locales, id_especialidad, especialidad_texto, prioridad,
                motivo, resumen, recursos)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id_remision_externa, fecha_recepcion;
        """, (client_id, sr_ref, task_ref, paciente_ref, Json(mapa), id_especialidad,
              datos["especialidad_texto"], datos["prioridad"], datos["motivo"],
              Json(datos["resumen"]), len(validado.entradas)))
        fila = cur.fetchone()
        id_externa = fila["id_remision_externa"]
        auditar_externo(cur, "remisiones_externas", id_externa, "RECIBIR_REMISION_EXTERNA", {
            "client_id": client_id, "institucion": inst.get("nombre"),
            "sr_ref_origen": sr_ref, "task_ref_origen": task_ref,
            "recursos": len(validado.entradas), "id_especialidad": id_especialidad,
            "especialidad_texto": datos["especialidad_texto"], "ip": ip,
        })

        try:
            respuesta = hapi_post(_hapi_url(), json=transaccion, timeout=25, headers={
                "Content-Type": "application/fhir+json", "Accept": "application/fhir+json"})
        except requests.RequestException:
            db.rollback()
            error = ErrorValidacion("Servidor FHIR local no disponible", 503, "transient")
            registrar_rechazo(db, inst, error, ip, notificar=False)
            return rechazo(error.status, error.mensaje, error.codigo)

        confirmacion, error = _evaluar_respuesta_hapi(respuesta, len(transaccion["entry"]))
        if error:
            db.rollback()
            registrar_rechazo(db, inst, error, ip)
            return rechazo(error.status, error.mensaje, error.codigo)

        try:
            db.commit()
        except Exception:
            db.rollback()
            _compensar_hapi(mapa, hapi_post)
            raise
    except UniqueViolation:
        # Dos envíos simultáneos del mismo ServiceRequest: gana el primero.
        db.rollback()
        error = ErrorValidacion("Esta remisión ya fue recibida", 409, "duplicate")
        registrar_rechazo(db, inst, error, ip, notificar=False)
        return rechazo(error.status, error.mensaje, error.codigo)
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()

    # --- c. Aviso en vivo (después del commit, como pide core.eventos) -----
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)
        try:
            destinatarios = _destinatarios(cur, id_especialidad)
            nombre_especialidad = datos["especialidad_texto"] or "especialidad no indicada"
            if id_especialidad is not None:
                cur.execute("SELECT nombre FROM especialidades WHERE id_especialidad = %s;",
                            (id_especialidad,))
                nombre_especialidad = (cur.fetchone() or {}).get("nombre") or nombre_especialidad
        finally:
            cur.close()
        db.rollback()   # cierra la transacción de solo lectura antes de publicar
        paciente = datos["resumen"]["paciente"]["nombre"] or "paciente externo"
        publicar(db, destinatarios, tipo="remision_externa_recibida",
                 mensaje=f"Nueva remisión de {inst.get('nombre') or client_id} a "
                         f"{nombre_especialidad}: {paciente}",
                 datos={"remision_externa_id": id_externa, "institucion": inst.get("nombre"),
                        "client_id": client_id, "especialidad": nombre_especialidad,
                        "prioridad": datos["prioridad"]})
    except Exception:
        db.rollback()
        log.exception("La remisión externa %s se guardó, pero no se pudo notificar", id_externa)

    return JSONResponse(status_code=200, content=confirmacion, media_type="application/fhir+json",
                        headers={"X-Remision-Externa": str(id_externa)})


# =====================================================================
# 7. Endpoints
# =====================================================================

@router.post("/fhir/remisiones-r30/recibir")
async def recibir_remision_externa(
    request: Request,
    inst=Depends(requerir_institucion("bundle:write", exigir_nonce=True)),
    db=Depends(get_db),
):
    """Entrada de remisiones del socio (R30). Autenticación R31 + nonce (R29).

    El cuerpo se lee crudo para responder siempre con OperationOutcome,
    incluso si no es JSON, y para limitar su tamaño antes de procesarlo.
    """
    crudo = await request.body()
    return await run_in_threadpool(
        procesar_recepcion, db, inst, crudo,
        request.headers.get("content-type"), ip_cliente(request),
        cabecera_ping=request.headers.get("x-interop-ping"))


@router.get("/remisiones-externas", tags=["Remisiones"])
def listar_remisiones_externas(db=Depends(get_db),
                               u=Depends(requerir_roles("Admin", "Especialista"))):
    """Bandeja de remisiones externas.

    Especialista: las pendientes de sus especialidades (o sin especialidad
    reconocida) y las que él respondió. Admin: todas.
    """
    filtro, params = "", []
    if u["rol"] == "Especialista":
        filtro = """
            WHERE (re.estado = 'pendiente' AND (re.id_especialidad IS NULL OR re.id_especialidad IN (
                       SELECT id_especialidad FROM usuario_especialidades
                       WHERE numero_documento_usuario = %s)))
               OR re.especialista_asignado = %s"""
        params = [u["numero_documento_usuario"], u["numero_documento_usuario"]]
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute(f"""
            SELECT re.id_remision_externa, re.socio_client_id, ci.nombre AS institucion,
                   re.id_especialidad, COALESCE(e.nombre, re.especialidad_texto) AS especialidad,
                   re.prioridad, re.motivo, re.resumen, re.recursos, re.estado,
                   re.especialista_asignado, re.observacion_respuesta,
                   re.fecha_recepcion, re.fecha_respuesta, re.respuesta_enviada
            FROM remisiones_externas re
            JOIN clientes_institucionales ci ON ci.client_id = re.socio_client_id
            LEFT JOIN especialidades e ON e.id_especialidad = re.id_especialidad
            {filtro}
            ORDER BY re.fecha_recepcion DESC
            LIMIT 200;
        """, params)
        return cur.fetchall()
    finally:
        cur.close()


def contar_externas_pendientes(cur, especialista: int) -> int:
    """Para /pendientes: remisiones externas que este especialista puede atender."""
    cur.execute("""
        SELECT count(*) FROM remisiones_externas
        WHERE estado = 'pendiente'
          AND (id_especialidad IS NULL OR id_especialidad IN (
                SELECT id_especialidad FROM usuario_especialidades
                WHERE numero_documento_usuario = %s));
    """, (especialista,))
    fila = cur.fetchone()
    return int(fila[0] if isinstance(fila, (tuple, list)) else list(fila.values())[0])


# =====================================================================
# 8. Devolución: nuestro especialista acepta o rechaza (salida hacia el socio)
# =====================================================================

class Decision(BaseModel):
    observacion: str | None = Field(default=None, max_length=500)


ESTADO_TASK = {"aceptada": "accepted", "rechazada": "rejected"}


def construir_task_respuesta(fila: dict) -> dict:
    """Task que le devolvemos al socio. Apunta a SU ServiceRequest y a SU paciente."""
    estado = fila["estado"]
    task = {
        "resourceType": "Task",
        "status": ESTADO_TASK[estado],
        "intent": "order",
        "focus": {"reference": fila["sr_ref_origen"]},
        "basedOn": [{"reference": fila["sr_ref_origen"]}],
        "for": {"reference": fila["paciente_ref_origen"]},
        "lastModified": (fila.get("fecha_respuesta") or datetime.now(timezone.utc)).isoformat(),
        "owner": {"display": institucion_propia()},
        "businessStatus": {"text": "Aceptada por el especialista" if estado == "aceptada"
                           else "Rechazada por el especialista"},
        "identifier": [{"system": "urn:salud-digital:remision-externa",
                        "value": str(fila["id_remision_externa"])}],
    }
    m = PATRON_REF.search(fila.get("task_ref_origen") or "")
    if m and m.group(1) == "Task":
        task["id"] = m.group(2)            # el mismo Task que ellos enviaron
    if fila.get("observacion_respuesta"):
        task["statusReason"] = {"text": _texto(fila["observacion_respuesta"], 500)}
    return task


def _actualizar_task_local(fila: dict) -> None:
    """Refleja la decisión en la copia del Task guardada en nuestro HAPI (mejor esfuerzo)."""
    local = (fila.get("ids_locales") or {}).get(fila.get("task_ref_origen") or "")
    if not local:
        return
    url = f"{_hapi_url()}/{local}"
    try:
        r = requests.get(url, timeout=10, headers={"Accept": "application/fhir+json"})
        if r.status_code != 200:
            return
        task = r.json()
        task["status"] = ESTADO_TASK[fila["estado"]]
        task["lastModified"] = datetime.now(timezone.utc).isoformat()
        if fila.get("observacion_respuesta"):
            task["statusReason"] = {"text": _texto(fila["observacion_respuesta"], 500)}
        requests.put(url, json=task, timeout=10, headers={"Content-Type": "application/fhir+json"})
    except (requests.RequestException, ValueError):
        log.warning("R30: no se pudo actualizar el Task local %s", local)


def enviar_respuesta_al_socio(db, id_externa: int, post=None) -> dict:
    """Envía el Task de respuesta y marca respuesta_enviada. Nunca lanza por fallas del socio."""
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM remisiones_externas WHERE id_remision_externa = %s;", (id_externa,))
        fila = cur.fetchone()
    finally:
        cur.close()
    db.rollback()
    if not fila or fila["estado"] == "pendiente":
        return {"respuesta_enviada": False, "detalle": "La remisión aún no tiene respuesta"}
    if fila["respuesta_enviada"]:
        return {"respuesta_enviada": True, "detalle": "La respuesta ya había sido entregada"}
    # La respuesta solo puede ir a la institución que ENVIÓ la remisión. Las URL y
    # credenciales de salida son de un único socio (R30_SOCIO_ID): si la remisión llegó
    # de otra institución, no se le manda a la equivocada; queda para reenviar cuando
    # el servidor se configure para esa institución.
    if fila["socio_client_id"] != socio_id():
        return {"respuesta_enviada": False,
                "detalle": f"La remisión llegó de '{fila['socio_client_id']}', pero el servidor está "
                           f"configurado para responder a '{socio_id()}'; no se envió"}
    try:
        respuesta = enviar_fhir(url_respuesta(), construir_task_respuesta(fila), post=post)
    except SocioNoConfigurado as e:
        return {"respuesta_enviada": False, "detalle": f"Socio sin configurar: {e}"}
    except SocioError as e:
        return {"respuesta_enviada": False, "detalle": str(e)}
    if respuesta.status_code not in (200, 201):
        return {"respuesta_enviada": False,
                "detalle": f"El socio no aceptó la respuesta (HTTP {respuesta.status_code})"}
    cur = db.cursor()
    try:
        cur.execute("""UPDATE remisiones_externas
                       SET respuesta_enviada = TRUE, respuesta_enviada_at = now()
                       WHERE id_remision_externa = %s;""", (id_externa,))
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()
    return {"respuesta_enviada": True, "detalle": "El socio recibió la respuesta"}


def _decidir(id_externa: int, estado: str, body: Decision, db, u: dict) -> dict:
    uid = u["numero_documento_usuario"]
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""SELECT * FROM remisiones_externas
                       WHERE id_remision_externa = %s FOR UPDATE;""", (id_externa,))
        fila = cur.fetchone()
        if not fila:
            raise HTTPException(status_code=404, detail="Remisión externa no encontrada")
        if fila["estado"] != "pendiente":
            raise HTTPException(status_code=409, detail="La remisión externa ya fue respondida")
        if fila["id_especialidad"] is not None:
            cur.execute("""SELECT 1 FROM usuario_especialidades
                           WHERE numero_documento_usuario = %s AND id_especialidad = %s;""",
                        (uid, fila["id_especialidad"]))
            if not cur.fetchone():
                raise HTTPException(status_code=403, detail="La remisión es de otra especialidad")
        observacion = _texto(body.observacion, 500) or None
        cur.execute("""
            UPDATE remisiones_externas
            SET estado = %s, especialista_asignado = %s, observacion_respuesta = %s,
                fecha_respuesta = now()
            WHERE id_remision_externa = %s
            RETURNING *;
        """, (estado, uid, observacion, id_externa))
        fila = cur.fetchone()
        registrar_auditoria(
            cur, "remisiones_externas", id_externa,
            "ACEPTAR_REMISION_EXTERNA" if estado == "aceptada" else "RECHAZAR_REMISION_EXTERNA",
            uid, anteriores={"estado": "pendiente"},
            nuevos={"estado": estado, "observacion": observacion,
                    "socio_client_id": fila["socio_client_id"],
                    "sr_ref_origen": fila["sr_ref_origen"]})
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()

    _actualizar_task_local(fila)
    envio = enviar_respuesta_al_socio(db, id_externa)
    if not envio["respuesta_enviada"]:
        log.warning("R30: respuesta de la remisión externa %s pendiente: %s", id_externa, envio["detalle"])
    return {"id_remision_externa": id_externa, "estado": estado, **envio}


@router.patch("/remisiones-externas/{id_externa}/aceptar", tags=["Remisiones"])
def aceptar_remision_externa(id_externa: int, body: Decision = Decision(), db=Depends(get_db),
                             u=Depends(requerir_roles("Especialista"))):
    """El especialista acepta; el socio recibe un Task en estado accepted."""
    return _decidir(id_externa, "aceptada", body, db, u)


@router.patch("/remisiones-externas/{id_externa}/rechazar", tags=["Remisiones"])
def rechazar_remision_externa(id_externa: int, body: Decision = Decision(), db=Depends(get_db),
                              u=Depends(requerir_roles("Especialista"))):
    """El especialista rechaza; el socio recibe un Task en estado rejected con el motivo."""
    return _decidir(id_externa, "rechazada", body, db, u)


@router.post("/remisiones-externas/{id_externa}/reenviar-respuesta", tags=["Remisiones"])
def reenviar_respuesta(id_externa: int, db=Depends(get_db),
                       u=Depends(requerir_roles("Especialista", "Admin"))):
    """Reintenta entregar la respuesta si el socio no estaba disponible."""
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""SELECT estado, especialista_asignado FROM remisiones_externas
                       WHERE id_remision_externa = %s;""", (id_externa,))
        fila = cur.fetchone()
    finally:
        cur.close()
    db.rollback()
    if not fila:
        raise HTTPException(status_code=404, detail="Remisión externa no encontrada")
    if fila["estado"] == "pendiente":
        raise HTTPException(status_code=409, detail="Primero acepte o rechace la remisión")
    if u["rol"] == "Especialista" and fila["especialista_asignado"] != u["numero_documento_usuario"]:
        raise HTTPException(status_code=403, detail="Solo quien respondió puede reenviar")
    return {"id_remision_externa": id_externa, **enviar_respuesta_al_socio(db, id_externa)}


# =====================================================================
# 9. Respuesta del socio a lo que NOSOTROS le enviamos (entrada)
# =====================================================================

ESTADO_SOCIO = {"accepted": "aceptada", "rejected": "rechazada"}
MAX_BYTES_TASK = 64 * 1024


def validar_task_respuesta(task) -> dict:
    if not isinstance(task, dict) or task.get("resourceType") != "Task":
        raise ErrorValidacion("Se esperaba un recurso Task")
    _profundidad(task)
    if task.get("status") not in ESTADO_SOCIO:
        raise ErrorValidacion("El Task de respuesta debe estar en accepted o rejected")
    rid = task.get("id")
    if rid is not None and (not isinstance(rid, str) or not PATRON_ID.match(rid)):
        raise ErrorValidacion("El Task tiene un id FHIR inválido")
    referencias = [_ref(task, "focus")]
    referencias += [b.get("reference") for b in task.get("basedOn") or [] if isinstance(b, dict)]
    referencias = [r for r in referencias if isinstance(r, str) and r]
    if not referencias and not rid:
        raise ErrorValidacion("El Task debe identificar la remisión (id, focus o basedOn)")
    motivo = ""
    if isinstance(task.get("statusReason"), dict):
        motivo = _nombre_concepto(task["statusReason"])
    if not motivo and isinstance(task.get("businessStatus"), dict):
        motivo = _nombre_concepto(task["businessStatus"])
    return {"estado": ESTADO_SOCIO[task["status"]], "task_id": rid,
            "referencias": referencias, "motivo": _texto(motivo, 500) or None}


def _corresponde(envio_id_remision: int, datos: dict) -> bool:
    from routers.remisiones_fhir_r30 import _id_fhir
    task_id = _id_fhir("task", envio_id_remision)
    sr_id = _id_fhir("ref", envio_id_remision)
    if datos["task_id"] == task_id:
        return True
    for referencia in datos["referencias"]:
        m = PATRON_REF.search(referencia)
        if m and ((m.group(1) == "ServiceRequest" and m.group(2) == sr_id)
                  or (m.group(1) == "Task" and m.group(2) == task_id)):
            return True
    return False


def procesar_respuesta(db, inst: dict, crudo: bytes, content_type: str | None,
                       ip: str | None) -> JSONResponse:
    client_id = inst["client_id"]
    try:
        if not _content_type_valido(content_type):
            raise ErrorValidacion("Content-Type debe ser application/fhir+json", 415, "not-supported")
        if len(crudo) > MAX_BYTES_TASK:
            raise ErrorValidacion("El Task supera el tamaño máximo (64 KB)", 413, "too-costly")
        try:
            task = json.loads(crudo)
        except (ValueError, RecursionError):
            raise ErrorValidacion("El cuerpo no es JSON válido", 400, "structure")
        datos = validar_task_respuesta(task)
    except ErrorValidacion as error:
        registrar_rechazo(db, inst, error, ip)
        return rechazo(error.status, error.mensaje, error.codigo)

    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        # Solo las remisiones que enviamos A ESTA institución: otra no puede responderlas.
        cur.execute("""
            SELECT e.id_envio, e.id_remision, e.remitido_por, e.respuesta_socio, r.id_paciente
            FROM r30_envios e JOIN remisiones r ON r.id_remision = e.id_remision
            WHERE e.socio = %s AND e.estado = 'confirmado'
            ORDER BY e.fecha_hora DESC
            LIMIT 500;
        """, (client_id,))
        envio = next((f for f in cur.fetchall() if _corresponde(f["id_remision"], datos)), None)
        if not envio:
            error = ErrorValidacion("No hay una remisión enviada a esta institución que corresponda "
                                    "a este Task", 404, "not-found")
            registrar_rechazo(db, inst, error, ip, notificar=False)
            return rechazo(error.status, error.mensaje, error.codigo)
        cur.execute("SELECT respuesta_socio FROM r30_envios WHERE id_envio = %s FOR UPDATE;",
                    (envio["id_envio"],))
        actual = cur.fetchone()["respuesta_socio"]
        if actual == datos["estado"]:
            db.rollback()     # reintento del socio: misma respuesta, nada que hacer
            return JSONResponse(status_code=200, content=task, media_type="application/fhir+json")
        if actual is not None:
            error = ErrorValidacion(f"La remisión ya fue {actual} por el socio", 409, "conflict")
            registrar_rechazo(db, inst, error, ip, notificar=False)
            return rechazo(error.status, error.mensaje, error.codigo)
        cur.execute("""
            UPDATE r30_envios
            SET respuesta_socio = %s, respuesta_motivo = %s, respuesta_at = now(),
                respuesta_client_id = %s
            WHERE id_envio = %s;
        """, (datos["estado"], datos["motivo"], client_id, envio["id_envio"]))
        auditar_externo(cur, "r30_envios", envio["id_remision"], "RESPUESTA_SOCIO", {
            "client_id": client_id, "institucion": inst.get("nombre"),
            "estado": datos["estado"], "motivo": datos["motivo"],
            "task_id": datos["task_id"], "ip": ip,
        })
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()

    try:
        verbo = "aceptó" if datos["estado"] == "aceptada" else "rechazó"
        mensaje = f"{inst.get('nombre') or client_id} {verbo} la remisión #{envio['id_remision']}"
        if datos["motivo"]:
            mensaje += f": {datos['motivo'][:200]}"
        publicar(db, [envio["remitido_por"]],
                 tipo=f"remision_socio_{datos['estado']}",
                 mensaje=mensaje, paciente_id=envio["id_paciente"],
                 datos={"remision_id": envio["id_remision"], "institucion": inst.get("nombre"),
                        "estado": datos["estado"], "motivo": datos["motivo"]})
    except Exception:
        db.rollback()
        log.exception("Respuesta del socio guardada, pero no se pudo notificar al médico")

    return JSONResponse(status_code=200, content=task, media_type="application/fhir+json")


@router.post("/fhir/remisiones-r30/respuesta")
async def recibir_respuesta_socio(
    request: Request,
    inst=Depends(requerir_institucion("task:write", exigir_nonce=True)),
    db=Depends(get_db),
):
    """El socio acepta o rechaza una remisión que le enviamos (Task accepted/rejected)."""
    crudo = await request.body()
    return await run_in_threadpool(
        procesar_respuesta, db, inst, crudo,
        request.headers.get("content-type"), ip_cliente(request))
