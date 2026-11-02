# Semana 12 · Asistente clínico RAG: POST /rag/preguntar
#
# Reglas que aplica este router ANTES de tocar el motor (rag/motor.py):
#   1. Rol: solo Medico y Especialista consultan. Admin, Contable y Paciente reciben 403.
#   2. Acceso al paciente: el Especialista solo con remisión aceptada/finalizada;
#      si se indica un encuentro, el Médico debe ser su responsable (o no tener responsable).
#   3. Seudonimización: el cliente envía el documento real; aquí se convierte en el
#      seudónimo HMAC (mismo SEUDONIMO_SECRETO que usó rag/preparar_historias.py).
#      El motor y el LLM nunca ven el documento.
#   4. Filtros clínicos: los aplica rag/recuperar.py en el WHERE (solo guías publicadas
#      e historia APROBADA de ESTE paciente), antes de rankear.
#   5. Auditoría: cada consulta queda en auditoria_cambios con acción CONSULTA_RAG.

import logging
import sys
from pathlib import Path

import psycopg2
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel, Field

from auth.service import requerir_roles
from core.database import get_db
from routers.common import exigir_especialista_remitido, obtener_encuentro, registrar_auditoria
from services.seudonimizacion import seudonimo

# En Docker el paquete rag/ se copia a /app/rag. En local (uvicorn desde back/)
# vive en la raíz del repositorio, un nivel arriba.
_RAIZ = Path(__file__).resolve().parents[2]
if not (Path(__file__).resolve().parents[1] / "rag").exists() and str(_RAIZ) not in sys.path:
    sys.path.append(str(_RAIZ))

from rag.motor import preguntar as motor_preguntar  # noqa: E402
from rag.recuperar import AccesoClinico  # noqa: E402

router = APIRouter(prefix="/rag", tags=["RAG · asistente clínico (Semana 12)"])
log = logging.getLogger("rag")


class Pregunta(BaseModel):
    pregunta: str = Field(min_length=3, max_length=1000)
    paciente_id: int | None = Field(default=None, gt=0, description="Documento del paciente (opcional)")
    id_encuentro: int | None = Field(default=None, gt=0, description="Limita la historia a un encuentro")


def _resolver_acceso(cur, body: Pregunta, u: dict) -> tuple[int | None, AccesoClinico | None]:
    """Valida que el usuario puede ver al paciente y devuelve el acceso seudonimizado."""
    paciente_id = body.paciente_id

    if body.id_encuentro is not None:
        encuentro = obtener_encuentro(cur, body.id_encuentro, incluir_eliminado=False)
        if not encuentro:
            raise HTTPException(status_code=404, detail="Encuentro no encontrado")
        if paciente_id is not None and encuentro["id_paciente"] != paciente_id:
            raise HTTPException(status_code=422, detail="El encuentro no pertenece a ese paciente")
        paciente_id = encuentro["id_paciente"]
        if u["rol"] == "Medico" and encuentro["medico_responsable"] not in (None, u["numero_documento_usuario"]):
            raise HTTPException(status_code=403, detail="El encuentro está asignado a otro médico")

    if paciente_id is None:
        return None, None        # solo guías clínicas

    cur.execute("SELECT 1 FROM pacientes WHERE numero_documento_paciente = %s AND is_deleted = FALSE;",
                (paciente_id,))
    if not cur.fetchone():
        raise HTTPException(status_code=404, detail="Paciente no encontrado")
    exigir_especialista_remitido(cur, paciente_id, u, body.id_encuentro, True)

    return paciente_id, AccesoClinico(seudonimo_paciente=seudonimo(paciente_id),
                                      id_encuentro=body.id_encuentro)


@router.post("/preguntar")
def preguntar(body: Pregunta, db=Depends(get_db), u=Depends(requerir_roles("Medico", "Especialista"))):
    """Responde con citas [F#] usando solo guías publicadas y la historia aprobada del paciente.

    `modo` indica cómo se respondió: `llm` (generada), `extractivo` (el LLM no estuvo disponible
    o se agotó su cupo; se devuelven fragmentos textuales) o `abstencion` (sin evidencia).
    """
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        paciente_id, acceso = _resolver_acceso(cur, body, u)

        try:
            resultado = motor_preguntar(body.pregunta.strip(), acceso=acceso)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except (RuntimeError, psycopg2.Error, ImportError) as exc:
            log.exception("Fallo del motor RAG")
            raise HTTPException(status_code=503, detail=f"El asistente no está disponible: {type(exc).__name__}")

        registrar_auditoria(
            cur, "rag_consultas", paciente_id if paciente_id is not None else "guias", "CONSULTA_RAG",
            u["numero_documento_usuario"],
            nuevos={
                "pregunta": body.pregunta.strip(),
                "id_encuentro": body.id_encuentro,
                "metodo": resultado["metodo"],
                "modo": resultado["modo"],
                "fuentes": [f["id_fragmento"] for f in resultado["fuentes"]],
                "fuentes_citadas": [f["cita"] for f in resultado["fuentes"] if f["citada"]],
            },
        )
        db.commit()
    except psycopg2.errors.CheckViolation:
        db.rollback()
        raise HTTPException(status_code=500,
                            detail="Falta la acción CONSULTA_RAG en auditoría: ejecute la migración 011")
    except Exception:
        db.rollback()
        raise
    finally:
        cur.close()

    return {
        "respuesta": resultado["respuesta"],
        "modo": resultado["modo"],
        "aviso": resultado["aviso"],
        "metodo": resultado["metodo"],
        "con_historia": acceso is not None,
        "fuentes": resultado["fuentes"],
        "advertencia": "Apoyo documental. No reemplaza el juicio clínico del profesional.",
    }
