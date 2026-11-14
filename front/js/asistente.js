// asistente.js — Semana 12 · Chat del asistente clínico RAG (POST /rag/preguntar).
// Dos entradas:
//   · Vista "Asistente clínico" del menú: consulta guías y, si se indica, la historia de un paciente.
//   · Pestaña "Asistente clínico" de la ficha del paciente: el paciente ya viene fijado.
// El backend valida rol, acceso al paciente y seudonimiza; aquí solo se muestra la respuesta
// con sus citas [F#] enlazadas a las fuentes.
import {apiGet,apiPost} from "./api.js";
import {escapeHtml} from "./ui.js";

const SUGERENCIAS=[
  "¿Cuáles son las cinco categorías de triaje establecidas en la Resolución 5596?",
  "¿Qué observaciones fisiológicas mínimas recomienda NICE registrar en la valoración inicial?",
  "¿Cuándo recomienda NICE el ácido tranexámico en trauma mayor con hemorragia?",
  "¿Qué elementos incluye la evaluación sistemática ABCDE?",
];
const SUGERENCIAS_PACIENTE=[
  "¿Cuál fue el motivo de consulta y el nivel de triaje del paciente?",
  "¿Qué diagnósticos tiene registrados el paciente y qué recomiendan las guías?",
];
const SUGERENCIAS_AGENTE=[
  "Consulta los últimos signos vitales del paciente",
  "Ejecuta el modelo predictivo para estimar el nivel de riesgo clínico de este paciente",
  "Prepara un borrador de remisión para valoración por otorrinolaringología",
];
const NOMBRES_HERRAMIENTA={
  consultar_historia:"Consulta de historia aprobada",
  ejecutar_modelo:"Predicción del modelo clínico",
  preparar_remision:"Borrador de remisión",
};
const MODO={
  llm:{clase:"success",texto:"Respuesta con citas"},
  extractivo:{clase:"warning",texto:"Modo extractivo"},
  abstencion:{clase:"neutral",texto:"Sin evidencia suficiente"},
};

/** Vista completa del menú lateral. */
export async function renderAsistente(container){
  container.innerHTML=`
    <section class="page-hero"><div><p class="eyebrow">Semana 12 · R23 RAG + R24 Agente</p><h2>Asistente clínico</h2>
      <p class="muted">Responde solo con guías clínicas oficiales (Resolución 5596, OMS, NICE) y, si indica un paciente,
      con su historia <strong>aprobada</strong>. Cada afirmación lleva su cita.</p></div>
      <span class="badge info">Apoyo clínico supervisado</span></section>
    <section class="card rag-chat" id="rag-chat"></section>`;
  montarChat(container.querySelector("#rag-chat"),{documento:null});
}

/** Pestaña dentro de la ficha del paciente. */
export async function renderPanelAsistente(documento,panel){
  panel.innerHTML=`<section class="card rag-chat" id="rag-chat"></section>`;
  montarChat(panel.querySelector("#rag-chat"),{documento:Number(documento)});
}

