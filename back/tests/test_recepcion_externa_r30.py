"""Pruebas del receptor de remisiones externas (R29, R30, R32).

No usan Neon, HAPI ni la red: la base y HAPI se reemplazan por dobles que
registran lo que se les pide. El "socio" de las pruebas es el Bundle que arma
el propio emisor del proyecto (routers/remisiones_fhir_r30.construir_bundle),
así se comprueba además que nuestro emisor y nuestro receptor encajan.

    cd back && python -m pytest tests/test_recepcion_externa_r30.py -q
"""
import copy
import json
from datetime import datetime, timezone

import pytest
import requests

from routers import recepcion_externa as rx
from routers import remisiones_fhir_r30 as r30

INST = {"client_id": "socio-demo", "nombre": "Institución de demostración",
        "scopes": ["bundle:write", "task:write"]}
FHIR_JSON = "application/fhir+json"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("R30_IDENTIFICADOR_SECRETO", "prueba-local-no-real-" * 3)
    monkeypatch.delenv("R30_EXIGIR_CONSENT", raising=False)


def bundle_natalia() -> dict:
    """Bundle tal como lo envía nuestro emisor R30 (6 recursos)."""
    ahora = datetime(2026, 11, 13, tzinfo=timezone.utc)
    rem = {"id_paciente": 9900000196, "id_remision": 10, "fecha_remision": ahora,
           "motivo": "Dolor torácico opresivo de 2 horas", "especialidad": "Cardiología"}
    obs = [{"id_observacion": 5, "codigo_loinc": "8867-4", "nombre": "Frecuencia cardiaca",
            "valor_numerico": 112, "unidad": "/min"}]
    reps = [{"id_reporte": 3, "estado": "aprobado", "categoria": "alto", "revisado_at": ahora}]
    consentimiento = {"vigente": True, "actualizado_at": ahora, "expira_at": None}
    return r30.construir_bundle(rem, obs, reps, consentimiento)


def bundle_generico() -> dict:
    """Bundle de otro equipo: POST con urn:uuid, sin ids, con nombre y performerType."""
    pac, sr, obs = "urn:uuid:11111111-1111-4111-8111-111111111111", \
        "urn:uuid:22222222-2222-4222-8222-222222222222", \
        "urn:uuid:33333333-3333-4333-8333-333333333333"
    con, task = "urn:uuid:44444444-4444-4444-8444-444444444444", \
        "urn:uuid:55555555-5555-4555-8555-555555555555"
    return {"resourceType": "Bundle", "type": "transaction", "entry": [
        {"fullUrl": pac, "request": {"method": "POST", "url": "Patient"},
         "resource": {"resourceType": "Patient", "name": [{"given": ["Ana"], "family": "Pérez"}],
                      "gender": "female", "birthDate": "1980-04-02",
                      "text": {"status": "generated", "div": "<div><script>alert(1)</script></div>"}}},
        {"fullUrl": sr, "request": {"method": "POST", "url": "ServiceRequest"},
         "resource": {"resourceType": "ServiceRequest", "status": "active", "intent": "order",
                      "priority": "urgent", "subject": {"reference": pac},
                      "requester": {"reference": "Practitioner/medico-del-socio"},
                      "code": {"coding": [{"system": rx.SNOMED, "code": "306206005"}]},
                      "performerType": {"text": "cardiologia"},
                      "reasonCode": [{"text": "Dolor torácico"}]}},
        {"fullUrl": obs, "request": {"method": "POST", "url": "Observation"},
         "resource": {"resourceType": "Observation", "status": "final", "subject": {"reference": pac},
                      "code": {"coding": [{"system": rx.LOINC, "code": "59408-5", "display": "SpO2"}]},
                      "valueQuantity": {"value": 91, "unit": "%"}}},
        {"fullUrl": con, "request": {"method": "POST", "url": "Consent"},
         "resource": {"resourceType": "Consent", "status": "active", "patient": {"reference": pac},
                      "provision": {"type": "permit"}}},
        {"fullUrl": task, "request": {"method": "POST", "url": "Task"},
         "resource": {"resourceType": "Task", "status": "requested", "intent": "order",
                      "focus": {"reference": sr}, "for": {"reference": pac}}},
    ]}


