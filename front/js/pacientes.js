import {apiGet,apiPut,apiPost,apiDelete} from "./api.js";
import {isRole,getCurrentUser} from "./auth.js";
import {escapeHtml,formatDateOnly,initialsFromName,showToast,modal} from "./ui.js";
import {renderHistoria} from "./historia.js";
import {renderPacs} from "./pacs.js";
import {renderEncuentroActual} from "./encuentro_actual.js";
import {abrirRemisionModal,renderResumenRemisionesMedico} from "./remisiones.js";
import {renderPanelIA} from "./ia.js";
import {renderPanelAsistente} from "./asistente.js";  

let currentPatient=null;

export async function renderListaPacientes(container){
  container.innerHTML='<div class="card">Cargando pacientes…</div>';
  try{
    const rows=await apiGet("/pacientes");
    const miDocumento=Number(getCurrentUser()?.numero_documento_usuario||0);
    container.innerHTML=`<section class="page-hero"><div><p class="eyebrow">Pacientes</p><h2>Pacientes registrados</h2><p class="muted">Listado clínico de pacientes disponibles para consulta. El médico solo puede desactivar fichas que él mismo registró; la restauración queda reservada al Admin.</p></div><span class="badge info">${rows.length} pacientes</span></section><div class="card">${rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Documento</th><th>Nombre</th><th>Fecha nacimiento</th><th>Municipio</th><th>Zona</th><th>Cuenta portal</th><th>Acciones</th></tr></thead><tbody>${rows.map(p=>`<tr><td>${p.numero_documento_paciente}</td><td>${escapeHtml(p.nombres||"")} ${escapeHtml(p.apellidos||"")}</td><td>${formatDateOnly(p.fecha_nacimiento)||"—"}</td><td>${escapeHtml(p.municipio_residencia||"—")}</td><td>${escapeHtml(p.zona_residencia||"—")}</td><td>${p.id_usuario?'<span class="badge success">Sí</span>':'<span class="badge neutral">No</span>'}</td><td><div class="actions">${p.medico_encuentro_activo&&Number(p.medico_encuentro_activo)!==miDocumento?'<button class="btn btn-secondary" disabled title="El encuentro activo está asignado a otro médico">Asignado a otro médico</button>':`<button class="btn btn-secondary" data-open-patient="${Number(p.numero_documento_paciente)}" type="button">Abrir ficha</button>`}${p.puede_eliminar?`<button class="btn btn-danger" data-delete-patient="${Number(p.numero_documento_paciente)}" data-patient-name="${escapeHtml(`${p.nombres||""} ${p.apellidos||""}`)}" type="button">Desactivar ficha</button>`:""}</div></td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No hay pacientes registrados.</div>'}</div>`;
    container.querySelectorAll("[data-open-patient]").forEach(btn=>btn.addEventListener("click",()=>{
      window.dispatchEvent(new CustomEvent("app:open-patient",{detail:{documento:Number(btn.dataset.openPatient)}}));
    }));
    container.querySelectorAll("[data-delete-patient]").forEach(btn=>btn.addEventListener("click",async()=>{
      const documento=Number(btn.dataset.deletePatient),nombre=btn.dataset.patientName||`paciente ${documento}`;
      if(!confirm(`¿Desactivar la ficha clínica de ${nombre}?

No se borrará físicamente. Solo el Admin podrá restaurarla.`))return;
      btn.disabled=true;
      try{
        await apiDelete(`/pacientes/${documento}`);
        showToast("Ficha clínica desactivada. El Admin puede restaurarla.","success",5000);
        await renderListaPacientes(container);
      }catch(err){
        showToast(err.message,"error",5000);
        btn.disabled=false;
      }
    }));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
export async function renderPacienteWorkspace(container,{self=false,documento=null}={}){
  const tpl=document.getElementById("tpl-paciente-shell");container.innerHTML="";container.appendChild(tpl.content.cloneNode(true));
  const form=container.querySelector("#patient-search-form"),input=container.querySelector("#patient-document");
  if(self){form.hidden=true;const u=getCurrentUser();await loadPatient(u.numero_documento_usuario,container.querySelector("#patient-result"),true);return;}
  if(documento){form.hidden=true;await loadPatient(documento,container.querySelector("#patient-result"));return;}
  form.addEventListener("submit",async e=>{e.preventDefault();await loadPatient(Number(input.value),container.querySelector("#patient-result"));});
}
async function loadPatient(documento,target,self=false){
  target.innerHTML='<div class="card">Buscando paciente…</div>';
  try{currentPatient=await apiGet(`/pacientes/${documento}`);
    if(!self&&isRole("Medico")){
      const cola=await apiGet("/encuentros/urgencias/activos");
      const ajeno=cola.find(e=>Number(e.id_paciente)===Number(documento)&&e.medico_responsable&&Number(e.medico_responsable)!==Number(getCurrentUser()?.numero_documento_usuario));
      if(ajeno){target.innerHTML='<div class="card"><div class="empty-state"><strong>Paciente en atención por otro médico</strong><p>Este encuentro ya tiene profesional responsable. No es posible abrir su ficha desde esta sesión.</p></div></div>';return;}
    }
    target.innerHTML=patientShell(currentPatient,self);bindTabs(documento,target);if(!self&&isRole("Medico"))await renderResumenRemisionesMedico(documento,target.querySelector("#patient-referrals"));if(!self)target.querySelector('[data-tab="actual"]')?.click();}
  catch(e){
    if(!self&&isRole("Medico")&&String(e.message||"").toLowerCase().includes("paciente no encontrado")){
      target.innerHTML=`<div class="card"><div class="empty-state"><strong>Paciente no registrado</strong><p>La persona puede ser atendida aunque no tenga cuenta del portal. Registre primero su ficha clínica y luego inicie la atención de Urgencias.</p><button id="register-patient" class="btn btn-primary" type="button">+ Registrar paciente</button></div></div>`;
      target.querySelector("#register-patient")?.addEventListener("click",()=>registrarPacienteModal(documento,()=>loadPatient(documento,target)));
    }else target.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
}

function registrarPacienteModal(documento,onDone){
  const m=modal("Registrar paciente",`<form id="new-patient-form" class="stack-form"><p class="muted small-text">Este registro crea la ficha clínica. No crea una cuenta de acceso; la atención no depende de tener portal.</p><div class="grid grid-2"><label>Documento<input name="numero_documento_paciente" type="number" value="${Number(documento)}" readonly required></label><label>Tipo de documento<select name="tipo_documento" required><option value="CC">CC</option><option value="TI">TI</option><option value="CE">CE</option><option value="PA">Pasaporte</option><option value="RC">Registro civil</option></select></label><label>Nombres<input name="nombres" required></label><label>Apellidos<input name="apellidos" required></label><label>Fecha de nacimiento<input name="fecha_nacimiento" type="date"></label><label>Género FHIR<select name="genero_fhir"><option value="">Sin especificar</option><option value="female">Femenino</option><option value="male">Masculino</option><option value="other">Otro</option><option value="unknown">Desconocido</option></select></label><label>Teléfono<input name="telefono"></label><label>Municipio<input name="municipio_residencia"></label><label>Zona<select name="zona_residencia"><option value="">Sin especificar</option><option value="urbana">Urbana</option><option value="rural_dispersa">Rural dispersa</option></select></label><label>Dirección<input name="direccion"></label></div><button class="btn btn-primary" type="submit">Registrar y abrir ficha</button></form>`);
  m.element.querySelector("#new-patient-form").onsubmit=async e=>{
    e.preventDefault();const fd=new FormData(e.target);const body=Object.fromEntries(fd.entries());body.numero_documento_paciente=Number(body.numero_documento_paciente);["fecha_nacimiento","genero_fhir","telefono","direccion","municipio_residencia","zona_residencia"].forEach(k=>{if(!body[k])body[k]=null;});
    try{await apiPost("/pacientes",body);showToast("Ficha clínica creada. Ya puede iniciar la atención.","success");m.close();await onDone();}catch(err){showToast(err.message,"error");}
  };
}
function patientShell(p,self){
  return `<section class="patient-header"><div class="patient-title"><div class="patient-avatar">${initialsFromName(p.nombres,p.apellidos)}</div><div><h2>${escapeHtml(p.nombres)} ${escapeHtml(p.apellidos)}</h2><p class="muted">${escapeHtml(p.tipo_documento||"Documento")} ${p.numero_documento_paciente}</p></div></div><div class="actions">${isRole("Medico")?'<button id="refer-patient" class="btn btn-primary" type="button">+ Nueva remisión</button><button id="send-vitals-fhir" class="btn btn-secondary" type="button">Enviar signos a FHIR</button><button id="register-fhir-observation" class="btn btn-secondary" type="button">+ Resultado FHIR</button><button id="sync-patient-fhir" class="btn btn-secondary" type="button">Sincronizar Patient FHIR</button>':''}</div></section>${isRole("Medico")?`<section id="patient-referrals" data-documento="${Number(p.numero_documento_paciente)}"></section>`:''}<nav class="patient-tabs">${self?"":'<button class="patient-tab active" data-tab="actual">Encuentro actual</button>'}<button class="patient-tab ${self?"active":""}" data-tab="datos">Datos personales</button><button class="patient-tab" data-tab="historia">Historia clínica</button><button class="patient-tab" data-tab="imagenes">Imágenes PACS</button>${!self&&(isRole("Admin")||isRole("Medico")||isRole("Especialista"))?'<button class="patient-tab" data-tab="ia">Apoyo al triage con IA</button>':""}${!self&&(isRole("Medico")||isRole("Especialista"))?'<button class="patient-tab" data-tab="asistente">Asistente clínico</button>':""}</nav><section id="patient-panel" class="patient-panel">${self?renderDatos(p):""}</section>`;
}
function renderDatos(p){const fields=[["Fecha de nacimiento",formatDateOnly(p.fecha_nacimiento)],["Género FHIR",p.genero_fhir],["Teléfono",p.telefono],["Dirección",p.direccion],["Municipio",p.municipio_residencia],["Zona",p.zona_residencia]];return `<div class="card"><div class="section-head"><h3>Información del paciente</h3></div><div class="detail-list">${fields.map(([k,v])=>`<div class="detail-item"><span>${escapeHtml(k)}</span><strong>${escapeHtml(v||"—")}</strong></div>`).join("")}</div></div>`;}
function registrarObservationFhirModal(doc){
  const opciones=[
    ["2339-0","Glucosa en sangre","mg/dL"],
    ["8480-6","Presión arterial sistólica","mmHg"],
    ["8462-4","Presión arterial diastólica","mmHg"],
    ["8867-4","Frecuencia cardíaca","/min"],
    ["8310-5","Temperatura corporal","Cel"],
    ["59408-5","Saturación de oxígeno","%"]
  ];
  const options=opciones.map(([codigo,nombre,unidad])=>`<option value="${codigo}" data-nombre="${escapeHtml(nombre)}" data-unidad="${escapeHtml(unidad)}">${escapeHtml(nombre)} (${codigo})</option>`).join("");
  const m=modal("Registrar resultado FHIR",`<form id="fhir-observation-form" class="stack-form"><p class="muted small-text">Registra un resultado clínico interoperable para este paciente. El recurso se envía a HAPI FHIR y la Subscription activa automáticamente la notificación y auditoría. Los sistemas externos pueden seguir enviando Observations directamente a FHIR.</p><label>Tipo de resultado<select name="codigo_loinc" id="fhir-observation-type" required>${options}</select></label><div class="grid grid-2"><label>Valor<input name="valor" type="number" step="any" required></label><label>Unidad<input name="unidad" id="fhir-observation-unit" readonly required></label></div><button class="btn btn-primary" type="submit">Enviar a FHIR</button></form>`);
  const form=m.element.querySelector("#fhir-observation-form");
  const select=form.querySelector("#fhir-observation-type");
  const unit=form.querySelector("#fhir-observation-unit");
  const actualizarUnidad=()=>{unit.value=select.selectedOptions[0]?.dataset.unidad||"";};
  select.addEventListener("change",actualizarUnidad);
  actualizarUnidad();
  form.onsubmit=async e=>{
    e.preventDefault();
    const option=select.selectedOptions[0];
    const body={
      codigo_loinc:select.value,
      nombre:option?.dataset.nombre||option?.textContent||"Observation",
      valor:Number(new FormData(form).get("valor")),
      unidad:unit.value
    };
    const submit=form.querySelector('button[type="submit"]');
    submit.disabled=true;
    submit.textContent="Enviando…";
    try{
      await apiPost(`/fhir/pacientes/${doc}/observations`,body);
      showToast("Resultado enviado a HAPI FHIR. La notificación se generará automáticamente.","success",5000);
      m.close();
    }catch(err){
      showToast(err.message,"error",5000);
      submit.disabled=false;
      submit.textContent="Enviar a FHIR";
    }
  };
}

function bindTabs(doc,target){
  const panel=target.querySelector("#patient-panel");target.querySelectorAll("[data-tab]").forEach(b=>b.addEventListener("click",async()=>{target.querySelectorAll("[data-tab]").forEach(x=>x.classList.toggle("active",x===b));if(b.dataset.tab==="actual")await renderEncuentroActual(doc,panel);if(b.dataset.tab==="datos")panel.innerHTML=renderDatos(currentPatient);if(b.dataset.tab==="historia")await renderHistoria(doc,panel);if(b.dataset.tab==="imagenes")await renderPacs(doc,panel);if(b.dataset.tab==="ia")await renderPanelIA(doc,panel);if(b.dataset.tab==="asistente")await renderPanelAsistente(doc,panel);}));
  target.querySelector("#send-vitals-fhir")?.addEventListener("click",async e=>{
    const btn=e.currentTarget;btn.disabled=true;
    try{const resultado=await apiPost(`/fhir/pacientes/${doc}/observations/registradas`,{});showToast(`${resultado.enviadas} mediciones registradas enviadas a HAPI FHIR`,"success",5000);}
    catch(err){showToast(err.message,"error",6000);}finally{btn.disabled=false;}
  });
  target.querySelector("#register-fhir-observation")?.addEventListener("click",()=>registrarObservationFhirModal(doc));
  target.querySelector("#sync-patient-fhir")?.addEventListener("click",async()=>{try{await apiPut(`/fhir/pacientes/${doc}`,{});showToast("Paciente sincronizado con HAPI FHIR","success");}catch(e){showToast(e.message,"error");}});
  target.querySelector("#refer-patient")?.addEventListener("click",async()=>{try{const h=await apiGet(`/pacientes/${doc}/historia-clinica`);const enc=(h.encuentros||[]).find(e=>e.estado!=="finalizado");await abrirRemisionModal(currentPatient,enc?.id_encuentro||null,()=>renderResumenRemisionesMedico(doc,target.querySelector("#patient-referrals")));}catch(e){showToast(e.message,"error")}});
}
