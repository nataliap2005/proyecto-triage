"""R30 · R31 · R32: devolución con Task en los dos sentidos y cliente hacia el socio.

  - Nuestro especialista acepta o rechaza una remisión externa -> Task al socio.
  - El socio acepta o rechaza una remisión que le enviamos -> aviso al médico.
  - El cliente hacia el socio (token OAuth en caché, API key, nonce, HTTPS).
  - El consentimiento queda ligado a la institución configurada y vence.

Sin Neon, HAPI ni red: base y HTTP son dobles.
    cd back && python -m pytest tests/test_devolucion_r30.py -q
"""
import json
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from core import socio_cliente as sc
from routers import recepcion_externa as rx
from routers import remisiones_fhir_r30 as r30

INST = {"client_id": "socio-demo", "nombre": "Institución de demostración"}
ESPECIALISTA = {"rol": "Especialista", "numero_documento_usuario": 1000000101}
FHIR_JSON = "application/fhir+json"


@pytest.fixture(autouse=True)
def entorno(monkeypatch):
    monkeypatch.setenv("R30_IDENTIFICADOR_SECRETO", "prueba-local-no-real-" * 3)
    for var in ("R30_SOCIO_TOKEN_URL", "R30_SOCIO_CLIENT_ID", "R30_SOCIO_CLIENT_SECRET",
                "R30_SOCIO_API_KEY", "R30_SOCIO_API_KEY_HEADER", "R30_SOCIO_ID",
                "R30_SOCIO_RESPUESTA_URL", "R30_SOCIO_URL"):
        monkeypatch.delenv(var, raising=False)
    sc.olvidar_token()


class Respuesta:
    def __init__(self, status=200, cuerpo=None):
        self.status_code = status
        self._cuerpo = cuerpo if cuerpo is not None else {}

    def json(self):
        return self._cuerpo


class Http:
    """Doble de requests.post: responde según la URL y guarda cada llamada."""

    def __init__(self, respuestas=None):
        self.llamadas = []
        self.respuestas = respuestas or {}

    def __call__(self, url, **k):
        self.llamadas.append((url, k))
        r = self.respuestas.get(url)
        if callable(r):
            return r()
        return r or Respuesta(200, {"resourceType": "Task"})


# =====================================================================
# Cliente hacia el socio
# =====================================================================

def test_sin_credenciales_no_se_envia(monkeypatch):
    with pytest.raises(sc.SocioNoConfigurado):
        sc.cabeceras()


def test_url_sin_https_solo_en_la_red_de_prueba():
    assert sc.validar_url("http://api:8000/fhir/x", "x")
    assert sc.validar_url("https://socio.example.org/api/x", "x")
    with pytest.raises(sc.SocioNoConfigurado, match="HTTPS"):
        sc.validar_url("http://socio.example.org/api/x", "x")


def test_oauth_pide_token_una_vez_y_manda_nonce_distinto(monkeypatch):
    monkeypatch.setenv("R30_SOCIO_TOKEN_URL", "https://socio.example.org/api/oauth/token")
    monkeypatch.setenv("R30_SOCIO_CLIENT_ID", "nosotros")
    monkeypatch.setenv("R30_SOCIO_CLIENT_SECRET", "secreto")
    http = Http({"https://socio.example.org/api/oauth/token":
                 Respuesta(200, {"access_token": "tok-123", "expires_in": 600})})
    a = sc.cabeceras(post=http)
    b = sc.cabeceras(post=http)
    assert a["Authorization"] == b["Authorization"] == "Bearer tok-123"
    assert a["x-nonce"] != b["x-nonce"] and len(a["x-nonce"]) >= 16
    assert len(http.llamadas) == 1                         # token en caché
    assert http.llamadas[0][1]["data"]["grant_type"] == "client_credentials"


def test_api_key_con_cabecera_configurable(monkeypatch):
    monkeypatch.setenv("R30_SOCIO_API_KEY", "clave-del-socio")
    monkeypatch.setenv("R30_SOCIO_API_KEY_HEADER", "X-Institucion-Key")
    assert sc.cabeceras()["X-Institucion-Key"] == "clave-del-socio"


