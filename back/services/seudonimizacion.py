# R12 · Capa de seguridad de datos entre la API y el servicio de IA.
#
# Minimiza: de toda la historia clínica, al modelo solo le llegan las 12 variables
#           clínicas que usa (edad, sexo, signos vitales, dolor, llegada, lesión, motivo).
# Seudonimiza: en vez del documento va un seudónimo HMAC-SHA256 con un secreto que
#           solo conoce la API (SEUDONIMO_SECRETO). El servicio ml no puede revertirlo.
# Nunca salen: nombre, documento, correo, teléfono ni dirección (Ley 1581 de 2012,
#           principios de finalidad y circulación restringida).

import hashlib
import hmac
from datetime import date

from fastapi import HTTPException

from core import identidad
from core.config import SEUDONIMO_SECRETO

# Signos vitales: variable del modelo -> códigos LOINC aceptados (el primero es el que usa el sistema)
LOINC_VARIABLE = {
    "fc":        ["8867-4"],                 # frecuencia cardiaca
    "fr":        ["9279-1"],                 # frecuencia respiratoria
    "pas":       ["8480-6"],                 # presión arterial sistólica
    "pad":       ["8462-4"],                 # presión arterial diastólica
    "temp_c":    ["8310-5", "8331-1"],       # temperatura corporal (u oral)
    "spo2":      ["59408-5", "2708-6"],      # saturación de oxígeno (pulsioximetría o arterial)
    "dolor_nrs": ["72514-3"],                # intensidad del dolor 0-10
}

# Mismos rangos que valida el servicio ml: un valor imposible se rechaza aquí, con un mensaje claro
RANGOS = {"edad": (18, 120), "fc": (20, 250), "fr": (4, 80), "pas": (40, 300), "pad": (20, 200),
          "temp_c": (30, 44), "spo2": (50, 100), "dolor_nrs": (0, 10)}

NOMBRE = {"fc": "frecuencia cardiaca", "fr": "frecuencia respiratoria", "pas": "presión sistólica",
          "pad": "presión diastólica", "temp_c": "temperatura", "spo2": "saturación de oxígeno",
          "dolor_nrs": "dolor"}

# Lo único que puede salir hacia el modelo. Cualquier otra clave hace fallar el envío.
CAMPOS_PERMITIDOS = {"edad", "sexo_M", "fc", "fr", "pas", "pad", "temp_c", "spo2", "dolor_nrs",
                     "llegada_ambulancia", "lesion", "motivo_categoria"}


def seudonimo(documento: int) -> str:
    """Mismo paciente -> mismo seudónimo; sin el secreto no se puede volver al documento."""
    if not SEUDONIMO_SECRETO:
        raise HTTPException(status_code=503, detail="Falta configurar SEUDONIMO_SECRETO en la API")
    # R27: el seudónimo se calcula sobre el documento real, así no cambia tras cifrar el documento.
    documento = identidad.real(documento)
    firma = hmac.new(SEUDONIMO_SECRETO.encode(), str(documento).encode(), hashlib.sha256).hexdigest()
    return "pac-" + firma[:32]


def _edad(nacimiento: date | None, referencia: date) -> int:
    if nacimiento is None:
        raise HTTPException(status_code=422, detail="El paciente no tiene fecha de nacimiento: no se puede calcular la edad")
    return referencia.year - nacimiento.year - ((referencia.month, referencia.day) < (nacimiento.month, nacimiento.day))


def leer_variables(cur, paciente: dict, encuentro: dict) -> tuple[dict, list[str]]:
    """Arma las 12 variables desde la historia clínica. Devuelve (variables, avisos)."""
    avisos = []

    edad = _edad(paciente["fecha_nacimiento"], encuentro["fecha_hora_ingreso"].date())
    if not RANGOS["edad"][0] <= edad <= RANGOS["edad"][1]:
        # Igual que en la semana 9: aplicar el modelo fuera de su población sería extrapolar
        raise HTTPException(status_code=422,
                            detail=f"El modelo se entrenó con adultos (18 años o más); el paciente tiene {edad}")

    genero = paciente.get("genero_fhir")
    if genero in ("male", "female"):
        sexo_m = int(genero == "male")
    else:
        sexo_m = 0
        avisos.append("Sexo no registrado: el modelo lo tomó como femenino (su peso en la predicción es pequeño)")

    # Último valor de cada signo vital en el encuentro
    codigos = [c for lista in LOINC_VARIABLE.values() for c in lista]
    cur.execute("""
        SELECT DISTINCT ON (codigo_loinc) codigo_loinc, valor_numerico
        FROM observaciones
        WHERE id_encuentro = %s
          AND is_deleted = FALSE
          AND valor_numerico IS NOT NULL
          AND codigo_loinc = ANY(%s)
        ORDER BY codigo_loinc, fecha_hora_observacion DESC, id_observacion DESC;
    """, (encuentro["id_encuentro"], codigos))
    por_codigo = {f["codigo_loinc"]: float(f["valor_numerico"]) for f in cur.fetchall()}

    variables = {"edad": edad, "sexo_M": sexo_m}
    for variable, lista in LOINC_VARIABLE.items():
        variables[variable] = next((por_codigo[c] for c in lista if c in por_codigo), None)

    if variables["dolor_nrs"] is None and encuentro.get("dolor_escala") is not None:
        variables["dolor_nrs"] = float(encuentro["dolor_escala"])

    vitales = ["fc", "fr", "pas", "pad", "temp_c", "spo2"]
    if all(variables[v] is None for v in vitales):
        raise HTTPException(status_code=422,
                            detail="El encuentro no tiene signos vitales registrados: no se puede estimar el riesgo")

    for v, (lo, hi) in RANGOS.items():
        if variables.get(v) is not None and not lo <= variables[v] <= hi:
            raise HTTPException(status_code=422,
                                detail=f"Valor fuera de rango para {NOMBRE.get(v, v)}: {variables[v]:g} (válido {lo}-{hi})")

    variables["llegada_ambulancia"] = None if encuentro.get("llegada_ambulancia") is None else int(encuentro["llegada_ambulancia"])
    variables["lesion"] = None if encuentro.get("lesion") is None else int(encuentro["lesion"])
    variables["motivo_categoria"] = encuentro.get("motivo_categoria") or "otros"
    if not encuentro.get("motivo_categoria"):
        avisos.append("Motivo de consulta sin categoría: se usó 'otros'")

    faltan = [NOMBRE[v] for v in vitales + ["dolor_nrs"] if variables[v] is None]
    if faltan:
        avisos.append("Sin dato (el modelo usa el valor típico): " + ", ".join(faltan))
    return variables, avisos


def construir_payload(documento: int, variables: dict) -> dict:
    """El JSON EXACTO que viaja al modelo y que se guarda en ia_payloads."""
    sobrantes = set(variables) - CAMPOS_PERMITIDOS
    if sobrantes:
        # Defensa en profundidad: si alguien agrega un campo por error, no sale de la API
        raise RuntimeError(f"Campos no permitidos hacia el modelo: {sorted(sobrantes)}")
    return {"seudonimo": seudonimo(documento), "variables": {k: variables[k] for k in sorted(variables)}}
