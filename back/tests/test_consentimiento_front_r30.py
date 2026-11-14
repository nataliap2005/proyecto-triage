"""R30: lectura protegida del estado persistido para la nueva pantalla de paciente."""
from datetime import datetime, timezone
from fastapi import HTTPException
import pytest
from routers import remisiones_fhir_r30 as r30

class CursorFake:
    def __init__(self, vinculado=True, consent=None):
        self.vinculado=vinculado
        self.consent=consent
        self.ultimo=None
        self.calls=[]
    def execute(self, query, params):
        self.calls.append((query,params))
        self.ultimo='paciente' if 'FROM pacientes' in query else 'consent'
    def fetchone(self):
        if self.ultimo == 'paciente':
            return (1,) if self.vinculado else None
        return self.consent
    def close(self):pass

class DbFake:
    def __init__(self, cursor): self.cur=cursor
    def cursor(self, **kwargs):return self.cur

USUARIO={'rol':'Paciente','numero_documento_usuario':9900000196}

def test_estado_paciente_sin_autorizacion():
    cur=CursorFake()
    result=r30.consultar_estado_consentimiento(db=DbFake(cur),u=USUARIO)
    assert result['registrado'] is False
    assert result['consentimiento_vigente'] is False
    assert result['socio']=='socio-piloto'
    assert cur.calls[-1][1]==(9900000196,)

def test_estado_autorizado_y_fecha():
    momento=datetime(2026,11,13,tzinfo=timezone.utc)
    cur=CursorFake(consent={'vigente':True,'actualizado_at':momento})
    result=r30.consultar_estado_consentimiento(db=DbFake(cur),u=USUARIO)
    assert result['consentimiento_vigente'] is True
    assert result['actualizado_at']==momento.isoformat()

def test_estado_no_accede_paciente_sin_vinculo():
    cur=CursorFake(vinculado=False)
    with pytest.raises(HTTPException) as error:
        r30.consultar_estado_consentimiento(db=DbFake(cur),u=USUARIO)
    assert error.value.status_code==403
    assert len(cur.calls)==1