def test_token_vencido_se_renueva_una_vez(monkeypatch):
    monkeypatch.setenv("R30_SOCIO_TOKEN_URL", "https://s.example.org/oauth/token")
    monkeypatch.setenv("R30_SOCIO_CLIENT_ID", "nosotros")
    monkeypatch.setenv("R30_SOCIO_CLIENT_SECRET", "secreto")
    estados = iter([401, 200])
    http = Http({"https://s.example.org/oauth/token": lambda: Respuesta(200, {"access_token": "t", "expires_in": 600}),
                 "https://s.example.org/respuesta": lambda: Respuesta(next(estados))})
    r = sc.enviar_fhir("https://s.example.org/respuesta", {"resourceType": "Task"}, post=http)
    assert r.status_code == 200
    assert sum(1 for u, _ in http.llamadas if u.endswith("/oauth/token")) == 2


# =====================================================================
# Task que le devolvemos al socio
# =====================================================================

def fila_externa(**cambios):
    fila = {"id_remision_externa": 7, "estado": "aceptada", "socio_client_id": "socio-demo",
            "sr_ref_origen": "ServiceRequest/r30-ref-abc", "task_ref_origen": "Task/r30-task-abc",
            "paciente_ref_origen": "Patient/r30-pac-abc", "observacion_respuesta": "Cupo mañana 8 a. m.",
            "fecha_respuesta": datetime(2026, 11, 18, tzinfo=timezone.utc), "respuesta_enviada": False,
            "ids_locales": {"Task/r30-task-abc": "Task/ext-1"}, "id_especialidad": 8}
    fila.update(cambios)
    return fila


def test_task_respuesta_apunta_a_los_recursos_del_socio():
    t = rx.construir_task_respuesta(fila_externa())
    assert t["id"] == "r30-task-abc" and t["status"] == "accepted"
    assert t["focus"] == {"reference": "ServiceRequest/r30-ref-abc"}
    assert t["for"] == {"reference": "Patient/r30-pac-abc"}
    assert t["statusReason"]["text"] == "Cupo mañana 8 a. m."
    rechazo = rx.construir_task_respuesta(fila_externa(estado="rechazada", task_ref_origen="urn:uuid:1"))
    assert rechazo["status"] == "rejected" and "id" not in rechazo


# =====================================================================
# Base falsa programable
# =====================================================================

class Cursor:
    def __init__(self, db):
        self.db, self.ultimo = db, ""

    def execute(self, sql, params=None):
        self.ultimo = " ".join(sql.split())
        self.db.sql.append((self.ultimo, params))

    def _buscar(self):
        for clave, valor in self.db.respuestas.items():
            if clave in self.ultimo:
                return valor() if callable(valor) else valor
        return None

    def fetchone(self):
        r = self._buscar()
        return r[0] if isinstance(r, list) else r

    def fetchall(self):
        r = self._buscar()
        return r if isinstance(r, list) else ([r] if r else [])

    def close(self):
        pass


class Base:
    def __init__(self, respuestas):
        self.respuestas, self.sql, self.commits, self.rollbacks = respuestas, [], 0, 0

    def cursor(self, cursor_factory=None):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def ejecuto(self, texto):
        return [p for s, p in self.sql if texto in s]


@pytest.fixture
def silencio(monkeypatch):
    avisos = []
    monkeypatch.setattr(rx, "publicar", lambda db, dest, **k: avisos.append((list(dest), k)))
    monkeypatch.setattr(rx, "usuarios_por_rol", lambda db, *r: [1171644825])
    monkeypatch.setattr(rx, "_actualizar_task_local", lambda fila: None)
    return avisos


# =====================================================================
# Nuestro especialista decide
# =====================================================================

