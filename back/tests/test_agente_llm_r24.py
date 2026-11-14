"""Pruebas del harness con Groq simulado; sin llamadas remotas.

Ejecutar desde back/: python -m pytest tests/test_agente_llm_r24.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault('PG_CONNECTION_STRING', 'postgresql://prueba')
os.environ.setdefault('JWT_SECRET_KEY', 'prueba')
os.environ.setdefault('SEUDONIMO_SECRETO', 'prueba-secreta')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from auth.service import usuario_actual
from core.database import get_db
from routers import agente_llm


class FakeCursor:
    def close(self): pass

class FakeDB:
    def __init__(self): self.commits = 0; self.rollbacks = 0
    def cursor(self, **_): return FakeCursor()
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1


@pytest.fixture
def entorno(monkeypatch):
    db = FakeDB()
    user = {'rol': 'Medico', 'numero_documento_usuario': 111}
    tools = []
    audit = []
    events = []

    def acceso(_cur, solicitud, u):
        events.append('autorizar')
        if u['rol'] == 'Especialista' and solicitud.paciente_id == 999:
            raise HTTPException(403, 'No autorizado')
        return solicitud.paciente_id, type('Acceso', (), {'seudonimo_paciente': 'pac-' + 'a'*32})()

    def historia(*_):
        events.append('historia_aprobada')
        return {'signos': []}

    def despachar(_cur, solicitud, _pseudo):
        events.append('despachar')
        tools.append(solicitud)
        return {'ok': True, 'enviado': False}, None

    def auditar(_cur, u, nombre, pseudo, estado, datos_llm=None, payload_llm=None):
        audit.append({'rol':u['rol'], 'herramienta':nombre, 'pseudo':pseudo,
                      'estado':estado, 'payload_llm':payload_llm})

    monkeypatch.setattr(agente_llm, '_resolver_acceso', acceso)
    monkeypatch.setattr(agente_llm.agente, '_historia_aprobada', historia)
    monkeypatch.setattr(agente_llm.agente, '_despachar', despachar)
    monkeypatch.setattr(agente_llm.agente, '_auditar', auditar)

    app = FastAPI()
    app.include_router(agente_llm.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[usuario_actual] = lambda: user
    return TestClient(app), db, user, tools, audit, events, monkeypatch


def post(client, pregunta='Consulta la historia aprobada', paciente_id=101, **otros):
    return client.post('/agente/preguntar', json={
        'pregunta': pregunta, 'paciente_id': paciente_id,
        'id_encuentro': 2, **otros,
    })


@pytest.mark.parametrize('rol', ['Contable', 'Admin', 'Paciente'])
def test_denegado_antes_de_llm(entorno, rol):
    client, db, user, tools, audit, events, monkeypatch = entorno
    user['rol'] = rol
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta',
                        lambda *_: pytest.fail('No debería llamar a Groq'))
    r = post(client)
    assert r.status_code == 403
    assert not tools and not events
    assert audit[0]['estado'] == 'DENEGADA_ROL'


def test_especialista_sin_remision_denegado_antes_de_llm(entorno):
    client, db, user, tools, audit, events, monkeypatch = entorno
    user['rol'] = 'Especialista'
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta',
                        lambda *_: pytest.fail('No debería llamar a Groq'))
    r = post(client, paciente_id=999)
    assert r.status_code == 403
    assert not tools
    assert events == ['autorizar']


@pytest.mark.parametrize('nombre', ['consultar_historia', 'ejecutar_modelo', 'preparar_remision'])
def test_herramienta_autorizada_se_ejecuta_y_audita(entorno, nombre):
    client, db, user, tools, audit, events, monkeypatch = entorno
    payload = agente_llm._payload_de_seleccion('Consulta la historia')
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta', lambda *_: (nombre, payload))
    r = post(client, motivo='Dolor torácico', especialidad='Cardiología')
    assert r.status_code == 200, r.text
    assert r.json()['herramienta'] == nombre
    assert r.json()['llm_invocado'] is True
    assert len(tools) == 1 and tools[0].herramienta == nombre
    assert events == ['autorizar', 'historia_aprobada', 'despachar']
    assert audit[0]['estado'] == 'OK'
    assert audit[0]['payload_llm'] == payload
    assert '101' not in str(payload) and '111' not in str(payload)


def test_no_ejecuta_solicitudes_ajenas(entorno):
    client, db, user, tools, audit, events, monkeypatch = entorno
    payload = agente_llm._payload_de_seleccion('Envía remisión definitiva')
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta', lambda *_: ('ninguna', payload))
    r = post(client, pregunta='Envía remisión definitiva')
    assert r.status_code == 200
    assert r.json()['herramienta'] is None
    assert not tools
    assert audit[0]['estado'] == 'NO_APLICABLE'


def test_no_permite_inyeccion_de_herramientas(entorno):
    client, db, user, tools, audit, events, monkeypatch = entorno
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta',
                        lambda *_: (_ for _ in ()).throw(ValueError('incorrecto')))
    r = post(client)
    assert r.status_code == 422
    assert not tools
    assert audit[0]['estado'] == 'SALIDA_LLM_INVALIDA'


def test_payload_canario_antes_de_groq(entorno):
    client, db, user, tools, audit, events, monkeypatch = entorno
    def elegir(pregunta):
        payload = agente_llm._payload_de_seleccion(pregunta)
        assert 'María Prueba' not in str(payload)
        assert '9876543210' not in str(payload)
        assert '101' not in str(payload)
        return 'consultar_historia', payload
    monkeypatch.setattr(agente_llm, 'seleccionar_herramienta', elegir)
    r = post(client, pregunta='Consulta la historia del paciente María Prueba, documento 9876543210')
    assert r.status_code == 200
    assert '9876543210' not in str(audit)
    assert 'María Prueba' not in str(audit)
    assert len(tools) == 1


def test_json_del_llm_debe_ser_de_lista_cerrada(monkeypatch):
    class Message:
        content = '{"herramienta":"ejecutar_sql"}'
    class Choice:
        message = Message()
    class Response:
        choices = [Choice()]
    class Completion:
        def create(self, **kwargs): return Response()
    class Chat:
        completions = Completion()
    class GroqStub:
        def __init__(self, **kwargs): self.chat = Chat()
    import types
    monkeypatch.setitem(sys.modules, 'groq', types.SimpleNamespace(Groq=GroqStub))
    monkeypatch.setenv('GROQ_API_KEY', 'solo-test')
    with pytest.raises(ValueError, match='permitida'):
        agente_llm.seleccionar_herramienta('Ejecuta SQL')