def recurso(bundle: dict, tipo: str) -> dict:
    return next(e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == tipo)


# =====================================================================
# Validación
# =====================================================================

def test_acepta_el_bundle_de_nuestro_emisor():
    v = rx.validar_bundle_entrante(bundle_natalia())
    assert v.entradas[v.solicitud].tipo == "ServiceRequest"
    assert v.tarea is not None and v.consentimiento is not None


def test_acepta_bundle_generico_con_urn_uuid():
    v = rx.validar_bundle_entrante(bundle_generico())
    assert v.entradas[v.paciente].clave.startswith("urn:uuid:")


@pytest.mark.parametrize("cambio, mensaje", [
    (lambda b: b.update(resourceType="Patient"), "Bundle"),
    (lambda b: b.update(type="batch"), "transaction o collection"),
    (lambda b: b.update(entry=b["entry"][:1]), "entre 2"),
    (lambda b: b["entry"].append({"resource": {"resourceType": "Subscription", "id": "x"},
                                  "request": {"method": "PUT", "url": "Subscription/x"}}), "no permitido"),
    (lambda b: b["entry"][0]["request"].update(method="DELETE"), "DELETE"),
    (lambda b: b["entry"][0]["request"].update(url="Patient/otro-id"), "no coincide"),
    (lambda b: recurso(b, "Observation")["code"]["coding"][0].update(system="http://otro"), "LOINC"),
    (lambda b: recurso(b, "Observation").update(status="preliminary"), "estado"),
    (lambda b: recurso(b, "Observation")["subject"].update(reference="Patient/otro"), "Patient del Bundle"),
    (lambda b: recurso(b, "DiagnosticReport").update(status="preliminary"), "aprobados"),
    (lambda b: recurso(b, "ServiceRequest").update(status="draft"), "activo"),
    (lambda b: recurso(b, "ServiceRequest").update(code={"text": "sin código"}), "SNOMED"),
    (lambda b: recurso(b, "Consent").update(status="inactive"), "Consent"),
    (lambda b: recurso(b, "Consent")["provision"].update(type="deny"), "permit"),
    (lambda b: recurso(b, "Consent")["provision"].update(period={"end": "2020-01-01T00:00:00Z"}), "vencido"),
    (lambda b: recurso(b, "Task")["focus"].update(reference="ServiceRequest/otra"), "Task"),
    (lambda b: recurso(b, "Task").update(status="accepted"), "requested"),
    (lambda b: b["entry"].append(copy.deepcopy(b["entry"][0])), "repetido"),
])
def test_rechaza_bundles_invalidos(cambio, mensaje):
    b = bundle_natalia()
    cambio(b)
    with pytest.raises(rx.ErrorValidacion, match=mensaje):
        rx.validar_bundle_entrante(b)


def test_exige_consent_salvo_que_se_desactive(monkeypatch):
    b = bundle_natalia()
    b["entry"] = [e for e in b["entry"] if e["resource"]["resourceType"] != "Consent"]
    with pytest.raises(rx.ErrorValidacion, match="Consent"):
        rx.validar_bundle_entrante(b)
    rx.validar_bundle_entrante(b, exigir_consentimiento=False)


def test_rechaza_json_anidado_a_proposito():
    b = bundle_natalia()
    profundo = {}
    actual = profundo
    for _ in range(60):
        actual["x"] = {}
        actual = actual["x"]
    recurso(b, "Patient")["extension"] = [profundo]
    with pytest.raises(rx.ErrorValidacion, match="anidado"):
        rx.validar_bundle_entrante(b)


# =====================================================================
# Reescritura para HAPI
# =====================================================================