def base_decision(estado="pendiente", de_su_especialidad=True, enviada=False):
    pendiente = fila_externa(estado=estado, respuesta_enviada=enviada)
    decidida = fila_externa(estado="aceptada", respuesta_enviada=enviada)
    return Base({
        "FOR UPDATE": pendiente,
        "FROM usuario_especialidades": {"?column?": 1} if de_su_especialidad else None,
        "UPDATE remisiones_externas SET estado": decidida,
        "SELECT * FROM remisiones_externas": decidida,
    })


def test_aceptar_guarda_audita_y_entrega_el_task(monkeypatch, silencio):
    monkeypatch.setenv("R30_SOCIO_RESPUESTA_URL", "https://socio.example.org/api/fhir/remisiones-r30/respuesta")
    monkeypatch.setenv("R30_SOCIO_API_KEY", "k")
    http = Http()
    monkeypatch.setattr(sc.requests, "post", http)
    db = base_decision()
    r = rx.aceptar_remision_externa(7, rx.Decision(observacion="Cupo mañana"), db=db, u=ESPECIALISTA)
    assert r["estado"] == "aceptada" and r["respuesta_enviada"] is True
    accion = [p[2] for s, p in db.sql if "INSERT INTO auditoria_cambios" in s]
    assert accion == ["ACEPTAR_REMISION_EXTERNA"]
    url, k = http.llamadas[0]
    assert url.endswith("/respuesta") and k["json"]["status"] == "accepted"
    assert k["headers"]["x-nonce"]
    assert db.ejecuto("SET respuesta_enviada = TRUE")


def test_si_el_socio_no_responde_queda_para_reintentar(monkeypatch, silencio):
    db = base_decision()
    r = rx.rechazar_remision_externa(7, rx.Decision(observacion="Sin cupo"), db=db, u=ESPECIALISTA)
    assert r["estado"] == "rechazada"
    assert r["respuesta_enviada"] is False and "sin configurar" in r["detalle"].lower()
    assert not db.ejecuto("SET respuesta_enviada = TRUE")


def test_no_se_decide_dos_veces_ni_en_otra_especialidad(silencio):
    with pytest.raises(HTTPException) as e:
        rx.aceptar_remision_externa(7, rx.Decision(), db=base_decision(estado="aceptada"), u=ESPECIALISTA)
    assert e.value.status_code == 409
    with pytest.raises(HTTPException) as e:
        rx.aceptar_remision_externa(7, rx.Decision(), db=base_decision(de_su_especialidad=False),
                                    u=ESPECIALISTA)
    assert e.value.status_code == 403


# =====================================================================
# El socio responde a lo que enviamos
# =====================================================================

def task_socio(**cambios):
    t = {"resourceType": "Task", "id": r30._id_fhir("task", 10), "status": "accepted",
         "intent": "order", "focus": {"reference": f"ServiceRequest/{r30._id_fhir('ref', 10)}"},
         "statusReason": {"text": "Cita asignada"}}
    t.update(cambios)
    return t


def base_respuesta(actual=None, socio_coincide=True):
    envios = [{"id_envio": 3, "id_remision": 10, "remitido_por": 1000000050,
               "respuesta_socio": actual, "id_paciente": 9900000196}] if socio_coincide else []
    return Base({"FROM r30_envios e JOIN remisiones": envios,
                 "SELECT respuesta_socio FROM r30_envios": {"respuesta_socio": actual}})


def responder(db, cuerpo, content_type=FHIR_JSON):
    crudo = cuerpo if isinstance(cuerpo, bytes) else json.dumps(cuerpo).encode()
    return rx.procesar_respuesta(db, INST, crudo, content_type, "203.0.113.9")