function montarChat(el,{documento}){
  const fijo=documento!=null;
  let modo="rag";
  el.innerHTML=`
    <div class="section-head"><div><h3>Asistente clínico</h3>
      <p class="muted small-text">R23 consulta guías con citas. R24 selecciona una herramienta autorizada y deja auditoría.</p></div></div>
    <div class="rag-modos" role="group" aria-label="Modo del asistente">
      <button type="button" class="rag-modo activo" data-modo="rag" aria-pressed="true">Consultar información · R23</button>
      <button type="button" class="rag-modo" data-modo="agente" aria-pressed="false">Ejecutar herramientas · R24</button>
    </div>
    <p class="muted small-text rag-descripcion"></p>
    <div class="rag-mensajes" aria-live="polite"></div>
    <form class="rag-form">
      ${fijo?`<p class="muted small-text">Paciente de esta ficha: <strong>${escapeHtml(documento)}</strong>. El backend usa el identificador para autorizar; Groq no lo recibe como argumento.</p>`:`<label class="rag-paciente"><span>Documento del paciente <span class="rag-paciente-opcional muted">(opcional en R23)</span></span><input name="paciente" type="number" min="1" step="1" inputmode="numeric" placeholder="Solo guías"></label>`}
      <div class="rag-campos-agente" hidden>
        <label class="rag-campo"><span>Encuentro clínico aprobado</span><select name="encuentro"><option value="">Seleccione un paciente primero</option></select></label>
        <p class="muted small-text rag-encuentro-ayuda">Se mostrarán los encuentros aprobados para el asistente y accesibles para su usuario.</p>
        <div class="rag-remision-campos" hidden>
          <label class="rag-campo"><span>Especialidad para el borrador</span><input name="especialidad" maxlength="120" placeholder="Ej. Otorrinolaringología"></label>
          <label class="rag-campo"><span>Motivo de la remisión</span><textarea name="motivo" rows="2" maxlength="1000" placeholder="Motivo clínico para revisión profesional"></textarea></label>
        </div>
      </div>
      <div class="rag-entrada">
        <textarea name="pregunta" rows="2" minlength="3" maxlength="1000" required placeholder="Escriba su pregunta clínica… (Enter para enviar; Shift+Enter para salto de línea)"></textarea>
        <button class="btn btn-primary" type="submit">Preguntar</button>
      </div>
      <p class="muted small-text rag-legal">Apoyo clínico; no sustituye el juicio profesional. Las autorizaciones se verifican en el backend y las acciones quedan auditadas.</p>
    </form>`;

  const form=el.querySelector(".rag-form");
  const area=form.querySelector('[name="pregunta"]');
  const lista=el.querySelector(".rag-mensajes");
  const docInput=form.querySelector('[name="paciente"]');
  const encuentroSelect=form.querySelector('[name="encuentro"]');
  const ayudaEncuentro=el.querySelector(".rag-encuentro-ayuda");
  const remisionCampos=el.querySelector(".rag-remision-campos");
  let versionConsulta=0;

  function pacienteActual(){return fijo?documento:(docInput?.value?Number(docInput.value):null);}
  function mostrarSugerencias(){
    const sugerencias=modo==="agente"?SUGERENCIAS_AGENTE:(fijo?[...SUGERENCIAS_PACIENTE,SUGERENCIAS[0]]:SUGERENCIAS);
    lista.innerHTML=`<div class="rag-vacio"><p class="muted">Pruebe con una de estas preguntas:</p><div class="rag-sugerencias">${sugerencias.map(s=>`<button type="button" class="rag-sugerencia">${escapeHtml(s)}</button>`).join("")}</div></div>`;
    lista.querySelectorAll(".rag-sugerencia").forEach(b=>b.addEventListener("click",()=>{
      area.value=b.textContent;
      actualizarRemision();
      area.focus();
    }));
  }

  async function cargarEncuentros(){
    const version=++versionConsulta;
    const paciente=pacienteActual();
    encuentroSelect.innerHTML='<option value="">Seleccione un paciente primero</option>';
    if(modo!=="agente")return;
    if(!Number.isSafeInteger(paciente)||paciente<=0){
      ayudaEncuentro.textContent="Ingrese un documento válido para consultar encuentros aprobados.";
      return;
    }
    encuentroSelect.innerHTML='<option value="">Cargando encuentros…</option>';
    ayudaEncuentro.textContent="Consultando encuentros autorizados…";
    try{
      const historia=await apiGet(`/pacientes/${paciente}/historia-clinica`);
      if(version!==versionConsulta||modo!=="agente"||paciente!==pacienteActual())return;
      const aprobados=(historia.encuentros||[]).filter(e=>e.aprobado_rag===true);
      encuentroSelect.replaceChildren(new Option(aprobados.length?"Seleccione un encuentro":"No hay encuentros aprobados",""));
      for(const e of aprobados){
        encuentroSelect.add(new Option(`Encuentro #${e.id_encuentro} · ${e.motivo_consulta||"Sin motivo registrado"}`,String(e.id_encuentro)));
      }
      ayudaEncuentro.textContent=aprobados.length
        ?"Seleccione el encuentro autorizado. La API validará nuevamente la asignación médica y la aprobación."
        :"Este paciente no tiene encuentros aprobados para R24.";
    }catch(err){
      if(version!==versionConsulta)return;
      encuentroSelect.replaceChildren(new Option("Sin acceso a encuentros",""));
      ayudaEncuentro.textContent=err.message||"No se pudieron cargar los encuentros.";
    }
  }

  function actualizarRemision(){
    const hayRemision=modo==="agente"&&/remisi[oó]n|remitir|especialista|interconsulta|referencia/i.test(area.value);
    remisionCampos.hidden=!hayRemision;
  }

  function cambiarModo(nuevo){
    if(modo===nuevo)return;
    modo=nuevo;
    el.querySelectorAll("[data-modo]").forEach(b=>{
      const activo=b.dataset.modo===modo;
      b.classList.toggle("activo",activo);
      b.setAttribute("aria-pressed",String(activo));
    });
    el.querySelector(".rag-descripcion").textContent=modo==="rag"
      ?"R23 · Respuestas documentales con citas. Puede consultar guías sin seleccionar paciente."
      :"R24 · Consulta de historia, predicción o borrador de remisión. Requiere paciente y encuentro clínico aprobado.";
    el.querySelector(".rag-campos-agente").hidden=modo!=="agente";
    el.querySelector(".rag-paciente-opcional")?.replaceChildren(document.createTextNode(modo==="rag"?"(opcional en R23)":"(obligatorio en R24)"));
    el.querySelector('button[type="submit"]').textContent=modo==="rag"?"Preguntar":"Ejecutar";
    area.value="";
    actualizarRemision();
    mostrarSugerencias();
    cargarEncuentros();
  }

  el.querySelectorAll("[data-modo]").forEach(b=>b.addEventListener("click",()=>cambiarModo(b.dataset.modo)));
  docInput?.addEventListener("change",cargarEncuentros);
  area.addEventListener("input",actualizarRemision);
  area.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});
  el.querySelector(".rag-descripcion").textContent="R23 · Respuestas documentales con citas. Puede consultar guías sin seleccionar paciente.";
  mostrarSugerencias();

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    const pregunta=area.value.trim();
    if(pregunta.length<3)return;
    const paciente=pacienteActual();
    let body={pregunta,...(paciente?{paciente_id:paciente}:{})};
    if(modo==="agente"){
      if(!Number.isSafeInteger(paciente)||paciente<=0){ayudaEncuentro.textContent="R24 requiere un documento de paciente válido.";docInput?.focus();return;}
      const id=Number(encuentroSelect.value);
      if(!Number.isSafeInteger(id)||id<=0){ayudaEncuentro.textContent="Seleccione un encuentro aprobado antes de ejecutar R24.";encuentroSelect.focus();return;}
      body={pregunta,paciente_id:paciente,id_encuentro:id};
      const motivo=form.querySelector('[name="motivo"]').value.trim();
      const especialidad=form.querySelector('[name="especialidad"]').value.trim();
      if(motivo)body.motivo=motivo;
      if(especialidad)body.especialidad=especialidad;
    }
    const modoEnviado=modo;
    lista.querySelector(".rag-vacio")?.remove();
    lista.insertAdjacentHTML("beforeend",burbujaUsuario(pregunta,paciente&&!fijo?paciente:null));
    const pendiente=document.createElement("div");
    pendiente.className="rag-msg rag-bot";
    pendiente.innerHTML=`<div class="rag-burbuja"><span class="rag-escribiendo"><i></i><i></i><i></i></span> ${modoEnviado==="rag"?"Buscando en las fuentes…":"Seleccionando herramienta autorizada…"}</div>`;
    lista.appendChild(pendiente);
    pendiente.scrollIntoView({behavior:"smooth",block:"end"});
    const boton=form.querySelector('button[type="submit"]');
    boton.disabled=true;
    el.querySelectorAll("[data-modo]").forEach(b=>b.disabled=true);
    try{
      const r=await apiPost(modoEnviado==="rag"?"/rag/preguntar":"/agente/preguntar",body);
      pendiente.replaceWith(modoEnviado==="rag"?burbujaRespuesta(r):burbujaAgente(r));
      area.value="";
      actualizarRemision();
    }catch(err){
      pendiente.innerHTML=`<div class="rag-burbuja rag-error">${escapeHtml(err.message||"No fue posible consultar el asistente.")}</div>`;
    }finally{
      boton.disabled=false;
      el.querySelectorAll("[data-modo]").forEach(b=>b.disabled=false);
      area.focus();
      lista.lastElementChild?.scrollIntoView({behavior:"smooth",block:"start"});
    }
  });
}

