# Endpoints de pacientes y consulta de historia clínica unificada.

from datetime import date, datetime
from html import escape
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Literal

from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import Response
from psycopg2.errors import UniqueViolation
from psycopg2.extras import RealDictCursor
from pydantic import BaseModel,Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from auth.service import requerir_roles
from core.database import get_db
from core.cifrado import cifrar,cifrar_campos
from core import identidad
from routers.common import exigir_especialista_remitido,exigir_paciente_propio,obtener_registro,registrar_auditoria

router=APIRouter()

GeneroFHIR=Literal["male","female","other","unknown"]
Zona=Literal["urbana","rural_dispersa"]

class PacienteCreate(BaseModel):
    numero_documento_paciente:int
    tipo_documento:str=Field(max_length=20)
    nombres:str=Field(max_length=100)
    apellidos:str=Field(max_length=100)
    fecha_nacimiento:date|None=None
    genero_fhir:GeneroFHIR|None=None
    telefono:str|None=Field(default=None,max_length=30)
    direccion:str|None=Field(default=None,max_length=200)
    municipio_residencia:str|None=Field(default=None,max_length=100)
    zona_residencia:Zona|None=None

class PacienteUpdate(BaseModel):
    tipo_documento:str|None=Field(default=None,max_length=20)
    nombres:str|None=Field(default=None,max_length=100)
    apellidos:str|None=Field(default=None,max_length=100)
    fecha_nacimiento:date|None=None
    genero_fhir:GeneroFHIR|None=None
    telefono:str|None=Field(default=None,max_length=30)
    direccion:str|None=Field(default=None,max_length=200)
    municipio_residencia:str|None=Field(default=None,max_length=100)
    zona_residencia:Zona|None=None

@router.post("/pacientes",tags=["Pacientes"],status_code=201)
def crear_paciente(data:PacienteCreate,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT numero_documento_usuario
            FROM usuarios
            WHERE numero_documento_usuario=%s
              AND id_rol=(SELECT id_rol FROM roles WHERE nombre='Paciente')
              AND is_deleted=FALSE;
        """,(data.numero_documento_paciente,))

        cuenta=cur.fetchone()

        cur.execute("""
            INSERT INTO pacientes(
                numero_documento_paciente,id_usuario,tipo_documento,nombres,
                apellidos,fecha_nacimiento,genero_fhir,telefono,direccion,
                municipio_residencia,zona_residencia
            )
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            RETURNING *;
        """,(
            data.numero_documento_paciente,
            cuenta["numero_documento_usuario"] if cuenta else None,
            data.tipo_documento,data.nombres,data.apellidos,
            data.fecha_nacimiento,
            data.genero_fhir,cifrar(data.telefono,"telefono"),cifrar(data.direccion,"direccion"),
            data.municipio_residencia,data.zona_residencia
        ))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",data.numero_documento_paciente,"CREAR",
            u["numero_documento_usuario"],nuevos=nuevo
        )

        db.commit()
        return nuevo

    except UniqueViolation:
        db.rollback()
        raise HTTPException(status_code=409,detail="Paciente ya registrado")
    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/pacientes",tags=["Pacientes"])
def listar_pacientes(db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        if u["rol"]=="Medico":
            cur.execute("""
                SELECT p.*,
                       (SELECT e.medico_responsable FROM encuentros e WHERE e.id_paciente=p.numero_documento_paciente AND e.is_deleted=FALSE AND e.estado <> 'finalizado' ORDER BY e.fecha_hora_ingreso DESC LIMIT 1) AS medico_encuentro_activo,
                       EXISTS(
                           SELECT 1
                           FROM auditoria_cambios a
                           WHERE a.tabla_afectada='pacientes'
                             AND a.registro_id=p.numero_documento_paciente::text
                             AND a.accion='CREAR'
                             AND a.realizado_por=%s
                       ) AS puede_eliminar
                FROM pacientes p
                WHERE p.is_deleted=FALSE
                ORDER BY p.apellidos,p.nombres;
            """,(u["numero_documento_usuario"],))
        else:
            cur.execute("""
                SELECT p.*, TRUE AS puede_eliminar
                FROM pacientes p
                WHERE p.is_deleted=FALSE
                ORDER BY p.apellidos,p.nombres;
            """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/pacientes/eliminados",tags=["Pacientes"])
def listar_pacientes_eliminados(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT p.*,
                   u.username AS eliminado_por_username
            FROM pacientes p
            LEFT JOIN usuarios u ON u.numero_documento_usuario=p.deleted_by
            WHERE p.is_deleted=TRUE
            ORDER BY p.deleted_at DESC NULLS LAST,p.apellidos,p.nombres;
        """)
        return cur.fetchall()
    finally:
        cur.close()