def test_respuesta_del_socio_actualiza_y_avisa_al_medico(silencio):
    db = base_respuesta()
    r = responder(db, task_socio())
    assert r.status_code == 200
    actualizacion = db.ejecuto("UPDATE r30_envios")[0]
    assert actualizacion[:3] == ("aceptada", "Cita asignada", "socio-demo")
    auditoria = [p for s, p in db.sql if "INSERT INTO auditoria_cambios" in s]
    assert auditoria[0][2] == "RESPUESTA_SOCIO"
    assert all("'SOCIO'" in s for s, _ in db.sql if "INSERT INTO auditoria_cambios" in s)
    destinatarios, aviso = silencio[0]
    assert destinatarios == [1000000050]                    # el médico remitente
    assert aviso["tipo"] == "remision_socio_aceptada" and aviso["paciente_id"] == 9900000196


def test_tambien_se_reconoce_por_el_service_request():
    datos = rx.validar_task_respuesta(task_socio(id=None, status="rejected"))
    assert datos["estado"] == "rechazada"
    assert rx._corresponde(10, datos) and not rx._corresponde(11, datos)


@pytest.mark.parametrize("cambio, status", [
    ({"status": "completed"}, 422),
    ({"resourceType": "ServiceRequest"}, 422),
    ({"id": None, "focus": None}, 422),
])
def test_task_invalido_se_rechaza_sin_escribir(silencio, cambio, status):
    db = base_respuesta()
    r = responder(db, task_socio(**cambio))
    assert r.status_code == status
    assert json.loads(r.body)["resourceType"] == "OperationOutcome"
    assert not db.ejecuto("UPDATE r30_envios")


def test_task_de_una_remision_que_no_le_enviamos_es_404(silencio):
    db = base_respuesta(socio_coincide=False)
    r = responder(db, task_socio())
    assert r.status_code == 404 and not db.ejecuto("UPDATE r30_envios")


def test_reintento_igual_es_idempotente_y_cambio_de_opinion_es_409(silencio):
    db = base_respuesta(actual="aceptada")
    assert responder(db, task_socio()).status_code == 200
    assert not db.ejecuto("UPDATE r30_envios") and silencio == []
    db = base_respuesta(actual="aceptada")
    assert responder(db, task_socio(status="rejected")).status_code == 409


def test_content_type_y_tamano_de_la_respuesta(silencio):
    assert responder(base_respuesta(), task_socio(), "text/plain").status_code == 415
    assert responder(base_respuesta(), b" " * (rx.MAX_BYTES_TASK + 1)).status_code == 413


# =====================================================================
# R32: consentimiento por institución y con vencimiento
# =====================================================================

class CursorConsent:
    def __init__(self):
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        if "RETURNING expira_at" in self.calls[-1][0]:
            return {"expira_at": datetime(2027, 11, 18, tzinfo=timezone.utc)}
        return (1,)

    def close(self):
        pass


class DbConsent:
    def __init__(self):
        self.cur, self.commits = CursorConsent(), 0

    def cursor(self, **k):
        return self.cur

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def test_consentimiento_se_guarda_para_el_socio_configurado_y_vence(monkeypatch):
    monkeypatch.setenv("R30_SOCIO_ID", "hospital-socio")
    monkeypatch.setenv("R30_CONSENTIMIENTO_DIAS", "30")
    db = DbConsent()
    paciente = {"rol": "Paciente", "numero_documento_usuario": 9900000196}
    r = r30.consentimiento(r30.Consentimiento(id_paciente=9900000196, autoriza=True), db=db, u=paciente)
    sql, params = next(c for c in db.cur.calls if "INSERT INTO r30_consentimientos" in c[0])
    assert params[1] == "hospital-socio" and params[-1] == 30
    assert r["socio"] == "hospital-socio" and r["expira_at"].startswith("2027-11-18")


def test_el_envio_usa_el_socio_configurado(monkeypatch):
    monkeypatch.setenv("R30_SOCIO_ID", "hospital-socio")
    assert r30.socio_id() == "hospital-socio"
    import inspect
    fuente = inspect.getsource(r30)
    # Ni el socio fijo del piloto ni el token compartido viejo quedan en el código.
    assert "'socio-piloto'" not in fuente and '"socio-piloto"' not in fuente
    assert not hasattr(r30, "HEADER") and not hasattr(r30, "_config_receptor")