/** R24: representación estructurada y escapada; nunca tratar la salida como HTML. */
function burbujaAgente(r){
  const nodo=document.createElement("div");
  nodo.className="rag-msg rag-bot";
  const tipo=NOMBRES_HERRAMIENTA[r.herramienta]||"Solicitud fuera del catálogo";
  const res=r.resultado||{};
  let detalle="";
  if(r.herramienta==="consultar_historia"&&res.historia){
    detalle=`<h4>Historia clínica aprobada</h4>${resumenHistoria(res.historia)}`;
  }else if(r.herramienta==="ejecutar_modelo"&&res.prediccion){
    const p=res.prediccion,por=p.probabilidades||{};
    detalle=`<h4>Resultado del modelo predictivo</h4><p><strong>Categoría estimada:</strong> ${escapeHtml(p.categoria||"No disponible")}</p>
      <div class="rag-probabilidades">${["critico","medio","no_critico"].map(k=>{
        const valor=Number(por[k]);
        return Number.isFinite(valor)?`<div><span>${escapeHtml(k)}</span><strong>${(valor*100).toFixed(2)}%</strong></div>`:"";
      }).join("")}</div>
      <p class="muted small-text">Versión: ${escapeHtml(p.modelo_version||"—")}. ${res.guardado===false?"No se guardó ningún reporte clínico.":"Revise el estado de persistencia."}</p>`;
  }else if(r.herramienta==="preparar_remision"&&res.borrador){
    const b=res.borrador;
    detalle=`<h4>Borrador de remisión</h4><p><strong>Especialidad:</strong> ${escapeHtml(b.especialidad||"—")}</p>
      <p><strong>Motivo:</strong> ${escapeHtml(b.motivo||"—")}</p>
      <p><strong>Estado:</strong> ${escapeHtml(b.estado||"—")} · ${b.enviado===false?"No enviado":"Verificar estado de envío"}</p>
      ${b.resumen_clinico?`<details class="rag-fuente"><summary>Ver resumen clínico del borrador</summary>${resumenHistoria(b.resumen_clinico)}</details>`:""}`;
  }else detalle=`<p>${escapeHtml(r.mensaje||"No se ejecutó ninguna herramienta.")}</p>`;
  nodo.innerHTML=`<div class="rag-burbuja"><div class="rag-meta"><span class="badge info">R24 · ${escapeHtml(tipo)}</span>
    ${r.llm_invocado?'<span class="badge success">Groq invocado</span>':""}</div><div class="rag-texto">${detalle}</div>
    ${r.advertencia?`<p class="rag-aviso">${escapeHtml(r.advertencia)}</p>`:""}</div>`;
  return nodo;
}

