"""R24: API real con base y ML simulados; no llama a Neon, Groq ni ML remoto.
Desde back/: python -m pytest tests/test_agente_r24.py -q
"""
import os
import sys
from pathlib import Path

os.environ.setdefault('PG_CONNECTION_STRING', 'postgresql://prueba')
os.environ.setdefault('JWT_SECRET_KEY', 'prueba')
os.environ['SEUDONIMO_SECRETO'] = 'secreto-de-prueba'
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from psycopg2.extras import Json

from auth.service import usuario_actual
from core.database import get_db
from routers import agente
_despachar_real = agente._despachar


class Cursor:
    def __init__(self, db):
        self.db = db

    def execute(self, sql, params=None):
        if 'INSERT INTO auditoria_cambios' not in sql:
            raise AssertionError('La BD simulada solo acepta eventos de auditoría')
        self.db.events.append(params)

    def close(self):
        pass


class DB:
    def __init__(self):
        self.events = []
        self.commits = 0
    def cursor(self, **kwargs):
        return Cursor(self)
    def commit(self):
        self.commits += 1
    def rollback(self):
        pass


@pytest.fixture
def entorno(monkeypatch):
    db = DB()
    usuario = {'rol': 'Medico', 'numero_documento_usuario': 111}
    calls = []
    pseudo = 'pac-' + 'a' * 32

    def acceso(cur, body, u):
        calls.append(('autorizacion', u['rol']))
        if u['rol'] == 'Especialista' and body.paciente_id == 999:
            raise HTTPException(403, 'Sin remisión aceptada')
        return body.paciente_id, type('Acceso', (), {'seudonimo_paciente': pseudo})()

    def despachar(cur, body, seudonimo):
        calls.append(('herramienta', body.herramienta))
        return {'ok': True}, {'seudonimo': seudonimo, 'variables': {'edad': 45}}

    monkeypatch.setattr(agente, '_resolver_acceso', acceso)
    monkeypatch.setattr(agente, '_despachar', despachar)

    app = FastAPI()
    app.include_router(agente.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[usuario_actual] = lambda: usuario
    return TestClient(app), db, usuario, calls


def post(client, herramienta='consultar_historia', paciente_id=101):
    return client.post('/agente/herramientas/ejecutar', json={
        'herramienta': herramienta, 'paciente_id': paciente_id,
        'id_encuentro': 2, 'motivo': 'Dolor torácico', 'especialidad': 'Cardiología'
    })


@pytest.mark.parametrize('rol', ['Contable', 'Paciente', 'Admin'])
def test_denegacion_403_y_auditoria_sin_invocar_backend(entorno, rol):
    client, db, usuario, calls = entorno
    usuario['rol'] = rol
    r = post(client, 'ejecutar_modelo')
    assert r.status_code == 403
    assert calls == []
    assert db.commits == 1
    assert db.events[0][2] == 'INVOCAR_HERRAMIENTA'
    assert db.events[0][5] == 111
    assert db.events[0][4].adapted['resultado'] == 'DENEGADA_ROL'


def test_especialista_sin_remision_denegado(entorno):
    client, db, usuario, calls = entorno
    usuario['rol'] = 'Especialista'
    r = post(client, paciente_id=999)
    assert r.status_code == 403
    assert calls == [('autorizacion', 'Especialista')]
    assert db.events[0][4].adapted['resultado'] == 'DENEGADA_403'


@pytest.mark.parametrize('herramienta', ['consultar_historia', 'ejecutar_modelo', 'preparar_remision'])
def test_tres_herramientas_autorizadas_y_auditadas(entorno, herramienta):
    client, db, usuario, calls = entorno
    r = post(client, herramienta)
    assert r.status_code == 200, r.text
    assert r.json()['llm_invocado'] is False
    assert r.json()['payload_llm'] is None
    assert calls[-1] == ('herramienta', herramienta)
    info = db.events[0][4].adapted
    assert info['resultado'] == 'OK'
    assert info['herramienta'] == herramienta
    assert info['seudonimo'].startswith('pac-')
    assert '101' not in str(info)


def test_sin_credenciales_rechazado_antes_de_tools():
    app = FastAPI()
    app.include_router(agente.router)
    app.dependency_overrides[get_db] = lambda: DB()
    client = TestClient(app)
    assert post(client).status_code in (401, 403)


def test_cuerpo_no_permite_herramientas_arbitrarias(entorno):
    client, db, usuario, calls = entorno
    assert post(client, 'ejecutar_sql').status_code == 422
    assert not calls


def test_borrador_censura_canarios_y_no_envia_remision(entorno, monkeypatch):
    client, db, usuario, calls = entorno
    monkeypatch.setattr(agente, '_despachar', _despachar_real)
    monkeypatch.setattr(agente, '_historia_aprobada', lambda *a: {'signos': [], 'motivo_consulta': 'Dolor torácico'})
    # Solo es un texto de prueba ficticio. No hay inserción de remisión.
    r = client.post('/agente/herramientas/ejecutar', json={
        'herramienta': 'preparar_remision', 'paciente_id': 101, 'id_encuentro': 2,
        'motivo': 'Paciente María Prueba, documento 9876543210, dolor torácico',
        'especialidad': 'Cardiología',
    })
    assert r.status_code == 200, r.text
    result = str(r.json())
    assert '9876543210' not in result
    assert 'María Prueba' not in result
    assert r.json()['resultado']['borrador']['enviado'] is False
    assert '9876543210' not in str(db.events)


# El original se conserva antes de las sustituciones de las pruebas.