def test_reescribe_ids_y_referencias_del_socio():
    original = bundle_natalia()
    tx, mapa = rx.reescribir_para_hapi(rx.validar_bundle_entrante(original), "socio-demo")
    texto = json.dumps(tx)
    for e in original["entry"]:
        assert e["resource"]["id"] not in texto          # ningún id del socio llega a HAPI
    locales = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in tx["entry"]}
    assert all(e["resource"]["id"].startswith("ext-") for e in tx["entry"])
    assert all(e["request"] == {"method": "PUT", "url": f"{e['resource']['resourceType']}/{e['resource']['id']}"}
               for e in tx["entry"])
    # Todas las referencias internas apuntan a recursos del mismo Bundle.
    pac = recurso(tx, "Patient")
    assert recurso(tx, "Observation")["subject"]["reference"] == f"Patient/{pac['id']}"
    assert recurso(tx, "Task")["focus"]["reference"] in locales
    assert set(mapa.values()) == locales
    assert recurso(tx, "Patient")["meta"]["tag"][0]["code"] == "socio-demo"


def test_ids_estables_por_socio_y_distintos_entre_socios():
    v = rx.validar_bundle_entrante(bundle_natalia())
    _, a = rx.reescribir_para_hapi(v, "socio-demo")
    _, b = rx.reescribir_para_hapi(v, "socio-demo")
    _, c = rx.reescribir_para_hapi(v, "otro-socio")
    assert a == b and a != c


def test_referencia_externa_queda_como_texto_y_se_quita_narrativo():
    tx, _ = rx.reescribir_para_hapi(rx.validar_bundle_entrante(bundle_generico()), "socio-demo")
    sr = recurso(tx, "ServiceRequest")
    assert "reference" not in sr["requester"]
    assert "medico-del-socio" in sr["requester"]["display"]
    assert "text" not in recurso(tx, "Patient")
    assert recurso(tx, "Task")["focus"]["reference"] == f"ServiceRequest/{sr['id']}"


# =====================================================================
# Resumen y especialidad
# =====================================================================

class CursorCatalogo:
    def execute(self, sql, params=None):
        self.sql = sql

    def fetchall(self):
        return [{"id_especialidad": 8, "nombre": "Cardiología"},
                {"id_especialidad": 9, "nombre": "Neurología"},
                {"id_especialidad": 2, "nombre": "Medicina General"}]


def test_resumen_y_especialidad_desde_la_nota_de_natalia():
    datos = rx.extraer_resumen(rx.validar_bundle_entrante(bundle_natalia()))
    assert datos["especialidad_texto"] == "Cardiología"
    assert "Dolor torácico" in datos["motivo"]
    assert datos["resumen"]["observaciones"][0]["loinc"] == "8867-4"
    assert datos["resumen"]["reportes"][0]["estado"] == "final"
    assert datos["resumen"]["consentimiento"]["estado"] == "active"
    assert datos["resumen"]["paciente"]["nombre"] is None     # el emisor no manda nombre


def test_resumen_generico_con_performer_type_y_nombre():
    datos = rx.extraer_resumen(rx.validar_bundle_entrante(bundle_generico()))
    assert datos["especialidad_texto"] == "cardiologia"
    assert datos["prioridad"] == "urgent"
    assert datos["resumen"]["paciente"]["nombre"] == "Ana Pérez"


@pytest.mark.parametrize("texto, esperado", [
    ("Cardiología", 8), ("CARDIOLOGIA", 8), ("cardiologia ", 8), ("Neurologia clínica", 9),
    ("Dermatología", None), ("", None), (None, None),
])
def test_mapea_especialidad_sin_tildes_ni_mayusculas(texto, esperado):
    assert rx.mapear_especialidad(CursorCatalogo(), texto) == esperado


# =====================================================================
# Proceso completo con base y HAPI falsos
# =====================================================================