function resumenHistoria(h){
  const signos=Array.isArray(h.signos)?h.signos:[];
  const observaciones=h.observaciones_generales
    ? '<p><strong>Observaciones:</strong> '+escapeHtml(h.observaciones_generales)+'</p>'
    : '';
  let tablaSignos='<p class="muted">Sin signos vitales disponibles.</p>';
  if(signos.length){
    const filas=signos.map(s=>{
      const nombre=escapeHtml(s.nombre||'—');
      const valor=escapeHtml(s.valor??'—');
      const unidad=escapeHtml(s.unidad||'');
      const loinc=escapeHtml(s.loinc||'—');
      return '<tr><td>'+nombre+'</td><td>'+valor+' '+unidad+'</td><td>'+loinc+'</td></tr>';
    }).join('');
    tablaSignos='<div class="table-wrap"><table class="rag-tabla">'
      +'<thead><tr><th>Signo vital</th><th>Valor</th><th>LOINC</th></tr></thead>'
      +'<tbody>'+filas+'</tbody></table></div>';
  }
  return '<p><strong>Motivo de consulta:</strong> '+escapeHtml(h.motivo_consulta||'—')+'</p>'
    +'<p><strong>Triage:</strong> '+escapeHtml(h.nivel_triage??'—')
    +' · <strong>Dolor:</strong> '+escapeHtml(h.dolor_escala??'—')+'</p>'
    +observaciones+tablaSignos;
}

function burbujaUsuario(texto,paciente){
  return `<div class="rag-msg rag-yo"><div class="rag-burbuja">${escapeHtml(texto)}${paciente?`<span class="rag-etiqueta">Paciente ${paciente}</span>`:""}</div></div>`;
}

