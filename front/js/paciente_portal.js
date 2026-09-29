import {apiGet,apiPost} from "./api.js";
import {getCurrentUser} from "./auth.js";
import {escapeHtml,formatDate,showToast,modal,triageBadge} from "./ui.js";

const val=v=>escapeHtml(v??"—");

/* ---------- Mis reportes ---------- */
export async function renderMisReportes(container){
  container.innerHTML='<div class="card">Cargando reportes…</div>';
  const refresh=()=>renderMisReportes(container);
  try{
    const rows=await apiGet("/reportes-previos/mios");
    container.innerHTML=`<div class="card"><div class="section-head"><div><h2>Mis reportes</h2><p class="muted">Síntomas que reportó antes de ser atendido.</p></div><button id="new-reporte" class="btn btn-primary" type="button">+ Nuevo reporte</button></div>${rows.length?`<div class="compact-list">${rows.map(r=>`<div class="compact-row" style="display:block"><strong>${val(r.sintoma_principal)}</strong> <span class="muted small-text">${formatDate(r.fecha_hora_reporte)}</span>${r.evolucion?`<div>${val(r.evolucion)}</div>`:""}${r.signos_alarma_presentes?`<div><span class="badge danger">Signos de alarma</span> ${val(r.descripcion_signos_alarma)}</div>`:""}${r.municipio_origen?`<div class="muted small-text">Origen: ${val(r.municipio_origen)}</div>`:""}</div>`).join("")}</div>`:'<div class="empty-state">No ha registrado reportes.</div>'}</div>`;
    container.querySelector("#new-reporte").onclick=()=>nuevoReporteModal(refresh);
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
function nuevoReporteModal(refresh){
  const m=modal("Nuevo reporte",`<form id="f-rep" class="stack-form">
    <label>Síntoma principal<input name="sintoma_principal" required></label>
    <label>Inicio de los síntomas<input name="inicio_sintomas" type="datetime-local"></label>
    <label>Evolución<textarea name="evolucion" rows="2"></textarea></label>
    <label class="check-row"><input type="checkbox" name="signos_alarma_presentes"> Presento signos de alarma</label>
    <label>Descripción de signos de alarma<input name="descripcion_signos_alarma"></label>
    <div class="grid grid-2"><label>Municipio de origen<input name="municipio_origen"></label><label>Ubicación aproximada<input name="ubicacion_aproximada"></label></div>
    <div class="grid grid-2"><label>Distancia (km)<input name="distancia_aproximada_km" type="number" min="0" step="any"></label><label>Tiempo de desplazamiento (min)<input name="tiempo_desplazamiento_min" type="number" min="0"></label></div>
    <button class="btn btn-primary" type="submit">Enviar reporte</button></form>`);
  const f=m.element.querySelector("#f-rep");
  f.onsubmit=async e=>{
    e.preventDefault();
    const g=n=>f.elements[n].value.trim();
    const num=n=>g(n)===""?null:Number(g(n));
    const body={
      id_paciente:Number(getCurrentUser().numero_documento_usuario),
      sintoma_principal:g("sintoma_principal"),
      inicio_sintomas:g("inicio_sintomas")?new Date(g("inicio_sintomas")).toISOString():null,
      evolucion:g("evolucion")||null,
      signos_alarma_presentes:f.elements.signos_alarma_presentes.checked,
      descripcion_signos_alarma:g("descripcion_signos_alarma")||null,
      municipio_origen:g("municipio_origen")||null,
      ubicacion_aproximada:g("ubicacion_aproximada")||null,
      distancia_aproximada_km:num("distancia_aproximada_km"),
      tiempo_desplazamiento_min:num("tiempo_desplazamiento_min")
    };
    if(body.signos_alarma_presentes&&!body.descripcion_signos_alarma){showToast("Describa los signos de alarma","error");return;}
    try{await apiPost("/reportes-previos",body);showToast("Reporte enviado","success");m.close();await refresh();}
    catch(err){showToast(err.message,"error");}
  };
}

/* ---------- Mis encuentros ---------- */
export async function renderMisEncuentros(container){
  container.innerHTML='<div class="card">Cargando encuentros…</div>';
  try{
    const rows=await apiGet("/encuentros/mios");
    container.innerHTML=`<div class="card"><div class="section-head"><div><h2>Mis encuentros</h2><p class="muted">Sus atenciones en el hospital.</p></div></div>${rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>#</th><th>Ingreso</th><th>Servicio</th><th>Motivo</th><th>Triage</th><th>Estado</th><th></th></tr></thead><tbody>${rows.map(e=>`<tr><td>${e.id_encuentro}</td><td>${formatDate(e.fecha_hora_ingreso)}</td><td>${val(e.servicio)}</td><td>${val(e.motivo_consulta)}</td><td>${triageBadge(e.nivel_triage)}</td><td><span class="badge ${e.estado==="finalizado"?"success":"info"}">${val(e.estado)}</span></td><td><button class="btn btn-secondary" data-det="${e.id_encuentro}" type="button">Ver detalle</button></td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No tiene encuentros registrados.</div>'}</div>`;
    container.querySelectorAll("[data-det]").forEach(b=>b.onclick=()=>detalleEncuentro(b.dataset.det));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
async function detalleEncuentro(id){
  try{
    const [dx,obs,notas,ex,rx]=await Promise.all(["diagnosticos","observaciones","notas-clinicas","examenes","prescripciones"].map(x=>apiGet(`/encuentros/${id}/${x}`)));
    const blk=(t,items,fn)=>`<div class="clinical-block"><h4>${t}</h4>${items.length?`<div class="compact-list">${items.map(i=>`<div class="compact-row">${fn(i)}</div>`).join("")}</div>`:'<div class="history-empty">Sin registros.</div>'}</div>`;
    modal(`Encuentro #${id}`,`<div class="stack-form">${blk("Diagnósticos",dx,d=>`<span><strong>${val(d.codigo_cie10||"")}</strong> ${val(d.descripcion)}</span>`)}${blk("Observaciones",obs,o=>`<span><strong>${val(o.nombre||o.tipo_observacion)}</strong>: ${val(o.valor_numerico??o.valor_texto)} ${val(o.unidad||"")}</span>`)}${blk("Notas clínicas",notas,n=>`<span>${val(n.contenido)}</span>`)}${blk("Exámenes",ex,x=>`<span><strong>${val(x.nombre)}</strong> · ${val(x.estado)}${x.resultado?` · ${val(x.resultado)}`:""}</span>`)}${blk("Prescripciones",rx,p=>`<span><strong>${val(p.medicamento||p.codigo_cum)}</strong> ${val(p.dosis||"")} ${val(p.frecuencia||"")}</span>`)}</div>`);
  }catch(e){showToast(e.message,"error");}
}