class CursorFalso:
    def __init__(self, db):
        self.db = db
        self.ultimo = None

    def execute(self, sql, params=None):
        self.db.sql.append((" ".join(sql.split()), params))
        self.ultimo = sql

    def fetchone(self):
        s = self.ultimo
        if "FROM remisiones_externas" in s and "SELECT id_remision_externa" in s:
            return {"id_remision_externa": 99} if self.db.duplicada else None
        if "INSERT INTO remisiones_externas" in s:
            return {"id_remision_externa": 7, "fecha_recepcion": datetime.now(timezone.utc)}
        if "SELECT nombre FROM especialidades" in s:
            return {"nombre": "Cardiología"}
        return None

    def fetchall(self):
        s = self.ultimo
        if "FROM especialidades" in s:
            return CursorCatalogo().fetchall()
        if "usuario_especialidades" in s:
            return [{"numero_documento_usuario": 1000000101}]
        return []

    def close(self):
        pass


class BaseFalsa:
    def __init__(self, duplicada=False):
        self.sql, self.commits, self.rollbacks = [], 0, 0
        self.duplicada = duplicada

    def cursor(self, cursor_factory=None):
        return CursorFalso(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def acciones(self):
        return [p[2] for s, p in self.sql if "INSERT INTO auditoria_cambios" in s]

    def inserto_remision(self):
        return any("INSERT INTO remisiones_externas" in s for s, _ in self.sql)


class Hapi:
    def __init__(self, status=200, cuerpo=None, falla=False):
        self.llamadas, self.status, self.cuerpo, self.falla = [], status, cuerpo, falla

    def post(self, url, json, timeout, headers):
        self.llamadas.append(json)
        if self.falla:
            raise requests.ConnectionError("HAPI caído")
        hapi = self

        class Respuesta:
            status_code = hapi.status

            def json(self):
                if hapi.cuerpo is not None:
                    return hapi.cuerpo
                return {"resourceType": "Bundle", "type": "transaction-response",
                        "entry": [{"response": {"status": "201 Created"}} for _ in json["entry"]]}
        return Respuesta()



@pytest.fixture
def avisos(monkeypatch):
    enviados = []
    monkeypatch.setattr(rx, "publicar", lambda db, dest, **k: enviados.append((list(dest), k)))
    monkeypatch.setattr(rx, "usuarios_por_rol", lambda db, *roles: [1171644825])
    monkeypatch.setattr(rx, "_hapi_url", lambda: "http://hapi-fhir:8080/fhir")
    return enviados


def procesar(db, hapi, cuerpo, content_type=FHIR_JSON):
    crudo = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
    return rx.procesar_recepcion(db, INST, crudo, content_type, "203.0.113.5",
                                 hapi_post=hapi.post)


def cuerpo(respuesta) -> dict:
    return json.loads(respuesta.body)


def test_bundle_valido_se_guarda_audita_y_avisa(avisos):
    db, hapi = BaseFalsa(), Hapi()
    r = procesar(db, hapi, bundle_natalia())
    assert r.status_code == 200
    assert cuerpo(r)["type"] == "transaction-response"
    assert r.headers["X-Remision-Externa"] == "7"
    assert len(hapi.llamadas) == 1 and hapi.llamadas[0]["type"] == "transaction"
    assert db.inserto_remision() and db.commits >= 1
    assert db.acciones() == ["RECIBIR_REMISION_EXTERNA"]
    assert all("'SOCIO'" in s for s, _ in db.sql if "INSERT INTO auditoria_cambios" in s)
    destinatarios, aviso = avisos[0]
    assert destinatarios == [1000000101]                   # el cardiólogo
    assert aviso["tipo"] == "remision_externa_recibida"


@pytest.mark.parametrize("crudo, content_type, status", [
    (b"{no es json", FHIR_JSON, 400),
    (json.dumps({"resourceType": "Bundle", "type": "batch", "entry": []}).encode(), FHIR_JSON, 422),
    (b"{}", "text/plain", 415),
    (b" " * (rx.MAX_BYTES + 1), FHIR_JSON, 413),
])
def test_entrada_invalida_no_escribe_nada_y_queda_auditada(avisos, crudo, content_type, status):
    db, hapi = BaseFalsa(), Hapi()
    r = procesar(db, hapi, crudo, content_type)
    assert r.status_code == status
    assert cuerpo(r)["resourceType"] == "OperationOutcome"
    assert hapi.llamadas == []                             # HAPI no recibe nada
    assert not db.inserto_remision()
    assert db.acciones() == ["RECHAZO_VALIDACION_EXTERNA"]
    assert avisos and avisos[0][1]["tipo"] == "remision_externa_invalida"


def test_hapi_rechaza_y_no_queda_la_remision(avisos):
    db = BaseFalsa()
    hapi = Hapi(status=400, cuerpo={"resourceType": "OperationOutcome",
                                    "issue": [{"severity": "error", "diagnostics": "Unknown code"}]})
    r = procesar(db, hapi, bundle_natalia())
    assert r.status_code == 422
    assert "Unknown code" in cuerpo(r)["issue"][0]["diagnostics"]
    # Se insertó dentro de la transacción, pero se deshizo antes de confirmar.
    assert db.rollbacks >= 1
    assert db.acciones()[-1] == "RECHAZO_VALIDACION_EXTERNA"


def test_hapi_confirma_parcialmente_y_se_rechaza(avisos):
    db = BaseFalsa()
    hapi = Hapi(cuerpo={"resourceType": "Bundle", "type": "transaction-response",
                        "entry": [{"response": {"status": "201 Created"}}]})
    r = procesar(db, hapi, bundle_natalia())
    assert r.status_code == 502


def test_hapi_caido_responde_503(avisos):
    r = procesar(BaseFalsa(), Hapi(falla=True), bundle_natalia())
    assert r.status_code == 503


def test_remision_repetida_responde_409_sin_tocar_hapi(avisos):
    db, hapi = BaseFalsa(duplicada=True), Hapi()
    r = procesar(db, hapi, bundle_natalia())
    assert r.status_code == 409
    assert cuerpo(r)["issue"][0]["code"] == "duplicate"
    assert hapi.llamadas == []
    assert avisos == []                                    # un reintento no molesta al Admin


def test_si_la_base_falla_despues_de_hapi_se_compensa(avisos):
    db, hapi = BaseFalsa(), Hapi()

    def commit_que_falla():
        raise RuntimeError("se cayó la conexión")
    db.commit = commit_que_falla
    with pytest.raises(RuntimeError):
        procesar(db, hapi, bundle_natalia())
    # Segunda llamada a HAPI: una sola transacción que borra los 6 recursos guardados.
    assert len(hapi.llamadas) == 2
    deshacer = hapi.llamadas[1]
    assert deshacer["type"] == "transaction" and len(deshacer["entry"]) == 6
    assert {e["request"]["method"] for e in deshacer["entry"]} == {"DELETE"}


# =====================================================================
# Autenticación (R29 + R31): la ruta exige token institucional
# =====================================================================

@pytest.fixture
def cliente(monkeypatch):
    # App mínima con solo este router: no carga main.py (que conecta a MongoDB,
    # Orthanc, etc.), así la prueba corre igual dentro y fuera de Docker.
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.database import get_db
    app = FastAPI()
    app.include_router(rx.router)
    monkeypatch.setenv("INSTITUCION_JWT_SECRET", "secreto-institucional-de-prueba-" * 2)
    app.dependency_overrides[get_db] = lambda: BaseFalsa()   # no toca Neon
    return TestClient(app)


@pytest.mark.parametrize("cabeceras", [
    {},                                                      # sin credenciales
    {"X-R30-Token": "el-token-viejo-ya-no-sirve"},           # receptor piloto anterior
    {"Authorization": "Bearer token.que.no.es.valido"},      # token alterado o de otra llave
])
def test_ruta_rechaza_sin_credenciales_institucionales(cliente, cabeceras):
    r = cliente.post("/fhir/remisiones-r30/recibir", content=json.dumps(bundle_natalia()),
                     headers={"Content-Type": FHIR_JSON, "x-nonce": "n" * 20, **cabeceras})
    assert r.status_code == 401


def test_el_receptor_viejo_con_token_compartido_ya_no_existe():
    assert not hasattr(r30, "recibir")
