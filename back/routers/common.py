# Funciones compartidas por los routers clínicos.
# Se mantienen fuera de main.py para evitar dependencias circulares.

from datetime import date,datetime
from decimal import Decimal

from fastapi import HTTPException
from psycopg2.extras import Json,RealDictCursor


def jsonable_row(row):
    if row is None:
        return None
    d=dict(row)
    for k,v in d.items():
        if isinstance(v,Decimal):
            d[k]=float(v)
        elif isinstance(v,(datetime,date)):
            d[k]=v.isoformat()
    return d

def registrar_auditoria(cursor,tabla,registro_id,accion,usuario,anteriores=None,nuevos=None):
    cursor.execute(
        """
        INSERT INTO auditoria_cambios(
            tabla_afectada,registro_id,accion,datos_anteriores,datos_nuevos,realizado_por
        ) VALUES(%s,%s,%s,%s,%s,%s);
        """,
        (
            tabla,str(registro_id),accion,
            Json(jsonable_row(anteriores)) if anteriores else None,
            Json(jsonable_row(nuevos)) if nuevos else None,
            usuario
        )
    )

def es_paciente_propio(cursor,id_paciente,u):
    cursor.execute("""
        SELECT 1
        FROM pacientes
        WHERE numero_documento_paciente=%s
          AND id_usuario=%s
          AND is_deleted=FALSE;
    """,(id_paciente,u["numero_documento_usuario"]))
    return cursor.fetchone() is not None

def exigir_paciente_propio(cursor,id_paciente,u):
    if u["rol"]=="Paciente" and not es_paciente_propio(cursor,id_paciente,u):
        raise HTTPException(status_code=403,detail="Solo puede consultar su propia información")

def obtener_encuentro(cursor,id_encuentro,incluir_eliminado=True):
    q="SELECT * FROM encuentros WHERE id_encuentro=%s"
    if not incluir_eliminado:
        q+=" AND is_deleted=FALSE"
    cursor.execute(q+";",(id_encuentro,))
    r=cursor.fetchone()
    return dict(r) if r else None

def exigir_especialista_remitido(cursor,id_paciente,u,id_encuentro=None,solo_aceptada=True):
    if u["rol"]!="Especialista":
        return
    estados=("aceptada",) if solo_aceptada else ("pendiente","aceptada")
    placeholders=",".join(["%s"]*len(estados))
    params=[id_paciente,u["numero_documento_usuario"],*estados]
    filtro_encuentro=""
    if id_encuentro is not None:
        filtro_encuentro=" AND id_encuentro=%s"
        params.append(id_encuentro)
    cursor.execute(
        f"""
        SELECT 1 FROM remisiones
        WHERE id_paciente=%s
          AND especialista_destino=%s
          AND estado IN ({placeholders})
          AND is_deleted=FALSE
          {filtro_encuentro}
        LIMIT 1;
        """,
        params
    )
    if not cursor.fetchone():
        raise HTTPException(status_code=403,detail="El especialista solo puede acceder a pacientes con remisión aceptada")

def exigir_acceso_encuentro(cursor,encuentro,u):
    if not encuentro:
        raise HTTPException(status_code=404,detail="Encuentro no encontrado")
    exigir_paciente_propio(cursor,encuentro["id_paciente"],u)
    exigir_especialista_remitido(cursor,encuentro["id_paciente"],u,encuentro["id_encuentro"],True)

def exigir_autor_o_admin(registro,campo_autor,u):
    if u["rol"]=="Admin":
        return
    if u["rol"] not in ("Medico","Especialista") or registro[campo_autor]!=u["numero_documento_usuario"]:
        raise HTTPException(
            status_code=403,
            detail="El profesional solo puede modificar o eliminar registros creados por él mismo"
        )

def obtener_registro(cursor,tabla,pk,id_registro):
    cursor.execute(f"SELECT * FROM {tabla} WHERE {pk}=%s;",(id_registro,))
    r=cursor.fetchone()
    return dict(r) if r else None
def clinical_create(db,u,tabla,pk,data:dict,campo_autor="registrado_por"):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        enc=obtener_encuentro(cur,data["id_encuentro"],False)

        if not enc:
            raise HTTPException(status_code=404,detail="Encuentro no encontrado")

        if enc["estado"]=="finalizado":
            raise HTTPException(status_code=409,detail="El encuentro está finalizado")

        if (
            u["rol"]=="Medico"
            and enc["medico_responsable"] not in (None,u["numero_documento_usuario"])
        ):
            raise HTTPException(status_code=403,detail="El encuentro está asignado a otro médico")

        if u["rol"]=="Especialista":
            exigir_especialista_remitido(cur,enc["id_paciente"],u,enc["id_encuentro"],True)

        data[campo_autor]=u["numero_documento_usuario"]

        cols=list(data.keys())
        vals=[data[c] for c in cols]

        cur.execute(
            f"""
            INSERT INTO {tabla}({','.join(cols)})
            VALUES({','.join(['%s']*len(cols))})
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,nuevo[pk],"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_update(db,u,tabla,pk,id_registro,campo_autor,cambios):
    if not cambios:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior or anterior["is_deleted"]:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        exigir_autor_o_admin(anterior,campo_autor,u)

        campos=[]
        vals=[]

        for k,v in cambios.items():
            campos.append(f"{k}=%s")
            vals.append(v)

        vals.append(id_registro)

        cur.execute(
            f"""
            UPDATE {tabla}
            SET {','.join(campos)},updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_delete(db,u,tabla,pk,id_registro,campo_autor):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior or anterior["is_deleted"]:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        exigir_autor_o_admin(anterior,campo_autor,u)

        cur.execute(
            f"""
            UPDATE {tabla}
            SET is_deleted=TRUE,
                deleted_at=now(),
                deleted_by=%s,
                updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            (u["numero_documento_usuario"],id_registro)
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"ELIMINAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Registro eliminado lógicamente"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

def clinical_restore(db,u,tabla,pk,id_registro):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,tabla,pk,id_registro)

        if not anterior:
            raise HTTPException(status_code=404,detail="Registro no encontrado")

        cur.execute(
            f"""
            UPDATE {tabla}
            SET is_deleted=FALSE,
                deleted_at=NULL,
                deleted_by=NULL,
                updated_at=now()
            WHERE {pk}=%s
            RETURNING *;
            """,
            (id_registro,)
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,tabla,id_registro,"RESTAURAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()
