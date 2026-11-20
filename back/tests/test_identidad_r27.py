"""R27: documento de identidad cifrado (número interno + bóveda + traducción en la frontera).

Corre sin base de datos: la bóveda se simula en memoria.
"""
import base64
import json
import os

import pytest
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.testclient import TestClient
from pydantic import BaseModel

os.environ.setdefault("CIFRADO_LLAVE_K1", base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("="))

from core import identidad  # noqa: E402
from core.cifrado import cifrar, descifrar  # noqa: E402
from core.identidad_middleware import IdentidadMiddleware, traducir_consulta, traducir_ruta  # noqa: E402

DOC = 1158509126
DOC2 = 31987654


@pytest.fixture(autouse=True)
def boveda(monkeypatch):
    """Bóveda en memoria: id_interno -> documento cifrado."""
    memoria = {}
    identidad._cache.clear()

    def registrar(documento, cur=None):
        n = identidad.interno(documento)
        memoria[n] = cifrar(str(int(documento)), identidad.CONTEXTO)
        return n

    def cargar(ids):
        for i in ids:
            if i in memoria:
                identidad._cache[i] = int(descifrar(memoria[i], identidad.CONTEXTO))

    monkeypatch.setattr(identidad, "registrar", registrar)
    monkeypatch.setattr(identidad, "_cargar", cargar)
    monkeypatch.setattr(identidad, "activa", lambda: True)
    registrar(DOC)
    registrar(DOC2)
    identidad._cache.clear()  # obliga a pasar por la bóveda cifrada
    return memoria


# ---------- número interno ----------

def test_interno_es_estable_y_de_16_digitos():
    a, b = identidad.interno(DOC), identidad.interno(DOC)
    assert a == b
    assert len(str(a)) == 16 and identidad.es_interno(a)
    assert a < 2**53  # el navegador lo maneja sin perder precisión


def test_documentos_distintos_dan_numeros_distintos():
    assert identidad.interno(DOC) != identidad.interno(DOC2)


def test_interno_es_idempotente():
    n = identidad.interno(DOC)
    assert identidad.interno(n) == n


def test_interno_depende_de_la_llave(monkeypatch):
    n = identidad.interno(DOC)
    monkeypatch.setenv("CIFRADO_LLAVE_K1", base64.urlsafe_b64encode(b"z" * 32).decode().rstrip("="))
    assert identidad.interno(DOC) != n


def test_boveda_guarda_el_documento_cifrado(boveda):
    guardado = boveda[identidad.interno(DOC)]
    assert guardado.startswith("v1.k1.") and str(DOC) not in guardado


def test_real_devuelve_el_documento():
    assert identidad.real(identidad.interno(DOC)) == DOC
    assert identidad.real(str(identidad.interno(DOC))) == str(DOC)


def test_real_no_toca_otros_valores():
    for v in (14, 459, DOC, "0123", "abc", None, 0.1851234567890123):
        assert identidad.real(v) == v


# ---------- traducción de texto ----------

def test_traducir_texto_json_y_mensajes():
    n = identidad.interno(DOC)
    texto = json.dumps({"paciente_id": n, "registro_id": str(n), "mensaje": f"Remisión del paciente {n}."})
    salida = json.loads(identidad.traducir_texto(texto))
    assert salida == {"paciente_id": DOC, "registro_id": str(DOC), "mensaje": f"Remisión del paciente {DOC}."}


def test_traducir_texto_no_toca_hashes_tokens_ni_decimales():
    n = str(identidad.interno(DOC))
    casos = [f"a{n}", f"{n}f", f"v1.k1.{n}x", f"0.{n}", f"eyJ{n}", "a3f" + n + "9c"]
    for c in casos:
        assert identidad.traducir_texto(c) == c


def test_numero_de_16_digitos_desconocido_queda_igual():
    assert identidad.traducir_texto("1234567890123456") == "1234567890123456"


# ---------- frontera de la API ----------

