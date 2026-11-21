from decimal import Decimal

from fastapi import APIRouter,Depends,HTTPException
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field

from auth.service import requerir_roles
from core.database import get_db
from services.seudonimizacion import NOMBRE, RANGOS
from routers.common import clinical_create,clinical_delete,clinical_restore,clinical_update,exigir_acceso_encuentro,obtener_encuentro,obtener_registro

router=APIRouter()

class ObservacionCreate(BaseModel):
    id_encuentro:int
    tipo_observacion:str=Field(max_length=100)
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str=Field(max_length=150)
    valor_numerico:Decimal|None=None
    valor_texto:str|None=None
    unidad:str|None=Field(default=None,max_length=30)

class ObservacionUpdate(BaseModel):
    tipo_observacion:str|None=Field(default=None,max_length=100)
    codigo_loinc:str|None=Field(default=None,max_length=30)
    nombre:str|None=Field(default=None,max_length=150)
    valor_numerico:Decimal|None=None
    valor_texto:str|None=None
    unidad:str|None=Field(default=None,max_length=30)

# Signos vitales reconocidos por su código LOINC. Los límites son los mismos que usa la
# capa hacia la IA (services/seudonimizacion.RANGOS): valores fisiológicamente POSIBLES,
# no valores normales. Un paciente crítico puede tener SpO2 75 % o PAS 70 y debe poder
# registrarse; lo que se bloquea es lo imposible (por ejemplo, 50 °C o una SpO2 de 120 %).
SIGNO_POR_LOINC = {"8480-6": "pas", "8462-4": "pad", "8867-4": "fc", "9279-1": "fr",
                   "8310-5": "temp_c", "2708-6": "spo2", "59408-5": "spo2"}
UNIDAD_SIGNO = {"pas": "mmHg", "pad": "mmHg", "fc": "lpm", "fr": "rpm", "temp_c": "°C", "spo2": "%"}
LOINC_PAS, LOINC_PAD = "8480-6", "8462-4"


def _num(v) -> str:
    return f"{float(v):g}"


def error_rango(codigo_loinc, valor):
    """Mensaje de error si el valor de un signo vital está fuera de lo posible; si no, None."""
    signo = SIGNO_POR_LOINC.get(codigo_loinc or "")
    if not signo or valor is None:
        return None
    lo, hi = RANGOS[signo]
    if lo <= float(valor) <= hi:
        return None
    u = UNIDAD_SIGNO[signo]
    return (f"{NOMBRE[signo].capitalize()}: {_num(valor)} {u} no es un valor posible. "
            f"Debe estar entre {lo} y {hi} {u}.")


def error_presion(pas, pad):
    if pas is not None and pad is not None and float(pas) <= float(pad):
        return (f"La presión sistólica ({_num(pas)} mmHg) debe ser mayor que la diastólica "
                f"({_num(pad)} mmHg).")
    return None


def _ultima(cur, id_encuentro, codigo_loinc, excluir=None):
    cur.execute("""
        SELECT valor_numerico FROM observaciones
        WHERE id_encuentro=%s AND codigo_loinc=%s AND is_deleted=FALSE
          AND valor_numerico IS NOT NULL AND (%s::bigint IS NULL OR id_observacion<>%s)
        ORDER BY fecha_hora_observacion DESC, id_observacion DESC LIMIT 1;
    """, (id_encuentro, codigo_loinc, excluir, excluir))
    fila = cur.fetchone()
    return fila["valor_numerico"] if fila else None


def validar_presion_con_registrada(db, d, excluir=None):
    """PAS > PAD comparando con la última presión registrada en el mismo encuentro."""
    codigo = d.get("codigo_loinc")
    if codigo not in (LOINC_PAS, LOINC_PAD) or d.get("valor_numerico") is None:
        return
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        if codigo == LOINC_PAS:
            error = error_presion(d["valor_numerico"], _ultima(cur, d["id_encuentro"], LOINC_PAD, excluir))
        else:
            error = error_presion(_ultima(cur, d["id_encuentro"], LOINC_PAS, excluir), d["valor_numerico"])
    finally:
        cur.close()
    if error:
        raise HTTPException(status_code=422, detail=error)


def validar_observacion(d):
    if (d.get("valor_numerico") is None)==(d.get("valor_texto") is None):
        raise HTTPException(
            status_code=400,
            detail="Debe enviar exactamente uno entre valor_numerico y valor_texto"
        )
    error = error_rango(d.get("codigo_loinc"), d.get("valor_numerico"))
    if error:
        raise HTTPException(status_code=422, detail=error)


