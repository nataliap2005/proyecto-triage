from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.router import router as auth_router
from core.database import get_db

from routers.usuarios import router as usuarios_router
from routers.pacientes import router as pacientes_router
from routers.antecedentes import router as antecedentes_router
from routers.reportes_previos import router as reportes_previos_router
from routers.encuentros import router as encuentros_router
from routers.observaciones import router as observaciones_router
from routers.diagnosticos import router as diagnosticos_router
from routers.notas_clinicas import router as notas_clinicas_router
from routers.examenes import router as examenes_router
from routers.medicamentos import router as medicamentos_router
from routers.prescripciones import router as prescripciones_router
from routers.facturas import router as facturas_router
from routers.auditoria import router as auditoria_router
from routers.fhir import router as fhir_router
from routers.pacs import router as pacs_router


app = FastAPI(
    title="API de Triaje Hospitalario",
    version="2.1.0",
    description=(
        "API clínica y administrativa modularizada, con interoperabilidad "
        "FHIR R4 e integración PACS/DICOM mediante Orthanc."
    ),
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ROUTERS
app.include_router(auth_router)

app.include_router(usuarios_router)
app.include_router(pacientes_router)

app.include_router(antecedentes_router)
app.include_router(reportes_previos_router)
app.include_router(encuentros_router)
app.include_router(observaciones_router)
app.include_router(diagnosticos_router)
app.include_router(notas_clinicas_router)
app.include_router(examenes_router)
app.include_router(medicamentos_router)
app.include_router(prescripciones_router)
app.include_router(facturas_router)

app.include_router(auditoria_router)
app.include_router(fhir_router)
app.include_router(pacs_router)


# SISTEMA

@app.get("/", tags=["Sistema"])
def raiz():
    return {
        "mensaje": "API de Triaje Hospitalario",
        "version": "2.1.0",
    }


@app.get("/estado-bd", tags=["Sistema"])
def estado_bd(db=Depends(get_db)):
    cur = db.cursor()

    try:
        cur.execute("SELECT current_database(), current_user;")
        bd, usuario = cur.fetchone()

        return {
            "estado": "ok",
            "base_datos": bd,
            "usuario": usuario,
        }

    finally:
        cur.close()
