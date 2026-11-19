"""R29: el webhook de la Subscription de HAPI rechaza sin secreto y valida el recurso.

    cd back && python -m pytest tests/test_fhir_hook_r29.py -q
"""
import copy
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers import fhir_suscripcion as hook

TOKEN = "token-del-hook-de-prueba-1234567890"

OBS = {"resourceType": "Observation", "id": "lab-1", "status": "final",
       "code": {"coding": [{"system": "http://loinc.org", "code": "8867-4"}]},
       "subject": {"reference": "Patient/paciente-9900000196"},
       "valueQuantity": {"value": 118, "unit": "/min"}}


@pytest.fixture
def cliente(monkeypatch):
    procesadas = []
    monkeypatch.setattr(hook, "FHIR_HOOK_TOKEN", TOKEN)
    monkeypatch.setattr(hook, "procesar_observation", lambda obs: procesadas.append(obs["id"]))
    app = FastAPI()
    app.include_router(hook.router)
    c = TestClient(app)
    c.procesadas = procesadas
    return c


def enviar(c, cuerpo, token=TOKEN):
    datos = cuerpo if isinstance(cuerpo, (bytes, str)) else json.dumps(cuerpo)
    return c.post("/fhir-hook", content=datos, headers={
        "Content-Type": "application/fhir+json", **({"X-Triaje-Token": token} if token else {})})


def test_sin_token_o_token_falso_responde_401(cliente):
    assert enviar(cliente, OBS, token=None).status_code == 401
    assert enviar(cliente, OBS, token="otro").status_code == 401
    assert cliente.procesadas == []


def test_observation_valida_se_procesa(cliente):
    r = enviar(cliente, OBS)
    assert r.status_code == 200 and cliente.procesadas == ["lab-1"]


def test_cuerpo_vacio_es_la_prueba_de_canal_de_hapi(cliente):
    assert enviar(cliente, b"").status_code == 200


@pytest.mark.parametrize("cambio, mensaje", [
    (lambda o: o.update(resourceType="Patient"), "Observation"),
    (lambda o: o.pop("id"), "id"),
    (lambda o: o.update(status="borrador"), "estado"),
    (lambda o: o.update(code={"text": "sin código"}), "código"),
    (lambda o: o.update(subject={"reference": "Group/1"}), "paciente"),
    (lambda o: o.update(valueQuantity={"value": "118"}), "numérico"),
])
def test_recurso_invalido_responde_422_sin_procesar(cliente, cambio, mensaje):
    obs = copy.deepcopy(OBS)
    cambio(obs)
    r = enviar(cliente, obs)
    assert r.status_code == 422
    assert r.json()["resourceType"] == "OperationOutcome"
    assert mensaje in r.json()["issue"][0]["diagnostics"]
    assert cliente.procesadas == []


def test_json_roto_y_bundle_con_una_invalida_no_procesa_ninguna(cliente):
    assert enviar(cliente, "{roto").status_code == 400
    mala = copy.deepcopy(OBS)
    mala["id"], mala["status"] = "lab-2", "x"
    bundle = {"resourceType": "Bundle", "type": "history",
              "entry": [{"resource": OBS}, {"resource": mala}]}
    assert enviar(cliente, bundle).status_code == 422
    assert cliente.procesadas == []                         # todo o nada


def test_otro_tipo_de_recurso_se_rechaza(cliente):
    r = enviar(cliente, {"resourceType": "Subscription", "id": "x"})
    assert r.status_code == 422 and cliente.procesadas == []
