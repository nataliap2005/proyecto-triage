from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

import asyncio

from auth.router import router as auth_router
from auth.service import requerir_roles
from core.database import get_db
from core.eventos import configurar_loop

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
from routers.catalogos import router as catalogos_router
from routers.remisiones import router as remisiones_router
from routers.eventos import router as eventos_router


app = FastAPI(
    title="API de Triaje Hospitalario",
    version="2.1.0",
    description=(
        "API clínica y administrativa modularizada, con interoperabilidad "
        "FHIR R4 e integración PACS/DICOM mediante Orthanc."
    ),
)

# Solo se permiten orígenes conocidos. El frontend actual usa /api mediante
# Nginx (mismo origen), pero se conservan los orígenes locales autorizados
# para pruebas directas desde el navegador.
ORIGENES_PERMITIDOS = [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGENES_PERMITIDOS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
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
app.include_router(catalogos_router)
app.include_router(remisiones_router)
app.include_router(eventos_router)


# SISTEMA

@app.on_event("startup")
async def _iniciar_bus_eventos():
    configurar_loop(asyncio.get_running_loop())

@app.get("/", tags=["Sistema"])
def raiz():
    return {
        "mensaje": "API de Triaje Hospitalario",
        "version": "2.1.0",
    }


@app.get("/estado-bd", tags=["Sistema"])
def estado_bd(
    db=Depends(get_db),
    usuario=Depends(requerir_roles("Admin")),
):
    cur = db.cursor()

    try:
        cur.execute("SELECT current_database(), current_user;")
        bd, usuario_bd = cur.fetchone()

        return {
            "estado": "ok",
            "base_datos": bd,
            "usuario": usuario_bd,
        }

    finally:
        cur.close()
