import {apiGet,apiPost,apiPatch} from "./api.js";
import {escapeHtml,formatDate,showToast,modal} from "./ui.js";
import {renderPacienteWorkspace} from "./pacientes.js";

export async function abrirRemisionModal(paciente,idEncuentro,onCreated=null){
  if(!idEncuentro){showToast("El paciente necesita un encuentro activo para ser remitido","warning");return;}
  try{
    const especialidades=await apiGet("/especialidades");
    const m=modal("Remitir a especialista",`<form id="remision-form" class="stack-form"><p class="muted">Paciente <strong>${escapeHtml(paciente.nombres)} ${escapeHtml(paciente.apellidos)}</strong> · Encuentro #${idEncuentro}</p><label>Especialidad<select id="remision-especialidad" required><option value="">Seleccione…</option>${especialidades.map(e=>`<option value="${e.id_especialidad}">${escapeHtml(e.nombre)}</option>`).join("")}</select></label><label>Especialista<select id="remision-especialista" required disabled><option value="">Primero seleccione una especialidad</option></select></label><label>Motivo<textarea id="remision-motivo" rows="4" minlength="3" maxlength="2000" required placeholder="Motivo clínico de la remisión"></textarea></label><button class="btn btn-primary" type="submit">Crear remisión</button></form>`);
    const espSel=m.element.querySelector("#remision-especialidad"),medSel=m.element.querySelector("#remision-especialista");
    espSel.onchange=async()=>{medSel.disabled=true;medSel.innerHTML='<option value="">Cargando…</option>';if(!espSel.value){medSel.innerHTML='<option value="">Primero seleccione una especialidad</option>';return;}try{const meds=await apiGet(`/especialistas?id_especialidad=${espSel.value}`);medSel.innerHTML=`<option value="">Seleccione…</option>${meds.map(x=>`<option value="${x.numero_documento_usuario}">${escapeHtml(x.nombres)} ${escapeHtml(x.apellidos)}</option>`).join("")}`;medSel.disabled=false;if(!meds.length)showToast("No hay especialistas activos en esa especialidad","warning");}catch(e){showToast(e.message,"error")}};
    m.element.querySelector("#remision-form").onsubmit=async e=>{e.preventDefault();try{const r=await apiPost("/remisiones",{id_paciente:Number(paciente.numero_documento_paciente),id_encuentro:Number(idEncuentro),especialista_destino:Number(medSel.value),id_especialidad:Number(espSel.value),motivo:m.element.querySelector("#remision-motivo").value.trim()});showToast(`Remisión #${r.id} creada`,"success");m.close();if(onCreated)await onCreated(r);}catch(err){showToast(err.message,"error")}};
  }catch(e){showToast(e.message,"error")}
}

const estadoMeta={
  pendiente:{label:"Pendiente",cls:"warning"},
  aceptada:{label:"Aceptada",cls:"success"},
  rechazada:{label:"Rechazada",cls:"danger"},
  finalizada:{label:"Finalizada",cls:"info"}
};

// NUEVO: insignia de estado reutilizable
function badgeEstado(estado){
  const meta=estadoMeta[estado]||{label:estado,cls:"info"};
  return `<span class="badge ${meta.cls}">${escapeHtml(meta.label)}</span>`;
}

