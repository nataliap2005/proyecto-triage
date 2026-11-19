// remisiones_externas.js — R30: remisiones que llegan de la institución socio.
// Se muestran debajo de "Mis remisiones" del especialista. Aceptar o rechazar
// le devuelve al socio un Task FHIR (accepted / rejected) desde el backend.
// Todo lo que viene del socio es texto externo: siempre pasa por escapeHtml.
import {apiGet,apiPatch,apiPost} from "./api.js";
import {escapeHtml,formatDate,modal,showToast} from "./ui.js";

const ESTADOS={
  pendiente:{label:"Pendiente",cls:"warning"},
  aceptada:{label:"Aceptada",cls:"success"},
  rechazada:{label:"Rechazada",cls:"danger"},
};
const PRIORIDADES={routine:"Rutina",urgent:"Urgente",asap:"Lo antes posible",stat:"Inmediata"};
const GENEROS={female:"Femenino",male:"Masculino",other:"Otro",unknown:"Sin dato"};

const badge=(meta,texto)=>`<span class="badge ${meta.cls}">${escapeHtml(texto??meta.label)}</span>`;

function paciente(r){
  const p=(r.resumen&&r.resumen.paciente)||{};
  const nombre=p.nombre?escapeHtml(p.nombre):`<em>Paciente externo</em>`;
  const extra=[p.genero?GENEROS[p.genero]||p.genero:null,p.nacimiento?`nac. ${p.nacimiento}`:null].filter(Boolean);
  return `${nombre}${extra.length?`<div class="muted small-text">${escapeHtml(extra.join(" · "))}</div>`:""}`;
}

function respuesta(r){
  if(r.estado==="pendiente") return '<span class="muted small-text">Sin responder</span>';
  const entrega=r.respuesta_enviada
    ?'<span class="badge success">Entregada al socio</span>'
    :`<span class="badge warning">Sin entregar</span> <button class="btn btn-secondary" type="button" data-reenviar="${Number(r.id_remision_externa)}">Reintentar envío</button>`;
  return `${r.observacion_respuesta?`<div class="small-text">${escapeHtml(r.observacion_respuesta)}</div>`:""}<div class="small-text">${entrega}</div>`;
}

