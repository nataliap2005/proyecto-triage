"""R29 · R30: prueba de punta a punta del receptor de remisiones externas.

Actúa como si fuera la institución socio: pide un token (R31), envía Bundles
válidos e inválidos y comprueba que cada uno reciba la respuesta esperada.
No importa nada del proyecto: se puede correr desde cualquier equipo.

Uso (desde back/):
    python scripts/prueba_recepcion_externa.py http://localhost:8000 socio-demo <client_secret>
    python scripts/prueba_recepcion_externa.py https://<tunel>.trycloudflare.com/api socio-demo <client_secret>

La primera URL es la base de la API (con /api si se pasa por Nginx o Cloudflare).
Necesita HAPI FHIR arriba para el caso válido. Cada corrida usa ids nuevos,
así que se puede repetir sin chocar con la anterior.

El client_secret se pasa por argumento y no se imprime: no lo guarde en el repo.
"""
import copy
import json
import secrets
import sys
import uuid

import requests

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
FHIR_JSON = "application/fhir+json"


def urn() -> str:
    return f"urn:uuid:{uuid.uuid4()}"


def bundle_valido() -> dict:
    """Remisión sintética, como la armaría un equipo socio cualquiera."""
    pac, sr, obs1, obs2, rep, con, task = (urn() for _ in range(7))
    paciente = {"reference": pac}
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        {"fullUrl": pac, "request": {"method": "POST", "url": "Patient"},
         "resource": {"resourceType": "Patient", "gender": "female", "birthDate": "1979-05-14",
                      "name": [{"text": "Paciente Sintética Prueba"}]}},
        {"fullUrl": sr, "request": {"method": "POST", "url": "ServiceRequest"},
         "resource": {"resourceType": "ServiceRequest", "status": "active", "intent": "order",
                      "priority": "urgent", "subject": paciente,
                      "code": {"coding": [{"system": SNOMED, "code": "306206005",
                                           "display": "Referral to service"}]},
                      "performerType": {"text": "Cardiología"},
                      "reasonCode": [{"text": "Dolor torácico opresivo de 2 horas (dato sintético)"}]}},
        {"fullUrl": obs1, "request": {"method": "POST", "url": "Observation"},
         "resource": {"resourceType": "Observation", "status": "final", "subject": paciente,
                      "code": {"coding": [{"system": LOINC, "code": "8867-4", "display": "Heart rate"}]},
                      "valueQuantity": {"value": 112, "unit": "/min", "system": "http://unitsofmeasure.org",
                                        "code": "/min"}}},
        {"fullUrl": obs2, "request": {"method": "POST", "url": "Observation"},
         "resource": {"resourceType": "Observation", "status": "final", "subject": paciente,
                      "code": {"coding": [{"system": LOINC, "code": "59408-5",
                                           "display": "Oxygen saturation"}]},
                      "valueQuantity": {"value": 91, "unit": "%", "system": "http://unitsofmeasure.org",
                                        "code": "%"}}},
        {"fullUrl": rep, "request": {"method": "POST", "url": "DiagnosticReport"},
         "resource": {"resourceType": "DiagnosticReport", "status": "final", "subject": paciente,
                      "code": {"text": "Evaluación de apoyo mediante IA, aprobada por profesional"},
                      "conclusion": "Categoría revisada: alto"}},
        {"fullUrl": con, "request": {"method": "POST", "url": "Consent"},
         "resource": {"resourceType": "Consent", "status": "active", "patient": paciente,
                      "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                                            "code": "patient-privacy"}]},
                      "category": [{"coding": [{"system": LOINC, "code": "59284-0"}]}],
                      "policyRule": {"text": "Ley 1581 de 2012"},
                      "provision": {"type": "permit"}}},
        {"fullUrl": task, "request": {"method": "POST", "url": "Task"},
         "resource": {"resourceType": "Task", "status": "requested", "intent": "order",
                      "focus": {"reference": sr}, "for": paciente}},
    ]}


