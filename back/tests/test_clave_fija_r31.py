"""R31 · modo de clave fija (API key por institución) y compatibilidad de entrada.

No usan base de datos ni red: la base se reemplaza por un doble.
    cd back && python -m pytest tests/test_clave_fija_r31.py -q
"""
import json

import pytest
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from auth import institucional as inst
from core.security import hash_password
from routers import recepcion_externa as rx

CLAVE = "clave-del-socio-de-prueba-no-real-0123456789"
HASH = hash_password(CLAVE)


class Cursor:
    def __init__(self, db):
        self.db, self.fila = db, None

    def execute(self, sql, params=None):
        self.db.sql.append(sql)
        if "secret_hash FROM clientes_institucionales" in sql:
            self.fila = (HASH,) if params[0] in self.db.clientes else None
        elif "nombre, scopes, activo FROM clientes_institucionales" in sql:
            c = self.db.clientes.get(params[0])
            self.fila = None if c is None else {"nombre": "Socio UCI", "scopes": c["scopes"], "activo": c["activo"]}
        elif "INSERT INTO oauth_eventos" in sql:
            self.db.eventos.append(params[1])
        elif "INSERT INTO oauth_nonces" in sql:
            clave = (params[0], params[1])
            self.fila = None if clave in self.db.nonces else (1,)
            self.db.nonces.add(clave)

    def fetchone(self):
        return self.fila

    def close(self):
        pass


class DB:
    def __init__(self, activo=True, scopes=("bundle:write",)):
        self.clientes = {"socio-uci": {"activo": activo, "scopes": list(scopes)}}
        self.sql, self.eventos, self.nonces = [], [], set()

    def cursor(self, cursor_factory=None):
        return Cursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("R30_ENTRADA_CLIENT_ID", "socio-uci")
    monkeypatch.setenv("INSTITUCION_JWT_SECRET", "secreto-institucional-de-prueba-no-real-0123456789")
    monkeypatch.setenv("JWT_SECRET_KEY", "llave-de-usuarios-distinta-de-prueba-0123456789")


def llamar(db, scope="bundle:write", bearer=None, x_system_key=None, x_api_key=None, nonce=None):
    dep = inst.requerir_institucion(scope, exigir_nonce=True)
    cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials=bearer) if bearer else None
    return dep(credenciales=cred, x_nonce=nonce, x_system_key=x_system_key, x_api_key=x_api_key, db=db)


@pytest.mark.parametrize("forma", ["x_system_key", "x_api_key", "bearer"])
def test_clave_valida_entra_sin_token_ni_nonce(forma):
    db = DB()
    r = llamar(db, **{forma: CLAVE})
    assert r["client_id"] == "socio-uci" and r["autenticacion"] == "clave_fija"
    assert "CLAVE_ACEPTADA" in db.eventos


def test_clave_incorrecta_da_401_y_queda_registrada():
    db = DB()
    with pytest.raises(HTTPException) as e:
        llamar(db, x_system_key="otra-clave-cualquiera")
    assert e.value.status_code == 401 and "CLAVE_RECHAZADA" in db.eventos


def test_sin_credencial_da_401():
    with pytest.raises(HTTPException) as e:
        llamar(DB())
    assert e.value.status_code == 401


def test_modo_apagado_rechaza_la_clave(monkeypatch):
    monkeypatch.delenv("R30_ENTRADA_CLIENT_ID")
    with pytest.raises(HTTPException) as e:
        llamar(DB(), x_system_key=CLAVE)
    assert e.value.status_code == 401


def test_institucion_desactivada_revoca_la_clave():
    with pytest.raises(HTTPException) as e:
        llamar(DB(activo=False), x_system_key=CLAVE)
    assert e.value.status_code == 401


def test_clave_respeta_los_permisos_registrados():
    with pytest.raises(HTTPException) as e:
        llamar(DB(scopes=("bundle:write",)), scope="task:write", x_system_key=CLAVE)
    assert e.value.status_code == 403


def test_nonce_opcional_pero_si_llega_se_valida():
    db = DB()
    llamar(db, x_system_key=CLAVE, nonce="nonce-unico-0123456789")
    with pytest.raises(HTTPException) as e:
        llamar(db, x_system_key=CLAVE, nonce="nonce-unico-0123456789")
    assert e.value.status_code == 409


def test_un_jwt_sigue_por_el_camino_de_token():
    # Un Bearer con forma de JWT no se compara como clave: va a la validación OAuth.
    db = DB()
    with pytest.raises(HTTPException) as e:
        llamar(db, bearer="aaa.bbb.ccc")
    assert e.value.status_code == 401 and "TOKEN_RECHAZADO" in db.eventos
    assert not any("secret_hash" in s for s in db.sql)


def test_la_clave_no_abre_la_api_clinica():
    # La API clínica usa el JWT de usuarios; la clave del socio no es un JWT válido allí.
    from auth import service
    with pytest.raises(HTTPException) as e:
        service.usuario_desde_token(CLAVE, DB())
    assert e.value.status_code == 401


# --------------------------- Compatibilidad del Bundle ---------------------------

