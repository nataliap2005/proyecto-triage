"""Pruebas de POST /rag/preguntar (Semana 12) sin base de datos, sin Groq y sin modelo.

Desde back/:   python -m pytest tests/test_rag.py -q

Se reemplazan la autenticación, la conexión a la base y el motor RAG, de modo que
se prueban exactamente las reglas del router: rol, acceso al paciente,
seudonimización, auditoría y manejo de errores. Al final se prueba el motor con
recuperación y LLM simulados: abstención, citas y respaldo extractivo ante el 429.
"""
import hashlib
import hmac
import os
import sys
from pathlib import Path

os.environ.setdefault("PG_CONNECTION_STRING", "postgresql://prueba")
os.environ.setdefault("JWT_SECRET_KEY", "prueba")
os.environ["SEUDONIMO_SECRETO"] = "secreto-de-prueba"

BACK = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACK))

import psycopg2  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import routers.rag as rag_router  # noqa: E402
from auth.service import usuario_actual  # noqa: E402
from core.database import get_db  # noqa: E402
import rag.motor as motor  # noqa: E402

DOC = 9900000057
OTRO_MEDICO = 222
ESPERADO = "pac-" + hmac.new(b"secreto-de-prueba", str(DOC).encode(), hashlib.sha256).hexdigest()[:32]


class Cursor:
    def __init__(self, bd):
        self.bd, self._fila = bd, None

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("INSERT INTO auditoria_cambios"):
            if self.bd.falla_auditoria:
                raise psycopg2.errors.CheckViolation()
            self.bd.auditoria.append(params)
            self._fila = None
        elif "FROM encuentros WHERE id_encuentro" in s:
            self._fila = self.bd.encuentros.get(params[0])
        elif "FROM pacientes WHERE numero_documento_paciente" in s:
            self._fila = {"?column?": 1} if params[0] in self.bd.pacientes else None
        elif "FROM remisiones" in s:
            self._fila = {"?column?": 1} if (params[0], params[1]) in self.bd.remisiones else None
        else:
            raise AssertionError(f"SQL inesperado: {s}")

    def fetchone(self):
        return self._fila

    def close(self):
        pass


class BD:
    def __init__(self):
        self.pacientes = {DOC}
        self.encuentros = {
            57: {"id_encuentro": 57, "id_paciente": DOC, "medico_responsable": 111},
            58: {"id_encuentro": 58, "id_paciente": DOC, "medico_responsable": OTRO_MEDICO},
        }
        self.remisiones = set()
        self.auditoria = []
        self.falla_auditoria = False
        self.commits = 0

    def cursor(self, cursor_factory=None):
        return Cursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass


def resultado_motor(**extra):
    return {"respuesta": "Respuesta [F1]", "modo": "llm", "aviso": None, "metodo": "dense",
            "fragmentos_recuperados": 1, "fragmentos_contexto": 1,
            "fuentes": [{"cita": "F1", "citada": True, "id_fragmento": "abc", "tipo": "guia",
                         "fuente": "x.pdf", "titulo": "X", "pagina": 1, "url": None,
                         "puntaje": 0.7, "origen_contexto": "recuperado", "extracto": "…"}], **extra}


@pytest.fixture
def entorno(monkeypatch):
    bd = BD()
    llamadas = []

    def falso_motor(pregunta, acceso=None, **kw):
        llamadas.append({"pregunta": pregunta, "acceso": acceso})
        return resultado_motor()

    monkeypatch.setattr(rag_router, "motor_preguntar", falso_motor)
    app = FastAPI()
    app.include_router(rag_router.router)
    app.dependency_overrides[get_db] = lambda: bd
    usuario = {"rol": "Medico", "numero_documento_usuario": 111}
    app.dependency_overrides[usuario_actual] = lambda: usuario
    return TestClient(app), bd, llamadas, usuario


def post(cliente, **body):
    return cliente.post("/rag/preguntar", json={"pregunta": "¿Qué es el triaje?", **body})


@pytest.mark.parametrize("rol", ["Contable", "Paciente", "Admin"])
def test_roles_no_clinicos_reciben_403(entorno, rol):
    cliente, bd, llamadas, usuario = entorno
    usuario["rol"] = rol
    assert post(cliente).status_code == 403
    assert not llamadas and not bd.auditoria


def test_medico_solo_guias_y_auditoria(entorno):
    cliente, bd, llamadas, _ = entorno
    r = post(cliente)
    assert r.status_code == 200, r.text
    datos = r.json()
    assert datos["modo"] == "llm" and datos["con_historia"] is False
    assert datos["fuentes"][0]["cita"] == "F1"
    assert llamadas[0]["acceso"] is None
    tabla, registro, accion, _, nuevos, usuario = bd.auditoria[0]
    assert (tabla, registro, accion, usuario) == ("rag_consultas", "guias", "CONSULTA_RAG", 111)
    assert nuevos.adapted["fuentes"] == ["abc"] and nuevos.adapted["modo"] == "llm"
    assert bd.commits == 1