def sin(bundle: dict, tipo: str) -> dict:
    b = copy.deepcopy(bundle)
    b["entry"] = [e for e in b["entry"] if e["resource"]["resourceType"] != tipo]
    return b


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    base, client_id, client_secret = sys.argv[1].rstrip("/"), sys.argv[2], sys.argv[3]
    recibir = f"{base}/fhir/remisiones-r30/recibir"
    resultados = []

    def caso(nombre, esperado, respuesta):
        try:
            cuerpo = respuesta.json()
        except ValueError:
            cuerpo = {}
        detalle = ""
        if isinstance(cuerpo, dict) and cuerpo.get("resourceType") == "OperationOutcome":
            detalle = (cuerpo.get("issue") or [{}])[0].get("diagnostics", "")
        elif isinstance(cuerpo, dict) and "detail" in cuerpo:
            detalle = str(cuerpo["detail"])
        elif respuesta.headers.get("X-Remision-Externa"):
            detalle = f"remisión externa #{respuesta.headers['X-Remision-Externa']}"
        ok = respuesta.status_code == esperado
        resultados.append(ok)
        print(f"[{'OK ' if ok else 'FALLA'}] {nombre:<46} esperado {esperado}  recibido "
              f"{respuesta.status_code}  {detalle[:90]}")

    def enviar(bundle, token, nonce=None, content_type=FHIR_JSON):
        cabeceras = {"Content-Type": content_type, "Accept": FHIR_JSON,
                     "x-nonce": nonce or secrets.token_urlsafe(24)}
        if token:
            cabeceras["Authorization"] = f"Bearer {token}"
        datos = bundle if isinstance(bundle, (bytes, str)) else json.dumps(bundle)
        return requests.post(recibir, data=datos, headers=cabeceras, timeout=40)

    valido = bundle_valido()
    caso("Sin token institucional", 401, enviar(valido, None))

    r = requests.post(f"{base}/oauth/token", timeout=20, data={
        "grant_type": "client_credentials", "client_id": client_id, "client_secret": client_secret})
    if r.status_code != 200:
        print(f"No se obtuvo token: HTTP {r.status_code} {r.text[:200]}")
        return 1
    token = r.json()["access_token"]
    print(f"Token institucional obtenido (vigencia {r.json().get('expires_in')} s, "
          f"permisos: {r.json().get('scope')})")

    caso("Token alterado", 401, enviar(valido, token[:-4] + "AAAA"))
    caso("Content-Type que no es FHIR", 415, enviar(valido, token, content_type="text/plain"))
    caso("Cuerpo que no es JSON", 400, enviar("{esto no es json", token))
    malo = copy.deepcopy(valido)
    malo["entry"][2]["resource"]["code"]["coding"][0]["system"] = "http://no-es-loinc"
    caso("Observation sin código LOINC", 422, enviar(malo, token))
    reporte = copy.deepcopy(valido)
    reporte["entry"][4]["resource"]["status"] = "preliminary"
    caso("DiagnosticReport no aprobado", 422, enviar(reporte, token))
    caso("Sin Consent del paciente (R32)", 422, enviar(sin(valido, "Consent"), token))
    peligroso = copy.deepcopy(valido)
    peligroso["entry"].append({"resource": {"resourceType": "Subscription", "id": "robo"},
                               "request": {"method": "PUT", "url": "Subscription/robo"}})
    caso("Intenta crear una Subscription en HAPI", 422, enviar(peligroso, token))
    borrar = copy.deepcopy(valido)
    borrar["entry"][0]["request"] = {"method": "DELETE", "url": "Patient/paciente-1"}
    caso("Intenta borrar un Patient propio", 422, enviar(borrar, token))

    nonce = secrets.token_urlsafe(24)
    caso("Bundle válido", 200, enviar(valido, token, nonce))
    caso("Mismo x-nonce otra vez (repetición)", 409, enviar(valido, token, nonce))
    caso("Misma remisión con nonce nuevo (duplicado)", 409, enviar(valido, token))

    print(f"\n{sum(resultados)} de {len(resultados)} casos con la respuesta esperada.")
    return 0 if all(resultados) else 1


if __name__ == "__main__":
    sys.exit(main())
