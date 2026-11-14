"""R24: harness cerrado, herramientas permitidas, auditoría y salida mínima.

No se permite SQL arbitrario ni ejecución de herramientas por contenido de un documento.
La herramienta se elige explícitamente por el cliente autenticado. La futura selección
por LLM debe llamar ESTE mismo ejecutor, sin saltarse las autorizaciones.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from auth.service import usuario_actual
from core.database import get_db
from routers.common import registrar_auditoria
from routers.rag import Pregunta, _resolver_acceso
from services.ml_client import llamar_ml
from services.seudonimizacion import construir_payload, leer_variables
from rag.privacidad import proteger_texto

router = APIRouter(prefix="/agente", tags=["R24 · Herramientas seguras"])


class SolicitudHerramienta(BaseModel):
    herramienta: Literal["consultar_historia", "ejecutar_modelo", "preparar_remision"]
    paciente_id: int = Field(gt=0)
    id_encuentro: int = Field(gt=0)
    motivo: str | None = Field(default=None, max_length=1000)
    especialidad: str | None = Field(default=None, max_length=120)


def _auditar(cur, u: dict, herramienta: str, seudonimo: str | None, estado: str,
             datos_llm: dict | None = None, payload_llm: dict | None = None):
    # Jamás registrar el documento real, nombre, pregunta cruda, tokens ni credenciales.
    registrar_auditoria(cur, "agente_herramientas", seudonimo or "sin_acceso", "INVOCAR_HERRAMIENTA",
                       u["numero_documento_usuario"], nuevos={
                           "herramienta": herramienta, "resultado": estado,
                           "seudonimo": seudonimo,
                           "payload_modelo": datos_llm,
                           "payload_llm": payload_llm,  # mensajes DEPURADOS efectivamente enviados a Groq
                       })


def _historia_aprobada(cur, paciente_id: int, id_encuentro: int) -> dict:
    # Se limita explícitamente a encuentros sintéticos APROBADOS para RAG.
    cur.execute("""
        SELECT e.id_encuentro, e.motivo_consulta, e.motivo_categoria, e.nivel_triage,
               e.dolor_escala, e.observaciones_triage, e.observaciones_generales
        FROM encuentros e JOIN pacientes p ON p.numero_documento_paciente=e.id_paciente
        WHERE e.id_encuentro=%s AND e.id_paciente=%s AND e.aprobado_rag IS TRUE
          AND e.is_deleted=FALSE AND p.is_deleted=FALSE AND p.origen='sintetico';
    """, (id_encuentro, paciente_id))
    fila = cur.fetchone()
    if fila is None:
        raise HTTPException(status_code=403, detail="La historia no está aprobada para uso del agente")
    cur.execute("""
        SELECT codigo_loinc, nombre, valor_numerico, unidad
        FROM observaciones WHERE id_encuentro=%s AND is_deleted=FALSE
          AND tipo_observacion='signo_vital' AND valor_numerico IS NOT NULL
        ORDER BY fecha_hora_observacion DESC LIMIT 20;
    """, (id_encuentro,))
    observaciones = cur.fetchall()
    return {
        "motivo_consulta": proteger_texto(fila["motivo_consulta"] or ""),
        "motivo_categoria": fila["motivo_categoria"],
        "nivel_triage": fila["nivel_triage"],
        "dolor_escala": fila["dolor_escala"],
        "observaciones_triage": proteger_texto(fila["observaciones_triage"] or ""),
        "observaciones_generales": proteger_texto(fila["observaciones_generales"] or ""),
        "signos": [{"loinc": x["codigo_loinc"], "nombre": x["nombre"],
                    "valor": float(x["valor_numerico"]), "unidad": x["unidad"]}
                   for x in observaciones],
    }


def _despachar(cur, body: SolicitudHerramienta, seudonimo: str) -> tuple[dict, dict | None]:
    historia = _historia_aprobada(cur, body.paciente_id, body.id_encuentro)
    if body.herramienta == "consultar_historia":
        return {"historia": historia}, None

    if body.herramienta == "preparar_remision":
        if not body.motivo or not body.motivo.strip() or not body.especialidad or not body.especialidad.strip():
            raise HTTPException(status_code=422, detail="Se requieren motivo y especialidad")
        borrador = {"estado": "borrador", "enviado": False, "seudonimo": seudonimo,
                    "especialidad": proteger_texto(body.especialidad.strip()),
                    "motivo": proteger_texto(body.motivo.strip()),
                    "resumen_clinico": historia}
        # No se inserta una remisión, no se invoca ningún endpoint de envío.
        return {"borrador": borrador}, None

    # ML: se lee la misma entrada de historia que usa POST /ia/analizar, sin crear
    # reportes, alarmas, notificaciones ni ningún dato clínico nuevo.
    cur.execute("""
        SELECT numero_documento_paciente, fecha_nacimiento, genero_fhir
        FROM pacientes WHERE numero_documento_paciente=%s AND is_deleted=FALSE;
    """, (body.paciente_id,))
    paciente = cur.fetchone()
    cur.execute("""
        SELECT id_encuentro, fecha_hora_ingreso, motivo_categoria, dolor_escala,
               llegada_ambulancia, lesion
        FROM encuentros WHERE id_encuentro=%s AND id_paciente=%s AND is_deleted=FALSE;
    """, (body.id_encuentro, body.paciente_id))
    encuentro = cur.fetchone()
    variables, avisos = leer_variables(cur, paciente, encuentro)
    payload = construir_payload(body.paciente_id, variables)
    prediccion = llamar_ml("POST", "/predecir", json=payload)
    # El contenido devuelto por el modelo se reduce a resultados clínicos
    # permitidos, sin documentos ni identificadores directos.
    resumen = {k: prediccion[k] for k in ("categoria", "p_critico", "probabilidades", "modelo_version")
               if k in prediccion}
    return {"prediccion": resumen, "avisos": avisos, "guardado": False}, payload


@router.post("/herramientas/ejecutar")
def ejecutar(body: SolicitudHerramienta, db=Depends(get_db), u=Depends(usuario_actual)):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        # Rechazos registrados antes de acceder a información clínica.
        if u["rol"] not in ("Medico", "Especialista"):
            _auditar(cur, u, body.herramienta, None, "DENEGADA_ROL")
            db.commit()
            raise HTTPException(status_code=403, detail="No tiene permisos para esta operación")

        # Reutiliza exactamente las restricciones del RAG (médico responsable,
        # especialista con remisión aceptada/finalizada y encuentro del paciente).
        try:
            _, acceso = _resolver_acceso(cur, Pregunta(pregunta="Consulta clínica autorizada",
                                                        paciente_id=body.paciente_id,
                                                        id_encuentro=body.id_encuentro), u)
            resultado, payload = _despachar(cur, body, acceso.seudonimo_paciente)
        except HTTPException as exc:
            db.rollback()
            _auditar(cur, u, body.herramienta, None, f"DENEGADA_{exc.status_code}")
            db.commit()
            raise

        _auditar(cur, u, body.herramienta, acceso.seudonimo_paciente, "OK", payload)
        db.commit()
        return {"herramienta": body.herramienta, "resultado": resultado,
                "payload_llm": None, "llm_invocado": False,
                "advertencia": "Apoyo clínico. Requiere revisión profesional."}
    finally:
        cur.close()