function burbujaRespuesta(r){
  const modo=MODO[r.modo]||MODO.llm;
  const nodo=document.createElement("div");
  nodo.className="rag-msg rag-bot";
  const citadas=r.fuentes.filter(f=>f.citada);
  const resto=r.fuentes.filter(f=>!f.citada);
  nodo.innerHTML=`
    <div class="rag-burbuja">
      <div class="rag-meta"><span class="badge ${modo.clase}">${modo.texto}</span>
        ${r.con_historia?'<span class="badge info">Incluye historia aprobada</span>':""}
        <span class="muted small-text">método: ${escapeHtml(r.metodo)}</span></div>
      ${r.aviso?`<div class="rag-aviso">${escapeHtml(r.aviso)}</div>`:""}
      <div class="rag-texto">${formatear(r.respuesta)}</div>
      ${r.fuentes.length?`<div class="rag-fuentes">
        <p class="rag-fuentes-titulo">Fuentes${citadas.length?" citadas":""}</p>
        ${(citadas.length?citadas:r.fuentes).map(tarjetaFuente).join("")}
        ${citadas.length&&resto.length?`<details><summary>${resto.length===1?"1 fragmento más":`${resto.length} fragmentos más`} de contexto</summary>${resto.map(tarjetaFuente).join("")}</details>`:""}
      </div>`:""}
    </div>`;
  // Clic en [F#] → resalta y despliega la fuente correspondiente.
  nodo.querySelectorAll("[data-cita]").forEach(b=>b.onclick=()=>{
    const f=nodo.querySelector(`[data-fuente="${b.dataset.cita}"]`);
    if(!f)return;
    f.closest("details")?.setAttribute("open","");
    f.open=true;
    f.classList.remove("rag-resaltada");void f.offsetWidth;f.classList.add("rag-resaltada");
    f.scrollIntoView({behavior:"smooth",block:"nearest"});
  });
  return nodo;
}

function tarjetaFuente(f){
  const esHistoria=f.tipo==="historia";
  const titulo=esHistoria
    ?`Historia clínica aprobada${f.id_encuentro?` · encuentro #${f.id_encuentro}`:""}`
    :`${f.titulo||f.fuente}${f.pagina?` · pág. ${f.pagina}`:""}`;
  return `<details class="rag-fuente ${esHistoria?"rag-fuente-historia":""}" data-fuente="${escapeHtml(f.cita)}">
    <summary><span class="rag-cita-tag">${escapeHtml(f.cita)}</span> ${escapeHtml(titulo)}</summary>
    <p class="rag-extracto">${escapeHtml(f.extracto||"")}${(f.extracto||"").length>=400?"…":""}</p>
    ${f.url?`<a href="${escapeHtml(f.url)}" target="_blank" rel="noopener noreferrer">Abrir guía original ↗</a>`:""}
  </details>`;
}

// Markdown mínimo y seguro: se escapa TODO primero y luego se aplican negritas, viñetas,
// tablas sencillas y las citas [F#] como botones.
function formatear(texto){
  const lineas=escapeHtml(texto||"").split(/\r?\n/);
  let html="",enLista=false,tabla=[];
  const cerrarLista=()=>{if(enLista){html+="</ul>";enLista=false;}};
  const cerrarTabla=()=>{
    if(!tabla.length)return;
    const filas=tabla.filter(l=>!/^\|?\s*:?-{2,}/.test(l)).map(l=>l.replace(/^\||\|$/g,"").split("|").map(c=>c.trim()));
    html+=`<div class="table-wrap"><table class="rag-tabla"><thead><tr>${filas[0].map(c=>`<th>${c}</th>`).join("")}</tr></thead><tbody>${
      filas.slice(1).map(f=>`<tr>${f.map(c=>`<td>${c}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`;
    tabla=[];
  };
  for(const cruda of lineas){
    const l=cruda.trim();
    if(l.startsWith("|")){cerrarLista();tabla.push(l);continue;}
    cerrarTabla();
    const vineta=l.match(/^(?:[-*•]|\d+[.)])\s+(.*)/);
    if(vineta){if(!enLista){html+="<ul>";enLista=true;}html+=`<li>${vineta[1]}</li>`;continue;}
    cerrarLista();
    if(!l){continue;}
    const titulo=l.match(/^#{1,4}\s+(.*)/);
    html+=titulo?`<p><strong>${titulo[1]}</strong></p>`:`<p>${l}</p>`;
  }
  cerrarLista();cerrarTabla();
  return html
    .replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>")
    .replace(/\[(F\d+(?:\s*,\s*F\d+)*)\]/g,(_,g)=>g.split(/\s*,\s*/).map(c=>`<button type="button" class="rag-cita" data-cita="${c}">${c}</button>`).join(""));
}
