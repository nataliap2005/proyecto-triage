// asistente.js — Semana 12 · Chat del asistente clínico RAG (POST /rag/preguntar).
// Dos entradas:
//   · Vista "Asistente clínico" del menú: consulta guías y, si se indica, la historia de un paciente.
//   · Pestaña "Asistente clínico" de la ficha del paciente: el paciente ya viene fijado.
// El backend valida rol, acceso al paciente y seudonimiza; aquí solo se muestra la respuesta
// con sus citas [F#] enlazadas a las fuentes.
import {apiPost} from "./api.js";
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
const MODO={
  llm:{clase:"success",texto:"Respuesta con citas"},
  extractivo:{clase:"warning",texto:"Modo extractivo"},
  abstencion:{clase:"neutral",texto:"Sin evidencia suficiente"},
};

/** Vista completa del menú lateral. */
export async function renderAsistente(container){
  container.innerHTML=`
    <section class="page-hero"><div><p class="eyebrow">Semana 12 · RAG</p><h2>Asistente clínico</h2>
      <p class="muted">Responde solo con guías clínicas oficiales (Resolución 5596, OMS, NICE) y, si indica un paciente,
      con su historia <strong>aprobada</strong>. Cada afirmación lleva su cita.</p></div>
      <span class="badge info">Apoyo documental</span></section>
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
  const sugerencias=fijo?[...SUGERENCIAS_PACIENTE,SUGERENCIAS[0]]:SUGERENCIAS;
  el.innerHTML=`
    <div class="section-head"><div><h3>Pregúntele a las guías${fijo?" y a la historia aprobada":""}</h3>
      <p class="muted small-text">${fijo
        ?`Paciente <strong>${documento}</strong>. Su documento no sale de la API: al motor solo llega un seudónimo.`
        :"Sin paciente, solo se consultan las guías. Con documento, se suma la historia aprobada de ese paciente."}</p></div></div>
    <div class="rag-mensajes" aria-live="polite">
      <div class="rag-vacio">
        <p class="muted">Pruebe con una de estas preguntas:</p>
        <div class="rag-sugerencias">${sugerencias.map(s=>`<button type="button" class="rag-sugerencia">${escapeHtml(s)}</button>`).join("")}</div>
      </div>
    </div>
    <form class="rag-form">
      ${fijo?"":`<label class="rag-paciente"><span>Documento del paciente <span class="muted">(opcional)</span></span>
        <input name="paciente" type="number" min="1" inputmode="numeric" placeholder="Solo guías"></label>`}
      <div class="rag-entrada">
        <textarea name="pregunta" rows="2" maxlength="1000" required placeholder="Escriba su pregunta clínica… (Enter para enviar, Shift+Enter para salto de línea)"></textarea>
        <button class="btn btn-primary" type="submit">Preguntar</button>
      </div>
      <p class="muted small-text rag-legal">Apoyo documental. No reemplaza el juicio clínico del profesional. Cada consulta queda en la auditoría.</p>
    </form>`;

  const form=el.querySelector(".rag-form");
  const area=form.querySelector("textarea");
  const lista=el.querySelector(".rag-mensajes");

  el.querySelectorAll(".rag-sugerencia").forEach(b=>b.onclick=()=>{area.value=b.textContent;form.requestSubmit();});
  area.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();form.requestSubmit();}});

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    const pregunta=area.value.trim();
    if(pregunta.length<3)return;
    const docInput=form.querySelector('[name="paciente"]');
    const paciente=fijo?documento:(docInput?.value?Number(docInput.value):null);
    const body={pregunta,...(paciente?{paciente_id:paciente}:{})};

    lista.querySelector(".rag-vacio")?.remove();
    lista.insertAdjacentHTML("beforeend",burbujaUsuario(pregunta,paciente&&!fijo?paciente:null));
    const pendiente=document.createElement("div");
    pendiente.className="rag-msg rag-bot";
    pendiente.innerHTML=`<div class="rag-burbuja"><span class="rag-escribiendo"><i></i><i></i><i></i></span> Buscando en las fuentes…</div>`;
    lista.appendChild(pendiente);
    pendiente.scrollIntoView({behavior:"smooth",block:"end"});

    area.value="";
    const boton=form.querySelector('button[type="submit"]');
    boton.disabled=true;
    try{
      const r=await apiPost("/rag/preguntar",body);
      pendiente.replaceWith(burbujaRespuesta(r));
    }catch(err){
      pendiente.innerHTML=`<div class="rag-burbuja rag-error">${escapeHtml(err.message||"No fue posible consultar el asistente.")}</div>`;
    }finally{
      boton.disabled=false;
      area.focus();
      lista.lastElementChild?.scrollIntoView({behavior:"smooth",block:"start"});
    }
  });
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