function verDatos(r){
  const res=r.resumen||{};
  const obs=res.observaciones||[];
  const reps=res.reportes||[];
  const cons=res.consentimiento;
  modal(`Remisión externa #${Number(r.id_remision_externa)}`,`
    <div class="stack-form">
      <p><strong>Institución:</strong> ${escapeHtml(r.institucion)}<br>
         <strong>Especialidad:</strong> ${escapeHtml(r.especialidad||"No indicada")}
         ${r.prioridad?` · <strong>Prioridad:</strong> ${escapeHtml(PRIORIDADES[r.prioridad]||r.prioridad)}`:""}<br>
         <strong>Recibida:</strong> ${formatDate(r.fecha_recepcion)}</p>
      <p><strong>Motivo:</strong> ${escapeHtml(r.motivo)}</p>
      <h4>Observaciones (LOINC)</h4>
      ${obs.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>LOINC</th><th>Observación</th><th>Valor</th></tr></thead><tbody>${obs.map(o=>`<tr><td>${escapeHtml(o.loinc||"—")}</td><td>${escapeHtml(o.nombre||"—")}</td><td>${escapeHtml(o.valor??"—")} ${escapeHtml(o.unidad||"")}</td></tr>`).join("")}</tbody></table></div>`:'<p class="muted">Sin observaciones.</p>'}
      <h4>Reporte de IA aprobado</h4>
      ${reps.length?reps.map(x=>`<p>${escapeHtml(x.nombre||"Reporte")}${x.conclusion?`: <strong>${escapeHtml(x.conclusion)}</strong>`:""} <span class="muted small-text">(${escapeHtml(x.estado||"")}${x.emitido?` · ${escapeHtml(formatDate(x.emitido))}`:""})</span></p>`).join(""):'<p class="muted">El socio no envió reportes.</p>'}
      <h4>Consentimiento del paciente</h4>
      <p>${cons?`${badge({cls:cons.estado==="active"?"success":"warning"},cons.estado==="active"?"Vigente":cons.estado)}${cons.inicio?` desde ${escapeHtml(formatDate(cons.inicio))}`:""}${cons.fin?` hasta ${escapeHtml(formatDate(cons.fin))}`:" · sin fecha de vencimiento"}`:'<span class="muted">No incluido</span>'}</p>
    </div>`);
}

async function decidir(id,accion,seccion){
  let observacion=null;
  if(accion==="rechazar"){
    observacion=prompt("Motivo del rechazo (se le envía a la institución socio):");
    if(observacion===null) return;
  }else{
    observacion="Remisión aceptada para valoración especializada";
  }
  try{
    const r=await apiPatch(`/remisiones-externas/${id}/${accion}`,{observacion:observacion||null});
    if(r.respuesta_enviada) showToast(`Remisión ${r.estado}; la institución socio ya recibió la respuesta`,"success",5000);
    else showToast(`Remisión ${r.estado}, pero la respuesta no se entregó: ${r.detalle}`,"warning",8000);
  }catch(e){showToast(e.message,"error");}
  await renderRemisionesExternas(seccion);
}

export async function renderRemisionesExternas(seccion){
  if(!seccion) return;
  try{
    const rows=await apiGet("/remisiones-externas");
    seccion.innerHTML=`<div class="card"><div class="section-head"><div><h2>Remisiones de otras instituciones</h2><p class="muted">Llegan por FHIR desde la institución socio. Al aceptar o rechazar, la respuesta le llega a ellos automáticamente.</p></div></div>${
      rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Recibida</th><th>Institución</th><th>Paciente</th><th>Especialidad</th><th>Motivo</th><th>Estado</th><th>Respuesta</th><th>Acciones</th></tr></thead><tbody>${rows.map(r=>`<tr>
        <td>${formatDate(r.fecha_recepcion)}</td>
        <td>${escapeHtml(r.institucion)}</td>
        <td>${paciente(r)}</td>
        <td>${escapeHtml(r.especialidad||"No indicada")}${r.prioridad&&r.prioridad!=="routine"?`<div>${badge({cls:"danger"},PRIORIDADES[r.prioridad]||r.prioridad)}</div>`:""}</td>
        <td class="small-text">${escapeHtml(r.motivo)}</td>
        <td>${badge(ESTADOS[r.estado]||{cls:"info",label:r.estado})}</td>
        <td>${respuesta(r)}</td>
        <td><div class="actions"><button class="btn btn-secondary" type="button" data-ver="${Number(r.id_remision_externa)}">Ver datos</button>${r.estado==="pendiente"?`<button class="btn btn-success" type="button" data-aceptar="${Number(r.id_remision_externa)}">Aceptar</button><button class="btn btn-danger" type="button" data-rechazar="${Number(r.id_remision_externa)}">Rechazar</button>`:""}</div></td>
      </tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No hay remisiones de otras instituciones.</div>'
    }</div>`;
    const porId=new Map(rows.map(r=>[String(r.id_remision_externa),r]));
    seccion.querySelectorAll("[data-ver]").forEach(b=>b.onclick=()=>verDatos(porId.get(b.dataset.ver)));
    seccion.querySelectorAll("[data-aceptar]").forEach(b=>b.onclick=()=>{b.disabled=true;decidir(b.dataset.aceptar,"aceptar",seccion);});
    seccion.querySelectorAll("[data-rechazar]").forEach(b=>b.onclick=()=>decidir(b.dataset.rechazar,"rechazar",seccion));
    seccion.querySelectorAll("[data-reenviar]").forEach(b=>b.onclick=async()=>{
      b.disabled=true;
      try{
        const r=await apiPost(`/remisiones-externas/${b.dataset.reenviar}/reenviar-respuesta`,{});
        showToast(r.respuesta_enviada?"La institución socio recibió la respuesta":`No se entregó: ${r.detalle}`,r.respuesta_enviada?"success":"warning",6000);
      }catch(e){showToast(e.message,"error");}
      await renderRemisionesExternas(seccion);
    });
  }catch(e){
    seccion.innerHTML=`<div class="error-box">No se pudieron cargar las remisiones externas: ${escapeHtml(e.message)}</div>`;
  }
}

// Se agrega debajo de la tarjeta de remisiones internas, en el mismo contenedor.
export function anexarRemisionesExternas(container){
  const seccion=document.createElement("div");
  seccion.dataset.remisionesExternas="";
  seccion.style.marginTop="1rem";
  container.appendChild(seccion);
  renderRemisionesExternas(seccion);
}

// En vivo (R17): una remisión externa nueva repinta la sección si está en pantalla.
window.addEventListener("tr:evento",e=>{
  if(e.detail?.tipo!=="remision_externa_recibida") return;
  document.querySelectorAll("[data-remisiones-externas]").forEach(s=>renderRemisionesExternas(s));
});