def _app():
    app = FastAPI()

    class Alta(BaseModel):
        numero_documento_paciente: int
        nombres: str

    class Remitir(BaseModel):
        id_paciente: int
        especialista_destino: int
        motivo: str

    @app.get("/pacientes/{documento}/historia-clinica")
    def historia(documento: int):
        return {"recibido": documento, "paciente": {"numero_documento_paciente": documento}}

    @app.post("/pacientes")
    def crear(p: Alta):
        return {"guardado": p.numero_documento_paciente}

    @app.post("/remisiones")
    def remitir(r: Remitir):
        return {"id": 14, "id_paciente": r.id_paciente, "especialista_destino": r.especialista_destino,
                "recibido": [r.id_paciente, r.especialista_destino]}

    @app.get("/imagenes")
    def imagenes(id_paciente: int):
        return {"recibido": id_paciente}

    @app.get("/remisiones/{id_remision}")
    def ver_remision(id_remision: int):
        return {"id": id_remision}

    @app.get("/eventos/stream")
    def stream():
        n = identidad.interno(DOC)
        def gen():
            yield f'data: {{"tipo": "remision", "paciente_id": {n}}}\n\n'
        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/pdf")
    def pdf():
        from fastapi import Response
        return Response(content=str(identidad.interno(DOC)).encode(), media_type="application/pdf")

    app.add_middleware(IdentidadMiddleware)
    return TestClient(app)


def test_ruta_con_documento_llega_como_interno_y_sale_como_documento():
    r = _app().get(f"/pacientes/{DOC}/historia-clinica")
    assert r.status_code == 200
    # La ruta trabajó con el número interno...
    # ...pero hacia afuera solo se ve el documento real.
    assert r.json() == {"recibido": DOC, "paciente": {"numero_documento_paciente": DOC}}
    assert str(identidad.interno(DOC)) not in r.text


def test_la_ruta_recibe_el_numero_interno(monkeypatch):
    monkeypatch.setattr(identidad, "traducir_texto", lambda t: t)  # se apaga la salida para mirar adentro
    r = _app().get(f"/pacientes/{DOC}/historia-clinica")
    assert r.json()["recibido"] == identidad.interno(DOC)


def test_cuerpo_de_alta_registra_en_boveda_y_traduce(boveda):
    nuevo = 1012345678
    r = _app().post("/pacientes", json={"numero_documento_paciente": nuevo, "nombres": "Ana"})
    assert r.status_code == 200 and r.json() == {"guardado": nuevo}
    assert identidad.interno(nuevo) in boveda


def test_cuerpo_traduce_paciente_y_especialista(monkeypatch):
    monkeypatch.setattr(identidad, "traducir_texto", lambda t: t)
    r = _app().post("/remisiones", json={"id_paciente": DOC, "especialista_destino": DOC2, "motivo": "x"})
    assert r.json()["recibido"] == [identidad.interno(DOC), identidad.interno(DOC2)]
    assert r.json()["id"] == 14  # el id de la remisión no se toca


def test_respuesta_de_remision_sale_con_documentos():
    r = _app().post("/remisiones", json={"id_paciente": DOC, "especialista_destino": DOC2, "motivo": "x"})
    assert r.json() == {"id": 14, "id_paciente": DOC, "especialista_destino": DOC2, "recibido": [DOC, DOC2]}


def test_consulta_con_documento():
    assert _app().get(f"/imagenes?id_paciente={DOC}").json() == {"recibido": DOC}
    assert traducir_consulta(f"id_paciente={DOC}&x=1") == f"id_paciente={identidad.interno(DOC)}&x=1"


def test_ids_que_no_son_personas_no_se_tocan():
    assert _app().get("/remisiones/14").json() == {"id": 14}
    assert traducir_ruta("/api/remisiones/14/aceptar") == "/api/remisiones/14/aceptar"
    assert traducir_ruta(f"/api/usuarios/{DOC}") == f"/api/usuarios/{identidad.interno(DOC)}"


def test_eventos_en_vivo_salen_con_documento():
    with _app().stream("GET", "/eventos/stream") as r:
        cuerpo = "".join(r.iter_text())
    assert f'"paciente_id": {DOC}' in cuerpo


def test_binarios_no_se_tocan():
    assert _app().get("/pdf").content == str(identidad.interno(DOC)).encode()


def test_sin_migrar_no_hace_nada(monkeypatch):
    monkeypatch.setattr(identidad, "activa", lambda: False)
    monkeypatch.setattr(identidad, "traducir_texto", lambda t: t)
    r = _app().get(f"/pacientes/{DOC}/historia-clinica")
    assert r.json()["recibido"] == DOC


# ---------- seudónimo estable ----------

def test_seudonimo_igual_antes_y_despues(monkeypatch):
    from services import seudonimizacion
    monkeypatch.setattr(seudonimizacion, "SEUDONIMO_SECRETO", "s" * 40)
    assert seudonimizacion.seudonimo(DOC) == seudonimizacion.seudonimo(identidad.interno(DOC))


def test_fhir_id_sale_con_documento_real():
    from routers.fhir import fhir_id
    assert fhir_id("paciente", identidad.interno(DOC)) == f"paciente-{DOC}"
    assert fhir_id("encuentro", 459) == "encuentro-459"
