import {apiGet,apiPost,apiPut,apiPatch,apiDelete} from "./api.js";
import {escapeHtml,showToast,modal,errorEnFormulario} from "./ui.js";
import {isRole} from "./auth.js";

async function run(fn,successMsg,refresh){
  try{ await fn(); showToast(successMsg,"success"); await refresh(); }
  catch(e){ showToast(e.message,"error"); }
}

function readForm(form){
  const fd=new FormData(form);
  const out={};
  for(const [k,v] of fd.entries()) out[k]=typeof v==="string"?v.trim():v;
  return out;
}
function nullify(obj,keys){ keys.forEach(k=>{ if(obj[k]==="") obj[k]=null; }); return obj; }

/* ---------- Nuevo encuentro ---------- */
export function nuevoEncuentroModal(documento,refresh){
  const m=modal("Nuevo encuentro",`
    <form id="f-encuentro" class="stack-form">
      <label>Motivo de consulta
        <textarea name="motivo_consulta" rows="3" required></textarea>
      </label>
      <div class="grid grid-2">
        <label>Tipo de encuentro
          <select name="tipo_encuentro">
            <option value="urgencias">Urgencias</option>
            <option value="consulta_externa">Consulta externa</option>
            <option value="hospitalizacion">Hospitalización</option>
            <option value="control">Control</option>
          </select>
        </label>
        <label>Servicio
          <input name="servicio" value="URGENCIAS" maxlength="50">
        </label>
      </div>
      <button class="btn btn-primary" type="submit">Crear encuentro</button>
    </form>`);
  m.element.querySelector("#f-encuentro").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_paciente=Number(documento);
    await run(()=>apiPost("/encuentros",body),"Encuentro creado",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Triage ---------- */
function triageModal(idEncuentro,refresh){
  const m=modal("Registrar triage",`
    <form id="f-triage" class="stack-form">
      <label>Nivel de triage (1 a 5)
        <select name="nivel_triage" required>
          <option value="1">1 · Resucitación</option>
          <option value="2">2 · Emergencia</option>
          <option value="3">3 · Urgente</option>
          <option value="4">4 · Menos urgente</option>
          <option value="5">5 · No urgente</option>
        </select>
      </label>
      <label>Escala de dolor (0 a 10, opcional)
        <input name="dolor_escala" type="number" min="0" max="10">
      </label>
      <label>Observaciones del triage
        <textarea name="observaciones_triage" rows="2"></textarea>
      </label>
      <button class="btn btn-primary" type="submit">Guardar triage</button>
    </form>`);
  m.element.querySelector("#f-triage").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.nivel_triage=Number(body.nivel_triage);
    body.dolor_escala=body.dolor_escala===""?null:Number(body.dolor_escala);
    nullify(body,["observaciones_triage"]);
    await run(()=>apiPut(`/encuentros/${idEncuentro}/triage`,body),"Triage registrado",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Observación ---------- */
function observacionModal(idEncuentro,refresh){
  const m=modal("Agregar observación",`
    <form id="f-obs" class="stack-form">
      <div class="grid grid-2">
        <label>Tipo de observación<input name="tipo_observacion" maxlength="100" required></label>
        <label>Código LOINC (opcional)<input name="codigo_loinc" maxlength="30"></label>
      </div>
      <label>Nombre<input name="nombre" maxlength="150" required></label>
      <div class="grid grid-2">
        <label>Valor numérico<input name="valor_numerico" type="number" step="any"></label>
        <label>Unidad<input name="unidad" maxlength="30"></label>
      </div>
      <label>Valor de texto (use este O el numérico, no ambos)
        <input name="valor_texto">
      </label>
      <button class="btn btn-primary" type="submit">Guardar observación</button>
    </form>`);
  m.element.querySelector("#f-obs").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_encuentro=idEncuentro;
    nullify(body,["codigo_loinc","unidad","valor_texto"]);
    body.valor_numerico=body.valor_numerico===""?null:Number(body.valor_numerico);
    if((body.valor_numerico===null)===(body.valor_texto===null)){
      errorEnFormulario(e.target,"Ingrese exactamente un valor: numérico o de texto"); return;
    }
    errorEnFormulario(e.target,[]);
    try{ await apiPost("/observaciones",body); }
    catch(err){ errorEnFormulario(e.target,err.message); return; }
    showToast("Observación registrada","success"); m.close(); await refresh();
  };
}


/* ---------- Signos vitales (varias observaciones de una vez) ---------- */
// min/max: valores fisiológicamente POSIBLES (los mismos que valida la API), no valores normales.
export const VITALES=[
  {key:"pas",loinc:"8480-6",nombre:"Presión arterial sistólica",unidad:"mm[Hg]",label:"PA sistólica",show:"mmHg",min:40,max:300},
  {key:"pad",loinc:"8462-4",nombre:"Presión arterial diastólica",unidad:"mm[Hg]",label:"PA diastólica",show:"mmHg",min:20,max:200},
  {key:"fc",loinc:"8867-4",nombre:"Frecuencia cardíaca",unidad:"/min",label:"Frecuencia cardíaca",show:"lpm",min:20,max:250},
  {key:"fr",loinc:"9279-1",nombre:"Frecuencia respiratoria",unidad:"/min",label:"Frecuencia respiratoria",show:"rpm",min:4,max:80},
  {key:"temp",loinc:"8310-5",nombre:"Temperatura corporal",unidad:"Cel",label:"Temperatura",show:"°C",min:30,max:44},
  {key:"spo2",loinc:"2708-6",nombre:"Saturación de oxígeno",unidad:"%",label:"Saturación O₂",show:"%",min:50,max:100},
];
function vitalesModal(idEncuentro,refresh){
  const m=modal("Registrar signos vitales",`
    <form id="f-vit" class="stack-form" novalidate>
      <div class="grid grid-2">${VITALES.map(v=>`<label>${v.label} (${v.show})<input name="${v.key}" type="number" step="any" min="${v.min}" max="${v.max}" placeholder="${v.min} a ${v.max}"></label>`).join("")}</div>
      <p class="muted small-text">Complete solo los que midió. Cada valor se guarda como una observación.</p>
      <button class="btn btn-primary" type="submit">Guardar signos vitales</button>
    </form>`);
  m.element.querySelector("#f-vit").onsubmit=async e=>{
    e.preventDefault();
    const f=e.target;
    const llenos=VITALES.filter(v=>f.elements[v.key].value!=="");
    const errores=[];
    VITALES.forEach(v=>f.elements[v.key].removeAttribute("aria-invalid"));
    for(const v of llenos){
      const n=Number(f.elements[v.key].value);
      if(!Number.isFinite(n)||n<v.min||n>v.max){
        errores.push(`${v.label}: ${f.elements[v.key].value} ${v.show} no es un valor posible. Debe estar entre ${v.min} y ${v.max} ${v.show}.`);
        f.elements[v.key].setAttribute("aria-invalid","true");
      }
    }
    const pas=f.elements.pas.value, pad=f.elements.pad.value;
    if(pas!==""&&pad!==""&&Number(pas)<=Number(pad)){
      errores.push(`La PA sistólica (${pas} mmHg) debe ser mayor que la diastólica (${pad} mmHg).`);
      f.elements.pas.setAttribute("aria-invalid","true"); f.elements.pad.setAttribute("aria-invalid","true");
    }
    if(!llenos.length) errores.push("Ingrese al menos un valor.");
    if(errores.length){ errorEnFormulario(f,errores); return; }
    errorEnFormulario(f,[]);
    const boton=f.querySelector("[type=submit]"); boton.disabled=true;
    try{
      // Un solo envío: la API guarda todos los signos o ninguno.
      await apiPost("/observaciones/signos-vitales",{id_encuentro:Number(idEncuentro),
        signos:llenos.map(v=>({codigo_loinc:v.loinc,nombre:v.nombre,valor_numerico:Number(f.elements[v.key].value),unidad:v.unidad}))});
    }catch(err){ errorEnFormulario(f,err.message); boton.disabled=false; return; }
    showToast("Signos vitales registrados","success"); m.close(); await refresh();
  };
}

/* ---------- Diagnóstico ---------- */
function diagnosticoModal(idEncuentro,refresh){
  const m=modal("Agregar diagnóstico",`
    <form id="f-dx" class="stack-form">
      <div class="grid grid-2">
        <label>Código CIE-10 (opcional)<input name="codigo_cie10" maxlength="30"></label>
        <label>Tipo
          <select name="tipo"><option value="principal">Principal</option><option value="secundario">Secundario</option></select>
        </label>
      </div>
      <label>Descripción<input name="descripcion" maxlength="250" required></label>
      <label>Estado clínico
        <select name="estado_clinico">
          <option value="active">Activo</option>
          <option value="recurrence">Recurrencia</option>
          <option value="relapse">Recaída</option>
          <option value="inactive">Inactivo</option>
          <option value="remission">Remisión</option>
          <option value="resolved">Resuelto</option>
        </select>
      </label>
      <button class="btn btn-primary" type="submit">Guardar diagnóstico</button>
    </form>`);
  m.element.querySelector("#f-dx").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_encuentro=idEncuentro;
    nullify(body,["codigo_cie10"]);
    await run(()=>apiPost("/diagnosticos",body),"Diagnóstico registrado",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Nota clínica ---------- */
function notaModal(idEncuentro,refresh){
  const m=modal("Agregar nota clínica",`
    <form id="f-nota" class="stack-form">
      <label>Tipo de nota
        <select name="tipo_nota">
          <option value="evolucion">Evolución</option>
          <option value="valoracion">Valoración</option>
          <option value="nota_clinica">Nota clínica</option>
        </select>
      </label>
      <label>Contenido<textarea name="contenido" rows="4" required></textarea></label>
      <button class="btn btn-primary" type="submit">Guardar nota</button>
    </form>`);
  m.element.querySelector("#f-nota").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_encuentro=idEncuentro;
    await run(()=>apiPost("/notas-clinicas",body),"Nota clínica registrada",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Examen ---------- */
function examenModal(idEncuentro,refresh){
  const m=modal("Solicitar examen",`
    <form id="f-examen" class="stack-form">
      <div class="grid grid-2">
        <label>Código LOINC (opcional)<input name="codigo_loinc" maxlength="30"></label>
        <label>Categoría (opcional)<input name="categoria" maxlength="100"></label>
      </div>
      <label>Nombre del examen<input name="nombre" maxlength="150" required></label>
      <button class="btn btn-primary" type="submit">Solicitar examen</button>
    </form>`);
  m.element.querySelector("#f-examen").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_encuentro=idEncuentro;
    nullify(body,["codigo_loinc","categoria"]);
    await run(()=>apiPost("/examenes",body),"Examen solicitado",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Prescripción ---------- */
async function prescripcionModal(idEncuentro,refresh){
  let medicamentos=[];
  try{ medicamentos=await apiGet("/medicamentos"); }
  catch(e){ showToast(e.message,"error"); return; }
  const opciones=medicamentos.map(x=>`<option value="${escapeHtml(x.codigo_cum)}">${escapeHtml(x.nombre)} · ${escapeHtml(x.concentracion||"")} (${escapeHtml(x.codigo_cum)})</option>`).join("");
  const m=modal("Crear prescripción",`
    <form id="f-rx" class="stack-form">
      <label>Medicamento
        <select name="codigo_cum" required>${opciones||'<option value="">No hay medicamentos registrados</option>'}</select>
      </label>
      <div class="grid grid-2">
        <label>Dosis<input name="dosis" maxlength="100"></label>
        <label>Frecuencia<input name="frecuencia" maxlength="100"></label>
      </div>
      <div class="grid grid-2">
        <label>Vía de administración<input name="via_administracion" maxlength="50"></label>
        <label>Cantidad<input name="cantidad" type="number" min="1" required></label>
      </div>
      <button class="btn btn-primary" type="submit">Crear prescripción</button>
    </form>`);
  m.element.querySelector("#f-rx").onsubmit=async e=>{
    e.preventDefault();
    const body=readForm(e.target);
    body.id_encuentro=idEncuentro;
    body.cantidad=Number(body.cantidad);
    nullify(body,["dosis","frecuencia","via_administracion"]);
    await run(()=>apiPost("/prescripciones",body),"Prescripción creada",async()=>{ m.close(); await refresh(); });
  };
}

/* ---------- Finalizar encuentro ---------- */
async function finalizarEncuentro(idEncuentro,refresh){
  if(!confirm("¿Finalizar este encuentro? No podrá seguir editándolo.")) return;
  await run(()=>apiPatch(`/encuentros/${idEncuentro}/finalizar`),"Encuentro finalizado",refresh);
}

/* ---------- Eliminar registro clínico ---------- */
async function eliminarRegistro(tipo,id,refresh){
  const rutas={
    antecedente:`/antecedentes/${id}`,
    observacion:`/observaciones/${id}`,
    diagnostico:`/diagnosticos/${id}`,
    nota:`/notas-clinicas/${id}`,
    examen:`/examenes/${id}`,
    prescripcion:`/prescripciones/${id}`,
  };
  if(!confirm("¿Eliminar este registro?")) return;
  await run(()=>apiDelete(rutas[tipo]),"Registro eliminado",refresh);
}

/* ---------- Toolbar del encabezado (Nuevo encuentro) ---------- */
export function renderHistoriaToolbar(documento,refresh){
  if(!isRole("Medico")) return "";
  return `<button id="btn-nuevo-encuentro" class="btn btn-primary" type="button">+ Nuevo encuentro</button>`;
}
export function bindHistoriaToolbar(container,documento,refresh){
  container.querySelector("#btn-nuevo-encuentro")?.addEventListener("click",()=>nuevoEncuentroModal(documento,refresh));
}

/* ---------- Acciones dentro de cada encuentro ---------- */
export function encounterActionsHtml(e){
  if(!isRole("Medico","Especialista")) return "";
  const activo=e.estado!=="finalizado";
  if(!activo) return "";
  const botones=[];
  if(isRole("Medico")) botones.push(`<button class="btn btn-secondary" data-triage="${e.id_encuentro}" type="button">Registrar triage</button>`);
  botones.push(`<button class="btn btn-secondary" data-add-obs="${e.id_encuentro}" type="button">+ Observación</button>`);
  botones.push(`<button class="btn btn-secondary" data-add-dx="${e.id_encuentro}" type="button">+ Diagnóstico</button>`);
  botones.push(`<button class="btn btn-secondary" data-add-nota="${e.id_encuentro}" type="button">+ Nota</button>`);
  botones.push(`<button class="btn btn-secondary" data-add-examen="${e.id_encuentro}" type="button">+ Examen</button>`);
  if(isRole("Medico")) botones.push(`<button class="btn btn-secondary" data-add-rx="${e.id_encuentro}" type="button">+ Prescripción</button>`);
  if(isRole("Medico")) botones.push(`<button class="btn btn-danger" data-finalizar="${e.id_encuentro}" type="button">Finalizar encuentro</button>`);
  return `<div class="actions encounter-actions">${botones.join("")}</div>`;
}
export function deleteButtonHtml(tipo,id){
  if(!isRole("Medico","Especialista")) return "";
  return `<button class="btn btn-ghost icon-btn-sm" data-del-tipo="${tipo}" data-del-id="${id}" type="button" title="Eliminar" aria-label="Eliminar">✕</button>`;
}
export function bindEncounterActions(container,refresh){
  container.querySelectorAll("[data-triage]").forEach(b=>b.onclick=()=>triageModal(b.dataset.triage,refresh));
  container.querySelectorAll("[data-add-obs]").forEach(b=>b.onclick=()=>observacionModal(b.dataset.addObs,refresh));
  container.querySelectorAll("[data-add-vitales]").forEach(b=>b.onclick=()=>vitalesModal(b.dataset.addVitales,refresh));
  container.querySelectorAll("[data-add-dx]").forEach(b=>b.onclick=()=>diagnosticoModal(b.dataset.addDx,refresh));
  container.querySelectorAll("[data-add-nota]").forEach(b=>b.onclick=()=>notaModal(b.dataset.addNota,refresh));
  container.querySelectorAll("[data-add-examen]").forEach(b=>b.onclick=()=>examenModal(b.dataset.addExamen,refresh));
  container.querySelectorAll("[data-add-rx]").forEach(b=>b.onclick=()=>prescripcionModal(b.dataset.addRx,refresh));
  container.querySelectorAll("[data-finalizar]").forEach(b=>b.onclick=()=>finalizarEncuentro(b.dataset.finalizar,refresh));
  container.querySelectorAll("[data-del-tipo]").forEach(b=>b.onclick=()=>eliminarRegistro(b.dataset.delTipo,b.dataset.delId,refresh));
}
