import {apiGet} from "./api.js";
import {isRole} from "./auth.js";
import {escapeHtml,formatDate,triageBadge} from "./ui.js";
import {nuevoEncuentroModal,bindEncounterActions,deleteButtonHtml,VITALES} from "./encuentro.js";

const val=v=>escapeHtml(v??"—");
const NIVELES={1:"Resucitación · atención inmediata",2:"Emergencia",3:"Urgente",4:"Menos urgente",5:"No urgente"};
const ESTADOS={en_triage:"EN TRIAGE",en_atencion:"EN ATENCIÓN",en_observacion:"EN OBSERVACIÓN",finalizado:"FINALIZADO"};

export async function renderEncuentroActual(documento,container){
  container.innerHTML='<div class="card">Cargando encuentro actual…</div>';
  const refresh=()=>renderEncuentroActual(documento,container);
  try{
    const [h,reportes]=await Promise.all([
      apiGet(`/pacientes/${documento}/historia-clinica`),
      apiGet("/reportes-previos").catch(()=>[])
    ]);
    const reporte=(reportes||[]).find(r=>Number(r.id_paciente)===Number(documento))||null; // vienen del más reciente al más antiguo
    const enc=(h.encuentros||[]).find(e=>e.estado!=="finalizado")||null;
    container.innerHTML=`${reportCard(reporte)}${enc?encounterView(enc,reporte):noEncounter()}`;
    container.querySelector("#btn-iniciar")?.addEventListener("click",()=>nuevoEncuentroModal(documento,refresh));
    bindEncounterActions(container,refresh);
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

function reportCard(r){
  if(!r) return `<div class="card flow-card"><div class="section-head"><h3>1 · Reporte previo del paciente</h3><span class="badge">Sin reporte</span></div><div class="history-empty">El paciente no registró un reporte previo antes de llegar.</div></div>`;
  return `<div class="card flow-card"><div class="section-head"><h3>1 · Reporte previo del paciente</h3><span class="muted small-text">${formatDate(r.fecha_hora_reporte)}</span></div><div class="clinical-block"><h4>Síntoma principal</h4><div>${val(r.sintoma_principal)}</div>${r.evolucion?`<div class="muted small-text">Evolución: ${val(r.evolucion)}</div>`:""}${r.inicio_sintomas?`<div class="muted small-text">Inicio: ${formatDate(r.inicio_sintomas)}</div>`:""}${r.signos_alarma_presentes?`<div style="margin-top:.4rem"><span class="badge danger">Signos de alarma</span> ${val(r.descripcion_signos_alarma)}</div>`:""}${r.municipio_origen?`<div class="muted small-text">Origen: ${val(r.municipio_origen)}${r.distancia_aproximada_km!=null?` · ${val(r.distancia_aproximada_km)} km`:""}${r.tiempo_desplazamiento_min!=null?` · ${val(r.tiempo_desplazamiento_min)} min`:""}</div>`:""}</div></div>`;
}

function noEncounter(){
  return `<div class="card flow-card"><div class="empty-state"><strong>No hay un encuentro activo</strong><p>Cuando el paciente llegue al hospital, inicie el encuentro para poder realizar el triage.</p>${isRole("Medico")?'<button id="btn-iniciar" class="btn btn-primary" type="button">+ Iniciar encuentro</button>':""}</div></div>`;
}

function lastVitals(obs){
  const map={};
  for(const o of obs) if(o.codigo_loinc) map[o.codigo_loinc]=o; // ordenadas por fecha: queda la última
  return map;
}

function encounterView(e,reporte){
  const obs=e.observaciones||[], dx=e.diagnosticos||[], notas=e.notas_clinicas||[], ex=e.examenes||[], rx=e.prescripciones||[];
  const vit=lastVitals(obs), vitCodes=new Set(VITALES.map(v=>v.loinc));
  const otras=obs.filter(o=>!vitCodes.has(o.codigo_loinc));
  const tieneTriage=!!e.nivel_triage, tieneVit=VITALES.some(v=>vit[v.loinc]);
  const atencion=dx.length+notas.length+ex.length+rx.length;
  const steps=[
    ["Reporte previo",!!reporte,false],
    ["Triage",tieneTriage,!tieneTriage],
    ["Signos vitales",tieneVit,tieneTriage&&!tieneVit],
    ["Atención clínica",atencion>0,tieneTriage&&tieneVit&&!atencion],
    ["Finalizar",false,tieneTriage&&tieneVit&&atencion>0],
  ];
  const id=e.id_encuentro, med=isRole("Medico"), clinical=isRole("Medico","Especialista");
  const btnClinical=(attr,label,cls="btn-secondary")=>clinical?`<button class="btn ${cls}" data-${attr}="${id}" type="button">${label}</button>`:"";
  const btnMed=(attr,label,cls="btn-secondary")=>med?`<button class="btn ${cls}" data-${attr}="${id}" type="button">${label}</button>`:"";
  return `
  <div class="card flow-card"><div class="section-head"><div><h2>Encuentro actual #${id}</h2><div class="muted small-text">Ingreso ${formatDate(e.fecha_hora_ingreso)} · ${val(e.servicio)}</div></div><span class="badge info">${ESTADOS[e.estado]||val(e.estado)}</span></div>
    <div class="flow-steps">${steps.map(([t,done,cur],i)=>`<div class="flow-step ${done?"done":""} ${cur?"current":""}"><span>${done?"✓":i+1}</span> ${t}</div>`).join("")}</div>
    <div class="clinical-block" style="margin-top:1rem"><h4>Motivo de consulta</h4><div>${val(e.motivo_consulta)}</div></div></div>

  <div class="card flow-card"><div class="section-head"><h3>2 · Triage</h3>${btnMed("triage",tieneTriage?"Actualizar triage":"Realizar triage","btn-primary")}</div>
    ${tieneTriage?`<div class="triage-panel">${triageBadge(e.nivel_triage)}<div><strong>Nivel ${e.nivel_triage} · ${NIVELES[e.nivel_triage]}</strong><div class="muted small-text">${e.dolor_escala!=null?`Dolor ${e.dolor_escala}/10 · `:""}Clasificado ${formatDate(e.fecha_hora_triage)}</div>${e.observaciones_triage?`<div class="small-text">${val(e.observaciones_triage)}</div>`:""}</div></div>`:'<div class="history-empty">Triage pendiente: revise el reporte previo, valore al paciente y asigne el nivel 1 a 5.</div>'}</div>

  <div class="card flow-card"><div class="section-head"><h3>3 · Signos vitales</h3>${btnClinical("add-vitales","+ Registrar signos vitales")}</div>
    ${tieneVit?`<div class="vitals-grid">${VITALES.filter(v=>vit[v.loinc]).map(v=>`<div class="metric"><strong>${val(vit[v.loinc].valor_numerico)} <small>${v.show}</small></strong><span>${v.label}</span></div>`).join("")}</div>`:'<div class="history-empty">Aún no hay signos vitales registrados.</div>'}
    ${otras.length?`<div class="compact-list" style="margin-top:.8rem">${otras.map(o=>`<div class="compact-row"><span><strong>${val(o.nombre)}</strong>: ${val(o.valor_numerico??o.valor_texto)} ${val(o.unidad||"")}</span>${deleteButtonHtml("observacion",o.id_observacion)}</div>`).join("")}</div>`:""}
    <div style="margin-top:.6rem">${btnClinical("add-obs","+ Otra observación","btn-ghost")}</div></div>

  <div class="card flow-card"><div class="section-head"><h3>4 · Atención clínica</h3><div class="actions">${btnClinical("add-dx","+ Diagnóstico")}${btnClinical("add-nota","+ Nota")}${btnClinical("add-examen","+ Examen")}${btnClinical("add-rx","+ Prescripción")}</div></div>
    <div class="grid grid-2">
      ${block("Diagnósticos",dx,d=>`<strong>${val(d.codigo_cie10||"")}</strong> ${val(d.descripcion)} <span class="muted small-text">${val(d.tipo)}</span>`,"diagnostico","id_diagnostico")}
      ${block("Notas clínicas",notas,n=>val(n.contenido),"nota","id_nota")}
      ${block("Exámenes",ex,x=>`<strong>${val(x.nombre)}</strong> · ${val(x.estado)}`,"examen","id_examen")}
      ${block("Prescripciones",rx,p=>`<strong>${val(p.medicamento||p.codigo_cum)}</strong> ${val(p.dosis||"")} ${val(p.frecuencia||"")}`,"prescripcion","id_prescripcion")}
    </div></div>

  ${med?`<div class="card flow-card"><div class="section-head"><div><h3>5 · Finalizar encuentro</h3><div class="muted small-text">Al finalizar ya no se podrá editar y quedará disponible para facturación.</div></div><button class="btn btn-danger" data-finalizar="${id}" type="button">Finalizar encuentro</button></div></div>`:""}`;
}
function block(titulo,items,fn,tipo,idKey){
  return `<div class="clinical-block"><h4>${titulo}</h4>${items.length?`<div class="compact-list">${items.map(i=>`<div class="compact-row"><span>${fn(i)}</span>${deleteButtonHtml(tipo,i[idKey])}</div>`).join("")}</div>`:'<div class="history-empty">Sin registros.</div>'}</div>`;
}
