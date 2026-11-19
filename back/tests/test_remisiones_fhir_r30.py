"""Pruebas puras R30; no hacen llamadas externas ni requieren pacientes reales."""
from datetime import datetime, timezone
import copy
import pytest
from routers import remisiones_fhir_r30 as r30

@pytest.fixture(autouse=True)
def secreto(monkeypatch):
    monkeypatch.setenv('R30_IDENTIFICADOR_SECRETO', 'prueba-local-no-real-' * 3)


def ejemplo():
    now = datetime(2026, 11, 13, tzinfo=timezone.utc)
    rem = {"id_paciente":9900000196,"id_remision":10,"fecha_remision":now,
           "motivo":"Valoración especializada", "especialidad":"Neurología"}
    obs = [{"id_observacion":5,"codigo_loinc":"8867-4","nombre":"Frecuencia cardiaca",
            "valor_numerico":82,"unidad":"/min"}]
    reps = [{"id_reporte":2,"estado":"pendiente","categoria":"critico","revisado_at":now},
            {"id_reporte":3,"estado":"aprobado","categoria":"medio","revisado_at":now}]
    consentimiento = {"vigente": True, "actualizado_at": now, "expira_at": None}
    return rem,obs,reps,consentimiento


def test_bundle_transaction_y_minimizacion():
    bundle = r30.construir_bundle(*ejemplo())
    assert bundle['type']=='transaction'
    assert {e['resource']['resourceType'] for e in bundle['entry']} == {
        'Patient','ServiceRequest','Observation','DiagnosticReport','Consent','Task'}
    assert len([e for e in bundle['entry'] if e['resource']['resourceType']=='DiagnosticReport'])==1
    assert len(bundle['entry']) == 6
    paciente = bundle['entry'][0]['resource']
    assert not any(k in paciente for k in ('identifier','name','telecom','address','birthDate'))
    assert '9900000196' not in str(bundle)
    assert all(e['request']['method']=='PUT' for e in bundle['entry'])
    assert bundle == r30.construir_bundle(*ejemplo())  # reintentos idempotentes


def test_rechaza_bundle_tipo_batch():
    b = r30.construir_bundle(*ejemplo())
    b['type']='batch'
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_rechaza_loinc_invalido():
    b = r30.construir_bundle(*ejemplo())
    next(e['resource'] for e in b['entry'] if e['resource']['resourceType']=='Observation')['code']['coding'][0]['system']='urn:incorrecto'
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_rechaza_paciente_cruzado():
    b = r30.construir_bundle(*ejemplo())
    next(e['resource'] for e in b['entry'] if e['resource']['resourceType']=='ServiceRequest')['subject']['reference']='Patient/otro'
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_rechaza_inclusion_identidad_directa():
    b = r30.construir_bundle(*ejemplo())
    b['entry'][0]['resource']['name']=[{'text':'Paciente real'}]
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_rechaza_reporte_no_final():
    b = r30.construir_bundle(*ejemplo())
    next(e['resource'] for e in b['entry'] if e['resource']['resourceType']=='DiagnosticReport')['status']='preliminary'
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_rechaza_url_inconsistente():
    b = r30.construir_bundle(*ejemplo())
    b['entry'][0]['request']['url']='Patient/id-equivocado'
    with pytest.raises(ValueError): r30.validar_bundle(b)


def test_no_se_incluye_reporte_sin_aprobacion():
    rem, obs, reps, consentimiento = ejemplo()
    assert len(r30.construir_bundle(rem,obs,reps,consentimiento)['entry']) == 6
    assert len(r30.construir_bundle(rem,obs,[reps[0]],consentimiento)['entry']) == 5


def test_exige_consentimiento_explicito():
    rem, obs, reps, consentimiento = ejemplo()
    consentimiento["vigente"] = False
    with pytest.raises(ValueError, match="consentimiento"):
        r30.construir_bundle(rem, obs, reps, consentimiento)


def test_consent_fhir_vinculado_y_task_refiere_orden():
    b = r30.construir_bundle(*ejemplo())
    recursos = {e["resource"]["resourceType"]: e["resource"] for e in b["entry"]}
    assert recursos["Consent"]["patient"]["reference"] == f"Patient/{recursos['Patient']['id']}"
    assert recursos["Consent"]["provision"]["type"] == "permit"
    assert recursos["Task"]["focus"]["reference"] == f"ServiceRequest/{recursos['ServiceRequest']['id']}"
    assert recursos["Task"]["status"] == "requested"


# Las pruebas del receptor (credenciales, Bundle inválido sin escritura, transacción
# única, Consent inactivo y Task cruzado) se movieron a tests/test_recepcion_externa_r30.py,
# porque el receptor ahora usa las credenciales institucionales R31.