class SignoVital(BaseModel):
    codigo_loinc:str=Field(max_length=30)
    nombre:str=Field(max_length=150)
    valor_numerico:Decimal
    unidad:str|None=Field(default=None,max_length=30)

class SignosVitalesCreate(BaseModel):
    id_encuentro:int
    signos:list[SignoVital]=Field(min_length=1,max_length=12)

@router.post("/observaciones",tags=["Observaciones"],status_code=201)
def crear_observacion(data:ObservacionCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    d=data.model_dump()
    validar_observacion(d)
    validar_presion_con_registrada(db,d)
    return clinical_create(db,u,"observaciones","id_observacion",d)


@router.post("/observaciones/signos-vitales",tags=["Observaciones"],status_code=201)
def crear_signos_vitales(data:SignosVitalesCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    """Registra varios signos vitales en una sola operación: o se guardan todos o ninguno.

    Rechaza con 422 (y la lista de errores) cualquier valor imposible y una presión
    sistólica que no sea mayor que la diastólica (en el mismo envío o frente a la última
    registrada en el encuentro).
    """
    errores=[]
    por_codigo={}
    for s in data.signos:
        if s.codigo_loinc not in SIGNO_POR_LOINC:
            errores.append(f"El código LOINC {s.codigo_loinc} no es un signo vital reconocido.")
            continue
        if s.codigo_loinc in por_codigo:
            errores.append(f"{s.nombre}: viene repetido en el mismo registro.")
        por_codigo[s.codigo_loinc]=s.valor_numerico
        error=error_rango(s.codigo_loinc,s.valor_numerico)
        if error:
            errores.append(error)
    if not errores and (LOINC_PAS in por_codigo or LOINC_PAD in por_codigo):
        pas=por_codigo.get(LOINC_PAS)
        pad=por_codigo.get(LOINC_PAD)
        if pas is None or pad is None:
            # Solo vino una de las dos: se compara con la última registrada en el encuentro.
            cur=db.cursor(cursor_factory=RealDictCursor)
            try:
                if pas is None:
                    pas=_ultima(cur,data.id_encuentro,LOINC_PAS)
                if pad is None:
                    pad=_ultima(cur,data.id_encuentro,LOINC_PAD)
            finally:
                cur.close()
        error=error_presion(pas,pad)
        if error:
            errores.append(error)
    if errores:
        raise HTTPException(status_code=422,detail=" ".join(errores))

    creados=[]
    try:
        for s in data.signos:
            d={"id_encuentro":data.id_encuentro,"tipo_observacion":"signos_vitales",
               "codigo_loinc":s.codigo_loinc,"nombre":s.nombre,"valor_numerico":s.valor_numerico,
               "valor_texto":None,"unidad":s.unidad}
            creados.append(clinical_create(db,u,"observaciones","id_observacion",d,confirmar=False))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return creados

@router.get("/encuentros/{id_encuentro}/observaciones",tags=["Observaciones"])
def observaciones_encuentro(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        e=obtener_encuentro(cur,id_encuentro,False)
        exigir_acceso_encuentro(cur,e,u)

        cur.execute("""
            SELECT *
            FROM observaciones
            WHERE id_encuentro=%s
              AND is_deleted=FALSE
            ORDER BY fecha_hora_observacion;
        """,(id_encuentro,))

        return cur.fetchall()

    finally:
        cur.close()

@router.put("/observaciones/{id_observacion}",tags=["Observaciones"])
def editar_observacion(id_observacion:int,data:ObservacionUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    cambios=data.model_dump(exclude_unset=True)

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        actual=obtener_registro(cur,"observaciones","id_observacion",id_observacion)

        if not actual:
            raise HTTPException(status_code=404,detail="Observación no encontrada")

        combinado=dict(actual)
        combinado.update(cambios)
        validar_observacion(combinado)
        validar_presion_con_registrada(db,combinado,excluir=id_observacion)

    finally:
        cur.close()

    return clinical_update(
        db,u,"observaciones","id_observacion",
        id_observacion,"registrado_por",cambios
    )

@router.delete("/observaciones/{id_observacion}",tags=["Observaciones"])
def eliminar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista"))):
    return clinical_delete(
        db,u,"observaciones","id_observacion",
        id_observacion,"registrado_por"
    )

@router.patch("/observaciones/{id_observacion}/restaurar",tags=["Observaciones"])
def restaurar_observacion(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    return clinical_restore(
        db,u,"observaciones","id_observacion",id_observacion
    )
