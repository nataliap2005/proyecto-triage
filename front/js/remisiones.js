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

export async function renderResumenRemisionesMedico(documento,container){
  if(!container)return;
  container.innerHTML='<div class="card"><div class="muted">Cargando remisiones…</div></div>';
  try{
    const rows=(await apiGet("/remisiones")).filter(r=>Number(r.id_paciente)===Number(documento));
    if(!rows.length){
      container.innerHTML='<div class="card"><div class="section-head"><div><h3>Remisiones</h3><p class="muted">Este paciente todavía no tiene remisiones creadas por usted.</p></div></div></div>';
      return;
    }
    container.innerHTML=`<div class="card"><div class="section-head"><div><h3>Remisiones</h3><p class="muted">Seguimiento de las remisiones que usted ha generado para este paciente.</p></div></div><div class="compact-list">${rows.map(r=>{const meta=estadoMeta[r.estado]||{label:r.estado,cls:"info"};return `<div class="compact-row"><div><strong>${escapeHtml(r.especialidad)}</strong><div class="muted small-text">Especialista: ${escapeHtml(r.especialista_nombres)} ${escapeHtml(r.especialista_apellidos)} · ${formatDate(r.fecha_remision)}</div><div class="small-text">${escapeHtml(r.motivo)}</div>${r.observacion_respuesta?`<div class="muted small-text">Respuesta: ${escapeHtml(r.observacion_respuesta)}</div>`:""}</div><span class="badge ${meta.cls}">${escapeHtml(meta.label)}</span></div>`}).join("")}</div></div>`;
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

export async function renderRemisiones(container){
  container.innerHTML='<div class="card">Cargando remisiones…</div>';
  try{
    const rows=await apiGet("/remisiones");
    if(!rows.length){container.innerHTML='<div class="card"><h2>Mis remisiones</h2><div class="empty-state">No hay remisiones asignadas.</div></div>';return;}
    container.innerHTML=`<div class="card"><div class="section-head"><div><h2>Mis remisiones</h2><p class="muted">Acepte una remisión antes de abrir la historia clínica del paciente.</p></div></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Fecha</th><th>Paciente</th><th>Especialidad</th><th>Motivo</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${formatDate(row.fecha_remision)}</td><td>${escapeHtml(row.paciente_nombres)} ${escapeHtml(row.paciente_apellidos)}<div class="muted small-text">${row.id_paciente}</div></td><td>${escapeHtml(row.especialidad)}</td><td>${escapeHtml(row.motivo)}</td><td><span class="badge info">${escapeHtml(row.estado)}</span></td><td><div class="actions">${row.estado==="pendiente"?`<button class="btn btn-success" data-accept="${row.id_remision}">Aceptar</button><button class="btn btn-danger" data-reject="${row.id_remision}">Rechazar</button>`:""}${row.estado==="aceptada"?`<button class="btn btn-primary" data-open="${row.id_paciente}">Atender paciente</button>`:""}</div></td></tr>`).join("")}</tbody></table></div></div>`;
    container.querySelectorAll("[data-accept]").forEach(b=>b.onclick=async()=>{try{await apiPatch(`/remisiones/${b.dataset.accept}/aceptar`,{observacion:"Remisión aceptada para valoración especializada"});showToast("Remisión aceptada","success");renderRemisiones(container);}catch(e){showToast(e.message,"error")}});
    container.querySelectorAll("[data-reject]").forEach(b=>b.onclick=async()=>{const reason=prompt("Motivo del rechazo (opcional):")||null;try{await apiPatch(`/remisiones/${b.dataset.reject}/rechazar`,{observacion:reason});showToast("Remisión rechazada","success");renderRemisiones(container);}catch(e){showToast(e.message,"error")}});
    container.querySelectorAll("[data-open]").forEach(b=>b.onclick=()=>renderPacienteWorkspace(container,{documento:Number(b.dataset.open)}));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