def bundle_uci() -> dict:
    """Bundle como lo describe el socio: collection, sin request, con security_envelope."""
    return {"resourceType": "Bundle", "type": "collection", "security_envelope": "AES256:xxxx",
            "entry": [
                {"resource": {"resourceType": "Patient", "id": "p1",
                              "identifier": [{"value": "123"}], "name": [{"text": "Ana Pérez"}]}},
                {"resource": {"resourceType": "ServiceRequest", "id": "sr1",
                              "code": {"text": "Remisión a UCI"},
                              "reasonCode": [{"text": "Dolor torácico"}]}},
                {"resource": {"resourceType": "Consent", "id": "c1", "status": "active"}},
                {"resource": {"resourceType": "Observation", "id": "o1",
                              "code": {"coding": [{"system": rx.LOINC, "code": "8867-4"}]},
                              "valueQuantity": {"value": 110, "unit": "/min"}}},
            ]}


def test_bundle_del_socio_se_adapta_y_valida():
    b = rx.adaptar_bundle_socio(bundle_uci())
    assert "security_envelope" not in b
    v = rx.validar_bundle_entrante(b)
    sr = v.entradas[v.solicitud].recurso
    assert sr["status"] == "active" and sr["subject"] == {"reference": "Patient/p1"}
    assert sr["code"]["text"] == "Remisión a UCI"
    assert {"system": rx.SNOMED, "code": "3457005", "display": "Patient referral"} in sr["code"]["coding"]
    assert v.entradas[v.consentimiento].recurso["provision"]["type"] == "permit"
    assert rx.extraer_resumen(v)["motivo"] == "Dolor torácico"


def test_adaptar_no_tapa_valores_invalidos():
    b = bundle_uci()
    b["entry"][2]["resource"]["provision"] = {"type": "deny"}
    with pytest.raises(rx.ErrorValidacion, match="permit"):
        rx.validar_bundle_entrante(rx.adaptar_bundle_socio(b))
    b = bundle_uci()
    b["entry"][3]["resource"]["subject"] = {"reference": "Patient/otro"}
    with pytest.raises(rx.ErrorValidacion, match="Patient del Bundle"):
        rx.validar_bundle_entrante(rx.adaptar_bundle_socio(b))


@pytest.mark.parametrize("cuerpo, cabecera, esperado", [
    ({"resourceType": "Parameters"}, None, True),
    ({"resourceType": "Bundle"}, "true", True),
    ({"resourceType": "Bundle"}, None, False),
])
def test_ping(cuerpo, cabecera, esperado):
    assert rx.es_ping(cuerpo, cabecera) is esperado


def test_ping_responde_200_sin_escribir():
    db = DB()
    r = rx.procesar_recepcion(db, {"client_id": "socio-uci", "nombre": "Socio UCI",
                                   "autenticacion": "clave_fija"},
                              json.dumps({"resourceType": "Parameters"}).encode(),
                              "application/json", None, cabecera_ping="true")
    assert r.status_code == 200 and json.loads(r.body)["resourceType"] == "OperationOutcome"
    assert db.sql == []


def test_bundle_real_del_socio_con_referencia_por_documento():
    """Ejemplo enviado por el socio: el Patient tiene id EXT-CC-<doc> y los demás
    recursos lo referencian como Patient/<doc> (su identifier)."""
    ref = {"reference": "Patient/1006458912"}
    b = {"resourceType": "Bundle", "type": "collection",
         "security_envelope": {"algoritmo": "AES-256-Fernet + HMAC-SHA256", "ciphertext": "x"},
         "entry": [
             {"resource": {"resourceType": "Patient", "id": "EXT-CC-1006458912",
                           "identifier": [{"system": "urn:hospital-socio:documento", "value": "1006458912"}],
                           "name": [{"text": "Paciente Sintético"}], "gender": "female"}},
             {"resource": {"resourceType": "ServiceRequest", "id": "SR-FHIR-1", "status": "active",
                           "intent": "order", "subject": dict(ref),
                           "code": {"coding": [{"system": rx.SNOMED, "code": "305351004"}]},
                           "reasonCode": [{"text": "Insuficiencia respiratoria aguda"}]}},
             {"resource": {"resourceType": "Consent", "id": "CONSENT-FHIR-1", "status": "active",
                           "scope": {"text": "Ley 1581/2012"}, "patient": dict(ref)}},
             {"resource": {"resourceType": "Observation", "id": "OBS-1", "status": "final",
                           "code": {"coding": [{"system": rx.LOINC, "code": "8867-4"}]},
                           "subject": dict(ref), "valueQuantity": {"value": 108.0, "unit": "beats/min"}}},
         ]}
    v = rx.validar_bundle_entrante(rx.adaptar_bundle_socio(b))
    assert v.entradas[v.solicitud].recurso["subject"] == {"reference": "Patient/EXT-CC-1006458912"}
    assert rx.extraer_resumen(v)["motivo"] == "Insuficiencia respiratoria aguda"
    transaccion, mapa = rx.reescribir_para_hapi(v, "socio-uci")
    assert transaccion["type"] == "transaction" and len(transaccion["entry"]) == 4


def test_ping_del_socio_con_parameters():
    cuerpo = {"resourceType": "Parameters", "id": "PING-VERIFICACION-R31",
              "parameter": [{"name": "mode", "valueString": "verify_m2m_credentials"}]}
    assert rx.es_ping(cuerpo, "true")
