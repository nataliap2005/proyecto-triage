from pathlib import Path

FHIR_CODE = r'''
# ============================================================
# FHIR R4 - INTEROPERABILIDAD CON HAPI FHIR
# ============================================================
import base64
import re
import requests

HAPI_FHIR_URL=os.getenv("HAPI_FHIR_URL","http://localhost:8080/fhir").rstrip("/")
FHIR_IDENTIFIER_SYSTEM="urn:salud-digital:documento"
FHIR_CUM_SYSTEM="urn:salud-digital:cum"
FHIR_LOCAL_SYSTEM="urn:salud-digital:local"

def fhir_id(prefijo,valor):
    limpio=re.sub(r"[^A-Za-z0-9\\-.]","-",str(valor))
    return f"{prefijo}-{limpio}"[:64]

def fhir_put(resource_type,resource_id,resource):
    resource=dict(resource)
    resource["resourceType"]=resource_type
    resource["id"]=resource_id
    try:
        r=requests.put(
            f"{HAPI_FHIR_URL}/{resource_type}/{resource_id}",
            json=resource,
            headers={"Accept":"application/fhir+json","Content-Type":"application/fhir+json"},
            timeout=20
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"No fue posible conectar con HAPI FHIR: {e}")
    if r.status_code not in (200,201):
        try: detalle=r.json()
        except Exception: detalle=r.text
        raise HTTPException(status_code=502,detail={
            "mensaje":"HAPI FHIR rechazó el recurso",
            "resourceType":resource_type,
            "id":resource_id,
            "status_code":r.status_code,
            "respuesta":detalle
        })
    return r.json()

def fhir_get(resource_type,resource_id):
    try:
        r=requests.get(
            f"{HAPI_FHIR_URL}/{resource_type}/{resource_id}",
            headers={"Accept":"application/fhir+json"},
            timeout=20
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"No fue posible conectar con HAPI FHIR: {e}")
    if r.status_code==404:
        raise HTTPException(status_code=404,detail="Recurso FHIR no encontrado")
    if r.status_code!=200:
        raise HTTPException(status_code=502,detail=f"Error consultando HAPI FHIR: HTTP {r.status_code}")
    return r.json()

def ref_patient(documento): return f"Patient/{fhir_id('paciente',documento)}"
def ref_encounter(id_encuentro): return f"Encounter/{fhir_id('encuentro',id_encuentro)}"
def ref_practitioner(documento): return f"Practitioner/{fhir_id('practitioner',documento)}"
def ref_medication(codigo_cum): return f"Medication/{fhir_id('medicamento',codigo_cum)}"

def map_encounter_status(estado):
    return {"en_triage":"triaged","en_atencion":"in-progress","en_observacion":"in-progress","finalizado":"finished"}.get(estado,"unknown")

def map_medication_request_status(estado):
    return {"activa":"active","dispensada":"completed","anulada":"cancelled"}.get(estado,"unknown")

def map_invoice_status(estado):
    return {"pendiente":"issued","pagada":"balanced","anulada":"cancelled"}.get(estado,"draft")

def build_patient(p):
    r={
        "identifier":[{"system":FHIR_IDENTIFIER_SYSTEM,"value":str(p["numero_documento_paciente"])}],
        "active":not p["is_deleted"],
        "name":[{"use":"official","family":p["apellidos"],"given":[p["nombres"]]}]
    }
    if p["genero_fhir"]: r["gender"]=p["genero_fhir"]
    if p["fecha_nacimiento"]: r["birthDate"]=p["fecha_nacimiento"].isoformat()
    if p["telefono"]: r["telecom"]=[{"system":"phone","value":p["telefono"]}]
    if p["direccion"] or p["municipio_residencia"]:
        r["address"]=[{"text":p["direccion"] or "","city":p["municipio_residencia"]}]
    return r

def build_practitioner(u):
    r={
        "identifier":[{"system":FHIR_IDENTIFIER_SYSTEM,"value":str(u["numero_documento_usuario"])}],
        "active":bool(u["estado"] and not u["is_deleted"]),
        "name":[{"family":u["apellidos"],"given":[u["nombres"]]}]
    }
    telecom=[]
    if u["telefono"]: telecom.append({"system":"phone","value":u["telefono"]})
    if u["email"]: telecom.append({"system":"email","value":u["email"]})
    if telecom: r["telecom"]=telecom
    return r

def build_encounter(e):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(e["id_encuentro"])}],
        "status":map_encounter_status(e["estado"]),
        "class":{"system":"http://terminology.hl7.org/CodeSystem/v3-ActCode","code":"EMER","display":"emergency"},
        "subject":{"reference":ref_patient(e["id_paciente"])},
        "period":{"start":e["fecha_hora_ingreso"].isoformat()}
    }
    if e["fecha_hora_fin"]: r["period"]["end"]=e["fecha_hora_fin"].isoformat()
    if e["motivo_consulta"]: r["reasonCode"]=[{"text":e["motivo_consulta"]}]
    if e["medico_responsable"]:
        r["participant"]=[{"individual":{"reference":ref_practitioner(e["medico_responsable"])}}]
    return r

def build_observation(o,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(o["id_observacion"])}],
        "status":"final",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(o["id_encuentro"])},
        "effectiveDateTime":o["fecha_hora_observacion"].isoformat(),
        "performer":[{"reference":ref_practitioner(o["registrado_por"])}]
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":o["codigo_loinc"],"display":o["nombre"]}],"text":o["nombre"]} if o["codigo_loinc"] else {"text":o["nombre"]}
    if o["valor_numerico"] is not None:
        r["valueQuantity"]={"value":float(o["valor_numerico"])}
        if o["unidad"]: r["valueQuantity"]["unit"]=o["unidad"]
    else:
        r["valueString"]=o["valor_texto"]
    return r

def build_condition(d,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(d["id_diagnostico"])}],
        "clinicalStatus":{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-clinical","code":d["estado_clinico"]}]},
        "verificationStatus":{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-ver-status","code":"confirmed"}]},
        "category":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/condition-category","code":"encounter-diagnosis","display":"Encounter Diagnosis"}]}],
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(d["id_encuentro"])},
        "recordedDate":d["fecha_diagnostico"].isoformat(),
        "recorder":{"reference":ref_practitioner(d["registrado_por"])}
    }
    r["code"]={"coding":[{"system":"http://hl7.org/fhir/sid/icd-10","code":d["codigo_cie10"],"display":d["descripcion"]}],"text":d["descripcion"]} if d["codigo_cie10"] else {"text":d["descripcion"]}
    return r

def build_medication(m):
    r={
        "identifier":[{"system":FHIR_CUM_SYSTEM,"value":m["codigo_cum"]}],
        "status":"active" if not m["is_deleted"] else "inactive",
        "code":{"coding":[{"system":FHIR_CUM_SYSTEM,"code":m["codigo_cum"],"display":m["nombre"]}],"text":m["nombre"]}
    }
    if m["forma_farmaceutica"]: r["form"]={"text":m["forma_farmaceutica"]}
    return r

def build_medication_request(p,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(p["id_prescripcion"])}],
        "status":map_medication_request_status(p["estado"]),
        "intent":"order",
        "medicationReference":{"reference":ref_medication(p["codigo_cum"])},
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(p["id_encuentro"])},
        "authoredOn":p["fecha_prescripcion"].isoformat(),
        "requester":{"reference":ref_practitioner(p["prescrito_por"])}
    }
    partes=[]
    if p["dosis"]: partes.append(f"Dosis: {p['dosis']}")
    if p["frecuencia"]: partes.append(f"Frecuencia: {p['frecuencia']}")
    if p["via_administracion"]: partes.append(f"Vía: {p['via_administracion']}")
    partes.append(f"Cantidad: {p['cantidad']}")
    r["dosageInstruction"]=[{"text":". ".join(partes)}]
    return r

def build_service_request(ex,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(ex["id_examen"])}],
        "status":ex["estado"],
        "intent":"order",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(ex["id_encuentro"])},
        "authoredOn":ex["fecha_solicitud"].isoformat(),
        "requester":{"reference":ref_practitioner(ex["solicitado_por"])}
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":ex["codigo_loinc"],"display":ex["nombre"]}],"text":ex["nombre"]} if ex["codigo_loinc"] else {"text":ex["nombre"]}
    if ex["categoria"]: r["category"]=[{"text":ex["categoria"]}]
    return r

def build_diagnostic_report(ex,id_paciente):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(ex["id_examen"])}],
        "basedOn":[{"reference":f"ServiceRequest/{fhir_id('examen',ex['id_examen'])}"}],
        "status":"final" if ex["estado"]=="completed" else "preliminary",
        "subject":{"reference":ref_patient(id_paciente)},
        "encounter":{"reference":ref_encounter(ex["id_encuentro"])}
    }
    r["code"]={"coding":[{"system":"http://loinc.org","code":ex["codigo_loinc"],"display":ex["nombre"]}],"text":ex["nombre"]} if ex["codigo_loinc"] else {"text":ex["nombre"]}
    if ex["fecha_resultado"]:
        r["effectiveDateTime"]=ex["fecha_resultado"].isoformat()
        r["issued"]=ex["fecha_resultado"].isoformat()
    if ex["conclusion"]: r["conclusion"]=ex["conclusion"]
    if ex["resultado"]:
        r["presentedForm"]=[{"contentType":"text/plain","data":base64.b64encode(ex["resultado"].encode("utf-8")).decode("ascii"),"title":f"Resultado de {ex['nombre']}"}]
    return r

def build_document_reference(n,id_paciente):
    contenido=base64.b64encode(n["contenido"].encode("utf-8")).decode("ascii")
    return {
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":str(n["id_nota"])}],
        "status":"current",
        "type":{"text":n["tipo_nota"]},
        "subject":{"reference":ref_patient(id_paciente)},
        "context":{"encounter":[{"reference":ref_encounter(n["id_encuentro"])}]},
        "date":n["fecha_hora"].isoformat(),
        "author":[{"reference":ref_practitioner(n["registrado_por"])}],
        "content":[{"attachment":{"contentType":"text/plain","data":contenido,"title":n["tipo_nota"]}}]
    }

def build_questionnaire_response(r):
    def item(link,text,value_key,value):
        if value is None: return None
        return {"linkId":link,"text":text,"answer":[{value_key:value}]}
    items=[
        item("sintoma-principal","Síntoma principal","valueString",r["sintoma_principal"]),
        item("evolucion","Evolución","valueString",r["evolucion"]),
        item("signos-alarma","Signos de alarma presentes","valueBoolean",r["signos_alarma_presentes"]),
        item("descripcion-signos-alarma","Descripción de signos de alarma","valueString",r["descripcion_signos_alarma"]),
        item("municipio-origen","Municipio de origen","valueString",r["municipio_origen"]),
        item("distancia-aproximada-km","Distancia aproximada en km","valueDecimal",float(r["distancia_aproximada_km"]) if r["distancia_aproximada_km"] is not None else None),
        item("tiempo-desplazamiento-min","Tiempo de desplazamiento en minutos","valueInteger",r["tiempo_desplazamiento_min"])
    ]
    return {
        "identifier":{"system":FHIR_LOCAL_SYSTEM,"value":str(r["id_reporte"])},
        "status":"completed",
        "subject":{"reference":ref_patient(r["id_paciente"])},
        "authored":r["fecha_hora_reporte"].isoformat(),
        "item":[x for x in items if x is not None]
    }

def build_invoice(f):
    r={
        "identifier":[{"system":FHIR_LOCAL_SYSTEM,"value":f["numero_factura"]}],
        "status":map_invoice_status(f["estado"]),
        "subject":{"reference":ref_patient(f["id_paciente"])},
        "date":f["fecha_emision"].isoformat(),
        "totalNet":{"value":float(f["total"]),"currency":"COP"}
    }
    if f["concepto"]: r["type"]={"text":f["concepto"]}
    return r

@app.get("/fhir/estado",tags=["FHIR"])
def estado_fhir(u=Depends(requerir_roles("Admin","Medico"))):
    try:
        r=requests.get(f"{HAPI_FHIR_URL}/metadata",headers={"Accept":"application/fhir+json"},timeout=20)
    except requests.RequestException as e:
        raise HTTPException(status_code=503,detail=f"HAPI FHIR no disponible: {e}")
    if r.status_code!=200:
        raise HTTPException(status_code=502,detail=f"HAPI FHIR respondió HTTP {r.status_code}")
    metadata=r.json()
    return {"estado":"ok","url":HAPI_FHIR_URL,"fhirVersion":metadata.get("fhirVersion"),"software":metadata.get("software",{}).get("name")}

@app.put("/fhir/pacientes/{documento}",tags=["FHIR"])
def sincronizar_patient(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM pacientes WHERE numero_documento_paciente=%s;",(documento,))
        p=cur.fetchone()
        if not p: raise HTTPException(status_code=404,detail="Paciente no encontrado")
        return fhir_put("Patient",fhir_id("paciente",documento),build_patient(p))
    finally: cur.close()

@app.get("/fhir/pacientes/{documento}",tags=["FHIR"])
def consultar_patient(documento:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico","Paciente"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try: exigir_paciente_propio(cur,documento,u)
    finally: cur.close()
    return fhir_get("Patient",fhir_id("paciente",documento))

@app.put("/fhir/encuentros/{id_encuentro}",tags=["FHIR"])
def sincronizar_encounter(id_encuentro:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        e=obtener_encuentro(cur,id_encuentro,True)
        if not e: raise HTTPException(status_code=404,detail="Encuentro no encontrado")
        return fhir_put("Encounter",fhir_id("encuentro",id_encuentro),build_encounter(e))
    finally: cur.close()

@app.put("/fhir/observaciones/{id_observacion}",tags=["FHIR"])
def sincronizar_observation(id_observacion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT o.*,e.id_paciente FROM observaciones o JOIN encuentros e ON e.id_encuentro=o.id_encuentro WHERE o.id_observacion=%s;",(id_observacion,))
        o=cur.fetchone()
        if not o: raise HTTPException(status_code=404,detail="Observación no encontrada")
        return fhir_put("Observation",fhir_id("observacion",id_observacion),build_observation(o,o["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/diagnosticos/{id_diagnostico}",tags=["FHIR"])
def sincronizar_condition(id_diagnostico:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT d.*,e.id_paciente FROM diagnosticos d JOIN encuentros e ON e.id_encuentro=d.id_encuentro WHERE d.id_diagnostico=%s;",(id_diagnostico,))
        d=cur.fetchone()
        if not d: raise HTTPException(status_code=404,detail="Diagnóstico no encontrado")
        return fhir_put("Condition",fhir_id("diagnostico",id_diagnostico),build_condition(d,d["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/medicamentos/{codigo_cum}",tags=["FHIR"])
def sincronizar_medication(codigo_cum:str,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM medicamentos WHERE codigo_cum=%s;",(codigo_cum,))
        m=cur.fetchone()
        if not m: raise HTTPException(status_code=404,detail="Medicamento no encontrado")
        return fhir_put("Medication",fhir_id("medicamento",codigo_cum),build_medication(m))
    finally: cur.close()

@app.put("/fhir/prescripciones/{id_prescripcion}",tags=["FHIR"])
def sincronizar_medication_request(id_prescripcion:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT p.*,e.id_paciente FROM prescripciones p JOIN encuentros e ON e.id_encuentro=p.id_encuentro WHERE p.id_prescripcion=%s;",(id_prescripcion,))
        p=cur.fetchone()
        if not p: raise HTTPException(status_code=404,detail="Prescripción no encontrada")
        return fhir_put("MedicationRequest",fhir_id("prescripcion",id_prescripcion),build_medication_request(p,p["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/examenes/{id_examen}",tags=["FHIR"])
def sincronizar_examen(id_examen:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT ex.*,e.id_paciente FROM examenes ex JOIN encuentros e ON e.id_encuentro=ex.id_encuentro WHERE ex.id_examen=%s;",(id_examen,))
        ex=cur.fetchone()
        if not ex: raise HTTPException(status_code=404,detail="Examen no encontrado")
        service=fhir_put("ServiceRequest",fhir_id("examen",id_examen),build_service_request(ex,ex["id_paciente"]))
        diagnostic=None
        if ex["estado"]=="completed" or ex["resultado"] or ex["conclusion"]:
            diagnostic=fhir_put("DiagnosticReport",fhir_id("resultado-examen",id_examen),build_diagnostic_report(ex,ex["id_paciente"]))
        return {"ServiceRequest":service,"DiagnosticReport":diagnostic}
    finally: cur.close()

@app.put("/fhir/notas-clinicas/{id_nota}",tags=["FHIR"])
def sincronizar_document_reference(id_nota:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT n.*,e.id_paciente FROM notas_clinicas n JOIN encuentros e ON e.id_encuentro=n.id_encuentro WHERE n.id_nota=%s;",(id_nota,))
        n=cur.fetchone()
        if not n: raise HTTPException(status_code=404,detail="Nota clínica no encontrada")
        return fhir_put("DocumentReference",fhir_id("nota",id_nota),build_document_reference(n,n["id_paciente"]))
    finally: cur.close()

@app.put("/fhir/reportes-previos/{id_reporte}",tags=["FHIR"])
def sincronizar_questionnaire_response(id_reporte:int,db=Depends(get_db),u=Depends(requerir_roles("Admin","Medico"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM reportes_previos WHERE id_reporte=%s;",(id_reporte,))
        r=cur.fetchone()
        if not r: raise HTTPException(status_code=404,detail="Reporte previo no encontrado")
        return fhir_put("QuestionnaireResponse",fhir_id("reporte-previo",id_reporte),build_questionnaire_response(r))
    finally: cur.close()

@app.put("/fhir/facturas/{id_factura}",tags=["FHIR"])
def sincronizar_invoice(id_factura:int,db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("SELECT * FROM facturas WHERE id_factura=%s;",(id_factura,))
        f=cur.fetchone()
        if not f: raise HTTPException(status_code=404,detail="Factura no encontrada")
        return fhir_put("Invoice",fhir_id("factura",id_factura),build_invoice(f))
    finally: cur.close()

@app.post("/fhir/sincronizar-todo",tags=["FHIR"])
def sincronizar_todo_fhir(db=Depends(get_db),u=Depends(requerir_roles("Admin"))):
    cur=db.cursor(cursor_factory=RealDictCursor)
    resumen={"Practitioner":0,"Patient":0,"Medication":0,"Encounter":0,"Observation":0,"Condition":0,"MedicationRequest":0,"ServiceRequest":0,"DiagnosticReport":0,"DocumentReference":0,"QuestionnaireResponse":0,"Invoice":0}
    try:
        cur.execute("SELECT u.* FROM usuarios u JOIN roles r ON r.id_rol=u.id_rol WHERE r.nombre='Medico' AND u.is_deleted=FALSE;")
        for med in cur.fetchall():
            fhir_put("Practitioner",fhir_id("practitioner",med["numero_documento_usuario"]),build_practitioner(med)); resumen["Practitioner"]+=1
        cur.execute("SELECT * FROM pacientes WHERE is_deleted=FALSE;")
        for p in cur.fetchall():
            fhir_put("Patient",fhir_id("paciente",p["numero_documento_paciente"]),build_patient(p)); resumen["Patient"]+=1
        cur.execute("SELECT * FROM medicamentos WHERE is_deleted=FALSE;")
        for m in cur.fetchall():
            fhir_put("Medication",fhir_id("medicamento",m["codigo_cum"]),build_medication(m)); resumen["Medication"]+=1
        cur.execute("SELECT * FROM encuentros WHERE is_deleted=FALSE;")
        for e in cur.fetchall():
            fhir_put("Encounter",fhir_id("encuentro",e["id_encuentro"]),build_encounter(e)); resumen["Encounter"]+=1
        cur.execute("SELECT o.*,e.id_paciente FROM observaciones o JOIN encuentros e ON e.id_encuentro=o.id_encuentro WHERE o.is_deleted=FALSE;")
        for o in cur.fetchall():
            fhir_put("Observation",fhir_id("observacion",o["id_observacion"]),build_observation(o,o["id_paciente"])); resumen["Observation"]+=1
        cur.execute("SELECT d.*,e.id_paciente FROM diagnosticos d JOIN encuentros e ON e.id_encuentro=d.id_encuentro WHERE d.is_deleted=FALSE;")
        for d in cur.fetchall():
            fhir_put("Condition",fhir_id("diagnostico",d["id_diagnostico"]),build_condition(d,d["id_paciente"])); resumen["Condition"]+=1
        cur.execute("SELECT p.*,e.id_paciente FROM prescripciones p JOIN encuentros e ON e.id_encuentro=p.id_encuentro WHERE p.is_deleted=FALSE;")
        for p in cur.fetchall():
            fhir_put("MedicationRequest",fhir_id("prescripcion",p["id_prescripcion"]),build_medication_request(p,p["id_paciente"])); resumen["MedicationRequest"]+=1
        cur.execute("SELECT ex.*,e.id_paciente FROM examenes ex JOIN encuentros e ON e.id_encuentro=ex.id_encuentro WHERE ex.is_deleted=FALSE;")
        for ex in cur.fetchall():
            fhir_put("ServiceRequest",fhir_id("examen",ex["id_examen"]),build_service_request(ex,ex["id_paciente"])); resumen["ServiceRequest"]+=1
            if ex["estado"]=="completed" or ex["resultado"] or ex["conclusion"]:
                fhir_put("DiagnosticReport",fhir_id("resultado-examen",ex["id_examen"]),build_diagnostic_report(ex,ex["id_paciente"])); resumen["DiagnosticReport"]+=1
        cur.execute("SELECT n.*,e.id_paciente FROM notas_clinicas n JOIN encuentros e ON e.id_encuentro=n.id_encuentro WHERE n.is_deleted=FALSE;")
        for n in cur.fetchall():
            fhir_put("DocumentReference",fhir_id("nota",n["id_nota"]),build_document_reference(n,n["id_paciente"])); resumen["DocumentReference"]+=1
        cur.execute("SELECT * FROM reportes_previos WHERE is_deleted=FALSE;")
        for r in cur.fetchall():
            fhir_put("QuestionnaireResponse",fhir_id("reporte-previo",r["id_reporte"]),build_questionnaire_response(r)); resumen["QuestionnaireResponse"]+=1
        cur.execute("SELECT * FROM facturas WHERE is_deleted=FALSE;")
        for f in cur.fetchall():
            fhir_put("Invoice",fhir_id("factura",f["id_factura"]),build_invoice(f)); resumen["Invoice"]+=1
        return {"mensaje":"Sincronización FHIR R4 completada","hapi_fhir_url":HAPI_FHIR_URL,"recursos":resumen}
    finally: cur.close()
'''

ruta=Path('main.py')
if not ruta.exists():
    raise FileNotFoundError('No existe main.py. Ejecuta primero endpoints_triaje_corregido.ipynb.')

texto=ruta.read_text(encoding='utf-8')
marcador='# La capa FHIR se incorporará después en un bloque separado.'
marca='# FHIR R4 - INTEROPERABILIDAD CON HAPI FHIR'

if marca in texto:
    print('La capa FHIR ya está agregada. No se duplicó.')
elif marcador in texto:
    texto=texto.replace(marcador,FHIR_CODE)
    ruta.write_text(texto,encoding='utf-8')
    print('Capa FHIR R4 agregada correctamente a main.py.')
else:
    raise RuntimeError('No se encontró el marcador esperado en main.py.')
