"""Límites de signos vitales al guardar (observaciones). Sin base de datos."""
from decimal import Decimal

import pytest
from fastapi import HTTPException

from routers import observaciones as obs

U = {"rol": "Medico", "numero_documento_usuario": 1}


def lote(**valores):
    codigos = {"pas": "8480-6", "pad": "8462-4", "fc": "8867-4", "fr": "9279-1", "temp": "8310-5", "spo2": "2708-6"}
    return obs.SignosVitalesCreate(id_encuentro=1, signos=[
        obs.SignoVital(codigo_loinc=codigos[k], nombre=k, valor_numerico=Decimal(str(v))) for k, v in valores.items()])


def test_temperatura_imposible():
    assert "30 y 44" in obs.error_rango("8310-5", 50)
    assert obs.error_rango("8310-5", 39.5) is None


@pytest.mark.parametrize("loinc,valor", [("2708-6", 120), ("2708-6", 30), ("8867-4", 0), ("9279-1", 100),
                                         ("8480-6", 400), ("8462-4", 5)])
def test_valores_imposibles(loinc, valor):
    assert obs.error_rango(loinc, valor)


@pytest.mark.parametrize("loinc,valor", [("2708-6", 75), ("8480-6", 70), ("8867-4", 180), ("8310-5", 35)])
def test_valores_criticos_pero_posibles_se_aceptan(loinc, valor):
    # Un paciente crítico debe poder registrarse: se bloquea lo imposible, no lo anormal.
    assert obs.error_rango(loinc, valor) is None


def test_otros_codigos_no_se_limitan():
    assert obs.error_rango("2160-0", 9999) is None   # creatinina u otros exámenes
    assert obs.error_rango(None, 50) is None


def test_sistolica_debe_ser_mayor_que_diastolica():
    assert "mayor que la diastólica" in obs.error_presion(80, 90)
    assert obs.error_presion(80, 80)
    assert obs.error_presion(120, 80) is None
    assert obs.error_presion(None, 80) is None


def test_observacion_individual_rechaza_valor_imposible():
    with pytest.raises(HTTPException) as e:
        obs.validar_observacion({"codigo_loinc": "8310-5", "valor_numerico": Decimal("50"), "valor_texto": None})
    assert e.value.status_code == 422


def test_lote_rechaza_y_lista_todos_los_errores():
    with pytest.raises(HTTPException) as e:
        obs.crear_signos_vitales(lote(temp=50, spo2=120, fc=80), db=None, u=U)
    assert e.value.status_code == 422
    assert "Temperatura" in e.value.detail and "Saturación" in e.value.detail


def test_lote_rechaza_sistolica_menor_que_diastolica():
    with pytest.raises(HTTPException) as e:
        obs.crear_signos_vitales(lote(pas=80, pad=90), db=None, u=U)
    assert "mayor que la diastólica" in e.value.detail


def test_lote_rechaza_codigo_que_no_es_signo_vital():
    data = obs.SignosVitalesCreate(id_encuentro=1, signos=[
        obs.SignoVital(codigo_loinc="2160-0", nombre="Creatinina", valor_numerico=Decimal("1.1"))])
    with pytest.raises(HTTPException) as e:
        obs.crear_signos_vitales(data, db=None, u=U)
    assert e.value.status_code == 422
