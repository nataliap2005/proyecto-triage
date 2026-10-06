"""Prueba de R21: una Observation nueva en HAPI FHIR notifica al médico responsable.
Uso: python prueba_fhir.py <medico_responsable> <cuenta_paciente> <documento_paciente>
"""
import getpass
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from utilidades_prueba import Canal, api, entrar, verificar

FHIR = "http://localhost:8080/fhir"   # HAPI directo, como un sistema externo


def fhir(metodo, ruta, cuerpo=None):
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(FHIR + ruta, data=datos, method=metodo)
    peticion.add_header("Accept", "application/fhir+json")
    if datos is not None:
        peticion.add_header("Content-Type", "application/fhir+json")
    try:
        with urllib.request.urlopen(peticion, timeout=30) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None


medico, cuenta_paciente, documento = sys.argv[1], sys.argv[2], int(sys.argv[3])
t_medico = entrar(medico, getpass.getpass(f"Clave de {medico}: "))
t_paciente = entrar(cuenta_paciente, getpass.getpass(f"Clave de {cuenta_paciente}: "))

# --- La Subscription existe y está activa ---
estado, sus = fhir("GET", "/Subscription/triaje-observaciones")
verificar("La Subscription existe en HAPI", estado == 200, estado)
if estado == 200:
    verificar("La Subscription está activa", sus.get("status") == "active", sus.get("status"))

# --- El Patient existe en HAPI (lo sincroniza la API, como ya hacía fhir.py) ---
estado, _ = api("PUT", f"/fhir/pacientes/{documento}", t_medico)
verificar("El paciente está sincronizado en HAPI", estado == 200, estado)

canal_medico = Canal(t_medico, medico)
canal_paciente = Canal(t_paciente, cuenta_paciente)

# --- Un "laboratorio externo" publica una glucosa en HAPI ---
observacion = {
    "resourceType": "Observation",
    "status": "final",
    "category": [{"coding": [{
        "system": "http://terminology.hl7.org/CodeSystem/observation-category",
        "code": "laboratory"}]}],
    "code": {
        "coding": [{"system": "http://loinc.org", "code": "2339-0",
                    "display": "Glucose [Mass/volume] in Blood"}],
        "text": "Glucosa en sangre"},
    "subject": {"reference": f"Patient/paciente-{documento}"},
    "effectiveDateTime": datetime.now(timezone.utc).isoformat(),
    "valueQuantity": {"value": 250, "unit": "mg/dL",
                      "system": "http://unitsofmeasure.org", "code": "mg/dL"},
}
inicio = time.time()
estado, creada = fhir("POST", "/Observation", observacion)
verificar("HAPI acepta la Observation (201)", estado == 201, estado if estado != 201 else "")
fhir_id_obs = str((creada or {}).get("id"))

de_esta = lambda e: e.get("tipo") == "observacion_fhir" and str(e.get("fhir_id")) == fhir_id_obs
evento, momento = canal_medico.esperar(de_esta, segundos=20)
verificar("El médico responsable recibe 'observacion_fhir'", evento is not None)
if evento:
    print(f"       llegó en {momento - inicio:.2f} s")
    print(f"       {evento['mensaje']}")
    verificar("El evento trae paciente_id", evento.get("paciente_id") == documento)

time.sleep(2)
verificar("El paciente NO recibe el aviso por su canal",
          not canal_paciente.recibio(lambda e: str(e.get("fhir_id")) == fhir_id_obs))
print(f"\nPara ver la auditoría: registro_id = '{fhir_id_obs}' en auditoria_cambios")