def test_paciente_se_seudonimiza_antes_del_motor(entorno):
    cliente, bd, llamadas, _ = entorno
    r = post(cliente, paciente_id=DOC)
    assert r.status_code == 200 and r.json()["con_historia"] is True
    acceso = llamadas[0]["acceso"]
    assert acceso.seudonimo_paciente == ESPERADO
    assert str(DOC) not in repr(llamadas[0])          # el documento nunca llega al motor
    assert bd.auditoria[0][1] == str(DOC)             # pero sí queda en la auditoría interna


def test_paciente_inexistente_404(entorno):
    cliente, *_ = entorno
    assert post(cliente, paciente_id=123).status_code == 404


def test_especialista_sin_remision_403_y_con_remision_200(entorno):
    cliente, bd, _, usuario = entorno
    usuario.update(rol="Especialista", numero_documento_usuario=333)
    assert post(cliente, paciente_id=DOC).status_code == 403
    bd.remisiones.add((DOC, 333))
    assert post(cliente, paciente_id=DOC).status_code == 200


def test_encuentro_de_otro_medico_403(entorno):
    cliente, *_ = entorno
    assert post(cliente, id_encuentro=58).status_code == 403


def test_encuentro_propio_deduce_paciente(entorno):
    cliente, _, llamadas, _ = entorno
    assert post(cliente, id_encuentro=57).status_code == 200
    assert llamadas[0]["acceso"].seudonimo_paciente == ESPERADO
    assert llamadas[0]["acceso"].id_encuentro == 57


def test_encuentro_de_otro_paciente_422(entorno):
    cliente, bd, *_ = entorno
    bd.pacientes.add(1)
    assert post(cliente, id_encuentro=57, paciente_id=1).status_code == 422


def test_pregunta_vacia_422(entorno):
    cliente, *_ = entorno
    assert cliente.post("/rag/preguntar", json={"pregunta": "a"}).status_code == 422


def test_motor_caido_503(entorno, monkeypatch):
    cliente, bd, *_ = entorno
    def roto(*a, **k):
        raise RuntimeError("Falta PG_CONNECTION_STRING")
    monkeypatch.setattr(rag_router, "motor_preguntar", roto)
    assert post(cliente).status_code == 503
    assert not bd.auditoria


def test_sin_migracion_011_mensaje_claro(entorno):
    cliente, bd, *_ = entorno
    bd.falla_auditoria = True
    r = post(cliente)
    assert r.status_code == 500 and "011" in r.json()["detail"]


# ---------- Motor (rag/motor.py) con recuperación y LLM simulados ----------

FRAG = {"id_fragmento": "f1", "id_documento": "d", "tipo": "guia", "fuente": "res.pdf",
        "texto": "ARTÍCULO 5. El triage tendrá cinco categorías. " * 20,
        "metadatos": {"titulo": "Resolución 5596", "pagina": 2, "url": None}}


def preparar_motor(monkeypatch, puntaje, generar):
    monkeypatch.setattr(motor, "buscar", lambda *a, **k: [dict(FRAG, puntaje=puntaje)])
    monkeypatch.setattr(motor, "expandir_contexto",
                        lambda frs, **k: [dict(f, origen_contexto="recuperado") for f in frs])
    monkeypatch.setattr(motor, "generar", generar)


def test_motor_se_abstiene_bajo_el_umbral(monkeypatch):
    def no_llamar(*a):
        raise AssertionError("no debe llamar al LLM")
    preparar_motor(monkeypatch, 0.10, no_llamar)
    r = motor.preguntar("¿quién ganó el mundial de 2014?", metodo="dense")
    assert r["modo"] == "abstencion" and r["fuentes"] == []


def test_motor_marca_fuentes_citadas(monkeypatch):
    preparar_motor(monkeypatch, 0.70, lambda p, c: "Son cinco categorías [F1].")
    r = motor.preguntar("categorías de triaje", metodo="dense")
    assert r["modo"] == "llm" and r["fuentes"][0]["citada"] is True


def test_motor_limite_groq_responde_extractivo(monkeypatch):
    class RateLimitError(Exception):
        pass
    def agotado(*a):
        raise RateLimitError("Error code: 429 - rate_limit_exceeded")
    preparar_motor(monkeypatch, 0.70, agotado)
    r = motor.preguntar("categorías de triaje", metodo="dense")
    assert r["modo"] == "extractivo"
    assert "límite" in r["aviso"]
    assert r["respuesta"].endswith("[F1]") and r["fuentes"][0]["citada"] is True


def test_motor_normaliza_citas_de_gpt_oss(monkeypatch):
    preparar_motor(monkeypatch, 0.70, lambda p, c: "Son cinco categorías 【F1†L6-L9】 y (F1).")
    r = motor.preguntar("categorías de triaje", metodo="dense")
    assert r["respuesta"] == "Son cinco categorías [F1] y [F1]."
    assert r["fuentes"][0]["citada"] is True


def test_motor_detecta_citas_agrupadas():
    assert motor.normalizar_citas("texto 【F2】") == "texto [F2]"