@router.get("/pacientes/{documento}",tags=["Pacientes"])
def ver_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM pacientes
            WHERE numero_documento_paciente=%s
              AND is_deleted=FALSE;
        """,(documento,))

        p=cur.fetchone()

        if not p:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        exigir_paciente_propio(cur,documento,u)
        exigir_especialista_remitido(cur,documento,u,solo_aceptada=True)
        return p

    finally:
        cur.close()

@router.put("/pacientes/{documento}",tags=["Pacientes"])
def editar_paciente(documento:int,data:PacienteUpdate,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cambios=data.model_dump(exclude_unset=True)

    if not cambios:
        raise HTTPException(status_code=400,detail="No se enviaron cambios")

    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        campos=[]
        vals=[]

        # R27: teléfono y dirección se guardan cifrados
        for k,v in cifrar_campos(cambios).items():
            campos.append(f"{k}=%s")
            vals.append(v)

        vals.append(documento)

        cur.execute(
            f"""
            UPDATE pacientes
            SET {','.join(campos)},updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
            """,
            vals
        )

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"EDITAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return nuevo

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.delete("/pacientes/{documento}",tags=["Pacientes"])
def eliminar_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        # R14: el médico solo puede hacer soft delete de un paciente que él mismo creó.
        # No se agrega una columna nueva a la BD: la autoría se verifica en la auditoría
        # del evento CREAR del paciente. El Admin conserva permiso para eliminar/restaurar.
        if u["rol"]=="Medico":
            cur.execute("""
                SELECT 1
                FROM auditoria_cambios
                WHERE tabla_afectada='pacientes'
                  AND registro_id=%s
                  AND accion='CREAR'
                  AND realizado_por=%s
                LIMIT 1;
            """,(str(documento),u["numero_documento_usuario"]))
            if not cur.fetchone():
                raise HTTPException(
                    status_code=403,
                    detail="El médico solo puede eliminar pacientes registrados por él mismo"
                )

        cur.execute("""
            UPDATE pacientes
            SET is_deleted=TRUE,
                deleted_at=now(),
                deleted_by=%s,
                updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
        """,(u["numero_documento_usuario"],documento))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"ELIMINAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Paciente eliminado lógicamente"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.patch("/pacientes/{documento}/restaurar",tags=["Pacientes"])
def restaurar_paciente(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        anterior=obtener_registro(cur,"pacientes","numero_documento_paciente",documento)

        if not anterior:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        cur.execute("""
            UPDATE pacientes
            SET is_deleted=FALSE,
                deleted_at=NULL,
                deleted_by=NULL,
                updated_at=now()
            WHERE numero_documento_paciente=%s
            RETURNING *;
        """,(documento,))

        nuevo=cur.fetchone()

        registrar_auditoria(
            cur,"pacientes",documento,"RESTAURAR",
            u["numero_documento_usuario"],anterior,nuevo
        )

        db.commit()
        return {"mensaje":"Paciente restaurado"}

    except:
        db.rollback()
        raise
    finally:
        cur.close()

@router.get("/pacientes/{documento}/historia-clinica",tags=["Historia clínica"])
def historia_clinica(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Especialista","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)

    try:
        cur.execute("""
            SELECT *
            FROM pacientes
            WHERE numero_documento_paciente=%s
              AND is_deleted=FALSE;
        """,(documento,))

        p=cur.fetchone()

        if not p:
            raise HTTPException(status_code=404,detail="Paciente no encontrado")

        exigir_paciente_propio(cur,documento,u)
        exigir_especialista_remitido(cur,documento,u,solo_aceptada=True)

        cur.execute("""
            SELECT *
            FROM antecedentes
            WHERE id_paciente=%s
              AND is_deleted=FALSE
            ORDER BY fecha_registro DESC;
        """,(documento,))

        antecedentes=cur.fetchall()

        cur.execute("""
            SELECT *
            FROM encuentros
            WHERE id_paciente=%s
              AND is_deleted=FALSE
            ORDER BY fecha_hora_ingreso DESC;
        """,(documento,))

        encuentros=cur.fetchall()
        episodios=[]

        for e in encuentros:
            ide=e["id_encuentro"]

            cur.execute("""
                SELECT *
                FROM observaciones
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_hora_observacion;
            """,(ide,))
            obs=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM diagnosticos
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_diagnostico;
            """,(ide,))
            dx=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM notas_clinicas
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_hora;
            """,(ide,))
            notas=cur.fetchall()

            cur.execute("""
                SELECT *
                FROM examenes
                WHERE id_encuentro=%s
                  AND is_deleted=FALSE
                ORDER BY fecha_solicitud;
            """,(ide,))
            exam=cur.fetchall()

            cur.execute("""
                SELECT
                    pr.*,m.nombre AS medicamento,
                    m.principio_activo,m.concentracion,
                    m.forma_farmaceutica
                FROM prescripciones pr
                JOIN medicamentos m
                  ON m.codigo_cum=pr.codigo_cum
                WHERE pr.id_encuentro=%s
                  AND pr.is_deleted=FALSE
                ORDER BY pr.fecha_prescripcion;
            """,(ide,))
            pres=cur.fetchall()

            ep=dict(e)

            ep["triage"]={
                "nivel_triage":e["nivel_triage"],
                "fecha_hora_triage":e["fecha_hora_triage"],
                "dolor_escala":e["dolor_escala"],
                "observaciones_triage":e["observaciones_triage"],
                "clasificado_por":e["clasificado_por"]
            }

            ep["observaciones"]=obs
            ep["diagnosticos"]=dx
            ep["notas_clinicas"]=notas
            ep["examenes"]=exam
            ep["prescripciones"]=pres

            cur.execute("""
                SELECT r.id_remision,r.motivo,r.estado,r.fecha_remision,r.fecha_respuesta,
                       r.observacion_respuesta,e.nombre AS especialidad,
                       esp.nombres AS especialista_nombres,esp.apellidos AS especialista_apellidos
                FROM remisiones r
                JOIN especialidades e ON e.id_especialidad=r.id_especialidad
                JOIN usuarios esp ON esp.numero_documento_usuario=r.especialista_destino
                WHERE r.id_encuentro=%s AND r.is_deleted=FALSE
                ORDER BY r.fecha_remision;
            """,(ide,))
            ep["remisiones"]=cur.fetchall()

            cur.execute("""
                SELECT ei.id_estudio,ei.modalidad,ei.descripcion,ei.fecha_estudio,
                       ex.nombre AS examen
                FROM estudios_imagenes ei
                JOIN examenes ex ON ex.id_examen=ei.id_examen
                WHERE ei.id_encuentro=%s AND ei.is_deleted=FALSE
                ORDER BY COALESCE(ei.fecha_estudio,ei.created_at);
            """,(ide,))
            ep["imagenes"]=cur.fetchall()

            episodios.append(ep)

        # R10/R11: solo reportes IA aprobados entran en historia clínica.
        cur.execute("""
            SELECT r.id_reporte AS id, r.id_encuentro, r.estado, r.categoria, r.p_critico,
                   r.modelo_version, r.resultado, r.observaciones_clinico,
                   r.revisado_por, r.revisado_at, r.created_at
            FROM reportes_ia r
            WHERE r.id_paciente=%s AND r.estado='aprobado'
            ORDER BY r.revisado_at DESC;
        """,(documento,))
        reportes_ia=cur.fetchall()

        return {
            "paciente":p,
            "antecedentes":antecedentes,
            "encuentros":episodios,
            "reportes_ia":reportes_ia
        }

    finally:
        cur.close()


def _texto(v):
    # R27: si aparece un número interno, en el PDF se imprime el documento real.
    return escape("—" if v is None else identidad.traducir_texto(str(identidad.real(v))))

def _fecha_local(v, solo_fecha=False):
    if v is None:
        return "—"
    if isinstance(v,date) and not isinstance(v,datetime):
        return v.strftime("%d/%m/%Y")
    try:
        if isinstance(v,str):
            v=datetime.fromisoformat(v.replace("Z","+00:00"))
        if getattr(v,"tzinfo",None):
            v=v.astimezone(ZoneInfo("America/Bogota"))
        return v.strftime("%d/%m/%Y" if solo_fecha else "%d/%m/%Y %I:%M %p")
    except Exception:
        return str(v)

LOINC_LABELS={
    "8310-5":"Temperatura",
    "8867-4":"Frecuencia cardiaca",
    "9279-1":"Frecuencia respiratoria",
    "8480-6":"Presión arterial sistólica",
    "8462-4":"Presión arterial diastólica",
    "2708-6":"Saturación de oxígeno",
    "59408-5":"Saturación de oxígeno",
}

def _nombre_observacion(o):
    nombre=str(o.get("nombre") or "").strip()
    if nombre:return nombre
    codigo=str(o.get("codigo_loinc") or "").strip()
    if codigo in LOINC_LABELS:return LOINC_LABELS[codigo]
    tipo=str(o.get("tipo_observacion") or "").strip()
    if tipo and tipo.lower() not in {"signos_vitales","signos vitales"}:return tipo.replace("_"," ").title()
    unidad=str(o.get("unidad") or "").lower()
    valor=o.get("valor_numerico")
    if "%" in unidad:return "Saturación de oxígeno"
    if "cel" in unidad or "°c" in unidad:return "Temperatura"
    return codigo or "Signo vital"


@router.get("/pacientes/{documento}/historia-clinica/pdf", tags=["Historia clínica"])
def historia_clinica_pdf(
    documento: int,
    db=Depends(get_db),
    u=Depends(requerir_roles("Admin", "Medico", "Especialista", "Paciente")),
):
    """R11: PDF longitudinal; solo reportes IA aprobados y contenido clínico del encuentro."""
    historia = historia_clinica(documento=documento, db=db, u=u)
    paciente = historia["paciente"]
    nombre = f"{paciente.get('nombres','')} {paciente.get('apellidos','')}".strip()

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,pagesize=letter,rightMargin=1.35*cm,leftMargin=1.35*cm,
        topMargin=1.35*cm,bottomMargin=1.35*cm,title=f"Historia clínica - {nombre}",
    )
    estilos=getSampleStyleSheet()
    body=estilos["BodyText"]
    elementos=[
        Paragraph("Historia clínica",estilos["Title"]),
        Paragraph(f"<b>Paciente:</b> {_texto(nombre)}",body),
        Paragraph(f"<b>Documento:</b> {_texto(documento)}",body),
        Paragraph(f"<b>Fecha de nacimiento:</b> {_texto(_fecha_local(paciente.get('fecha_nacimiento'),True))}",body),
        Paragraph(f"<b>Municipio / zona:</b> {_texto(paciente.get('municipio_residencia'))} / {_texto(paciente.get('zona_residencia'))}",body),
        Spacer(1,10),Paragraph("Antecedentes",estilos["Heading2"]),
    ]
    antecedentes=historia.get("antecedentes") or []
    if antecedentes:
        for a in antecedentes:
            elementos.append(Paragraph(f"<b>{_texto(a.get('tipo_antecedente') or a.get('tipo') or 'Antecedente')}:</b> {_texto(a.get('descripcion') or a.get('detalle') or '')}",body))
    else: elementos.append(Paragraph("Sin antecedentes registrados.",body))

    elementos.extend([Spacer(1,8),Paragraph("Encuentros clínicos",estilos["Heading2"])])
    for e in historia.get("encuentros") or []:
        elementos.append(Paragraph(
            f"<b>Encuentro #{_texto(e.get('id_encuentro'))}</b> — {_texto(_fecha_local(e.get('fecha_hora_ingreso')))} — estado: {_texto(e.get('estado'))}",
            estilos["Heading3"],
        ))
        elementos.append(Paragraph(
            f"<b>Servicio:</b> {_texto(e.get('servicio') or e.get('tipo_encuentro'))} &nbsp;&nbsp; "
            f"<b>Motivo:</b> {_texto(e.get('motivo_consulta'))} &nbsp;&nbsp; <b>Triage:</b> {_texto(e.get('nivel_triage'))}",body))
        if e.get("dolor_escala") is not None:
            elementos.append(Paragraph(f"<b>Dolor:</b> {_texto(e.get('dolor_escala'))}/10",body))
        if e.get("fecha_hora_fin"):
            elementos.append(Paragraph(f"<b>Finalización:</b> {_texto(_fecha_local(e.get('fecha_hora_fin')))}",body))

        obs=e.get("observaciones") or []
        if obs:
            datos=[["Signo / observación","Valor","Unidad"]]
            for o in obs:
                valor=o.get("valor_numerico") if o.get("valor_numerico") is not None else o.get("valor_texto")
                datos.append([_nombre_observacion(o),str(valor if valor is not None else "—"),str(o.get("unidad") or "")])
            tabla=Table(datos,colWidths=[7.5*cm,4.5*cm,3*cm])
            tabla.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.lightgrey),("GRID",(0,0),(-1,-1),0.25,colors.grey),("VALIGN",(0,0),(-1,-1),"TOP"),("FONTSIZE",(0,0),(-1,-1),8)]))
            elementos.extend([Spacer(1,5),Paragraph("<b>Signos vitales y observaciones</b>",body),tabla])

        dx=e.get("diagnosticos") or []
        if dx:
            elementos.extend([Spacer(1,5),Paragraph("<b>Diagnósticos</b>",body)])
            for d in dx:
                elementos.append(Paragraph(f"• {_texto(d.get('descripcion'))} {_texto('['+d.get('codigo_cie10')+']' if d.get('codigo_cie10') else '')} — {_texto(d.get('tipo') or '')}",body))

        notas=e.get("notas_clinicas") or []
        if notas:
            elementos.extend([Spacer(1,5),Paragraph("<b>Notas clínicas</b>",body)])
            for n in notas:
                elementos.append(Paragraph(f"• {_texto(n.get('tipo_nota') or 'Nota')}: {_texto(n.get('contenido'))}",body))

        exam=e.get("examenes") or []
        if exam:
            elementos.extend([Spacer(1,5),Paragraph("<b>Exámenes solicitados</b>",body)])
            for x in exam:
                elementos.append(Paragraph(f"• {_texto(x.get('nombre'))} — {_texto(x.get('categoria') or '')} — estado: {_texto(x.get('estado'))}",body))

        imgs=e.get("imagenes") or []
        if imgs:
            elementos.extend([Spacer(1,5),Paragraph("<b>Imágenes PACS asociadas</b>",body)])
            for im in imgs:
                elementos.append(Paragraph(f"• Estudio #{_texto(im.get('id_estudio'))}: {_texto(im.get('examen') or im.get('descripcion'))} — modalidad {_texto(im.get('modalidad'))}",body))

        pres=e.get("prescripciones") or []
        if pres:
            elementos.extend([Spacer(1,5),Paragraph("<b>Prescripciones</b>",body)])
            for pr in pres:
                elementos.append(Paragraph(
                    f"• {_texto(pr.get('medicamento') or pr.get('codigo_cum'))} {_texto(pr.get('concentracion') or '')} — "
                    f"dosis {_texto(pr.get('dosis'))}; frecuencia {_texto(pr.get('frecuencia'))}; vía {_texto(pr.get('via_administracion'))}; cantidad {_texto(pr.get('cantidad'))}",body))

        rem=e.get("remisiones") or []
        if rem:
            elementos.extend([Spacer(1,5),Paragraph("<b>Remisiones</b>",body)])
            for r in rem:
                especialista=f"{r.get('especialista_nombres') or ''} {r.get('especialista_apellidos') or ''}".strip()
                elementos.append(Paragraph(
                    f"• {_texto(r.get('especialidad'))} — {_texto(r.get('estado'))} — especialista: {_texto(especialista)}<br/>"
                    f"Motivo: {_texto(r.get('motivo'))}"+(f"<br/>Conclusión/respuesta: {_texto(r.get('observacion_respuesta'))}" if r.get('observacion_respuesta') else ""),body))
        elementos.append(Spacer(1,10))

    elementos.extend([Spacer(1,6),Paragraph("Reportes de IA aprobados",estilos["Heading2"])])
    reportes=historia.get("reportes_ia") or []
    if reportes:
        for r in reportes:
            pct=(float(r.get("p_critico"))*100) if r.get("p_critico") is not None else None
            ptxt=f"{pct:.2f}%" if pct is not None else "—"
            elementos.append(Paragraph(
                f"<b>Reporte #{_texto(r.get('id'))}</b> — categoría {_texto(r.get('categoria'))} — P(crítico): {_texto(ptxt)} — modelo {_texto(r.get('modelo_version'))}",body))
            if r.get("observaciones_clinico"):
                elementos.append(Paragraph(f"<b>Observación clínica:</b> {_texto(r.get('observaciones_clinico'))}",body))
    else: elementos.append(Paragraph("No hay reportes de IA aprobados.",body))

    doc.build(elementos)
    contenido=buffer.getvalue();buffer.close()

    # Copia institucional del PDF en una carpeta dedicada. El bind mount de
    # docker-compose la deja en ./historias_clinicas del proyecto y .gitignore
    # evita versionar información clínica por accidente.
    carpeta=Path("/app/historias_clinicas")
    try:
        carpeta.mkdir(parents=True,exist_ok=True)
        (carpeta/f"historia_{identidad.real(documento)}.pdf").write_bytes(contenido)
    except OSError:
        pass

    return Response(content=contenido,media_type="application/pdf",headers={"Content-Disposition":f'attachment; filename="historia_{identidad.real(documento)}.pdf"'})

