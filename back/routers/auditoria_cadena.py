# R28: verificación de la auditoría encadenada con hashes (solo Admin).
#
#   GET /auditoria/verificar-cadena
#
# La cadena la construye un trigger de la base (migración 016). Este endpoint solo
# invoca la función auditoria_verificar_cadena(), que recalcula el hash de cada
# fila y comprueba que cada una apunte a la anterior sin huecos.

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from psycopg2.extras import RealDictCursor

from auth.service import requerir_roles
from core.database import get_db

router = APIRouter()

MENSAJES = {
    "CONTENIDO_ALTERADO": "El contenido de un registro fue modificado después de firmarse.",
    "SECUENCIA_CON_HUECO": "Falta al menos un registro: se eliminó o se reordenó la cadena.",
    "ENLACE_ROTO": "Un registro ya no apunta al hash del registro anterior.",
}


@router.get("/auditoria/verificar-cadena", tags=["Auditoría"])
def verificar_cadena(db=Depends(get_db), admin=Depends(requerir_roles("Admin"))):
    """Recorre toda la cadena y devuelve si es íntegra o dónde se rompe por primera vez."""
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM auditoria_verificar_cadena();")
        r = cur.fetchone()
    finally:
        cur.close()

    if r["ok"]:
        resumen = "Cadena íntegra: ningún registro fue alterado, borrado ni reordenado."
    elif r["motivo"]:
        resumen = (f"Cadena ROTA en el registro #{r['id_roto']} (eslabón {r['primer_roto']}): "
                   f"{MENSAJES.get(r['motivo'], r['motivo'])}")
    else:
        resumen = (f"Hay {r['sin_encadenar']} registro(s) sin eslabón: "
                   "se insertaron sin pasar por el trigger de la cadena.")
    return {
        "integra": r["ok"],
        "resumen": resumen,
        "total_eslabones": r["total"],
        "sin_encadenar": r["sin_encadenar"],
        "primer_eslabon_roto": r["primer_roto"],
        "id_auditoria_roto": r["id_roto"],
        "motivo": r["motivo"],
        # Anótelo fuera de la base (acta, correo, captura): si alguien borra los últimos
        # registros, la cadena restante sigue cuadrando pero este hash ya no coincidirá.
        "hash_cabeza": r["hash_cabeza"],
        "verificado_en": datetime.now(timezone.utc).isoformat(),
    }