export async function renderResumenRemisionesMedico(documento,container){
  if(!container)return;
  container.innerHTML='<div class="card"><div class="muted">Cargando remisiones…</div></div>';
  try{
    const rows=(await apiGet("/remisiones")).filter(r=>Number(r.id_paciente)===Number(documento));
    if(!rows.length){
      container.innerHTML='<div class="card"><div class="section-head"><div><h3>Remisiones</h3><p class="muted">Este paciente todavía no tiene remisiones creadas por usted.</p></div></div></div>';
      return;
    }
    container.innerHTML=`<div class="card"><div class="section-head"><div><h3>Remisiones</h3><p class="muted">Seguimiento de las remisiones que usted ha generado para este paciente.</p></div></div><div class="compact-list">${rows.map(r=>`<div class="compact-row"><div><strong>${escapeHtml(r.especialidad)}</strong><div class="muted small-text">Especialista: ${escapeHtml(r.especialista_nombres)} ${escapeHtml(r.especialista_apellidos)} · ${formatDate(r.fecha_remision)}</div><div class="small-text">${escapeHtml(r.motivo)}</div>${r.observacion_respuesta?`<div class="muted small-text">Respuesta: ${escapeHtml(r.observacion_respuesta)}</div>`:""}</div>${badgeEstado(r.estado)}</div>`).join("")}</div></div>`;
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

// Vista del especialista. NUEVO: la tarjeta lleva data-vista-remisiones="especialista"
// para que el listener de abajo sepa que la lista está en pantalla.
export async function renderRemisiones(container){
  container.innerHTML='<div class="card">Cargando remisiones…</div>';
  try{
    const rows=await apiGet("/remisiones");
    if(!rows.length){container.innerHTML='<div class="card" data-vista-remisiones="especialista"><h2>Mis remisiones</h2><div class="empty-state">No hay remisiones asignadas.</div></div>';return;}
    container.innerHTML=`<div class="card" data-vista-remisiones="especialista"><div class="section-head"><div><h2>Mis remisiones</h2><p class="muted">Acepte una remisión antes de abrir la historia clínica del paciente.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Fecha</th><th>Paciente</th><th>Especialidad</th><th>Motivo</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${formatDate(row.fecha_remision)}</td><td>${escapeHtml(row.paciente_nombres)} ${escapeHtml(row.paciente_apellidos)}<div class="muted small-text">${row.id_paciente}</div></td><td>${escapeHtml(row.especialidad)}</td><td>${escapeHtml(row.motivo)}</td><td>${badgeEstado(row.estado)}</td><td><div class="actions">${row.estado==="pendiente"?`<button class="btn btn-success" data-accept="${row.id_remision}">Aceptar</button><button class="btn btn-danger" data-reject="${row.id_remision}">Rechazar</button>`:""}${row.estado==="aceptada"?`<button class="btn btn-primary" data-open="${row.id_paciente}">Atender paciente</button>`:""}</div></td></tr>`).join("")}</tbody></table></div></div>`;
    container.querySelectorAll("[data-accept]").forEach(b=>b.onclick=async()=>{try{await apiPatch(`/remisiones/${b.dataset.accept}/aceptar`,{observacion:"Remisión aceptada para valoración especializada"});showToast("Remisión aceptada","success");renderRemisiones(container);}catch(e){showToast(e.message,"error")}});
    container.querySelectorAll("[data-reject]").forEach(b=>b.onclick=async()=>{const reason=prompt("Motivo del rechazo (opcional):")||null;try{await apiPatch(`/remisiones/${b.dataset.reject}/rechazar`,{observacion:reason});showToast("Remisión rechazada","success");renderRemisiones(container);}catch(e){showToast(e.message,"error")}});
    container.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>renderPacienteWorkspace(container,{documento:Number(b.dataset.open)}));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

// NUEVO: vista del médico con todas las remisiones que ha enviado (R16).
// El backend ya filtra: un médico solo recibe las suyas en GET /remisiones.
export async function renderRemisionesEnviadas(container){
  container.innerHTML='<div class="card">Cargando remisiones…</div>';
  try{
    const rows=await apiGet("/remisiones");
    if(!rows.length){container.innerHTML='<div class="card" data-vista-remisiones="medico"><h2>Remisiones enviadas</h2><div class="empty-state">Todavía no ha remitido pacientes.</div></div>';return;}
    container.innerHTML=`<div class="card" data-vista-remisiones="medico"><div class="section-head"><div><h2>Remisiones enviadas</h2><p class="muted">El estado se actualiza solo cuando el especialista responde.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Fecha</th><th>Paciente</th><th>Especialidad</th><th>Especialista</th><th>Estado</th><th>Respuesta</th><th></th></tr></thead><tbody>${rows.map(r=>`<tr><td>${formatDate(r.fecha_remision)}</td><td>${escapeHtml(r.paciente_nombres)} ${escapeHtml(r.paciente_apellidos)}<div class="muted small-text">${r.id_paciente}</div></td><td>${escapeHtml(r.especialidad)}</td><td>${escapeHtml(r.especialista_nombres)} ${escapeHtml(r.especialista_apellidos)}</td><td>${badgeEstado(r.estado)}</td><td class="small-text">${r.observacion_respuesta?escapeHtml(r.observacion_respuesta):'<span class="muted">—</span>'}</td><td><button class="btn btn-secondary" data-ver="${Number(r.id_paciente)}" type="button">Ver paciente</button></td></tr>`).join("")}</tbody></table></div></div>`;
    container.querySelectorAll("[data-ver]").forEach(b=>b.onclick=()=>renderPacienteWorkspace(container,{documento:Number(b.dataset.ver)}));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

// NUEVO (R16): las vistas de remisiones se actualizan solas, sin F5.
// Solo se repinta lo que está en pantalla; si el usuario está en otra cosa
// (por ejemplo, atendiendo a un paciente), no se le interrumpe.
const EVENTOS_REMISION=new Set(["remision_recibida","remision_aceptada","remision_rechazada"]);

window.addEventListener("tr:evento",e=>{
  const evento=e.detail;
  if(!EVENTOS_REMISION.has(evento.tipo)) return;

  // Listas completas (especialista o médico), si están visibles.
  document.querySelectorAll("[data-vista-remisiones]").forEach(tarjeta=>{
    const contenedor=tarjeta.parentElement;
    if(tarjeta.dataset.vistaRemisiones==="especialista") renderRemisiones(contenedor);
    else renderRemisionesEnviadas(contenedor);
  });

  // Tarjeta "Remisiones" dentro de la ficha del paciente afectado (médico).
  document.querySelectorAll("#patient-referrals[data-documento]").forEach(seccion=>{
    if(Number(seccion.dataset.documento)===Number(evento.paciente_id)){
      renderResumenRemisionesMedico(seccion.dataset.documento,seccion);
    }
  });
});