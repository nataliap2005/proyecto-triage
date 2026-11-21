
import {apiPatch,apiPost,apiPut} from "./api.js";
import {escapeHtml,showToast,errorEnFormulario} from "./ui.js";

const NIVELES={1:"Resucitación",2:"Emergencia",3:"Urgente",4:"Menos urgente",5:"No urgente"};
const CATEGORIA={
  critico:{texto:"Crítico",rango:[1,2],sugerido:2,clase:"ia-critico"},
  medio:{texto:"Medio",rango:[3,3],sugerido:3,clase:"ia-medio"},
  no_critico:{texto:"No crítico",rango:[4,5],sugerido:4,clase:"ia-no-critico"},
};
const MOTIVOS=[["cardiovascular","Cardiovascular (dolor torácico, palpitaciones)"],["respiratorio","Respiratorio (disnea, tos)"],
  ["digestivo","Digestivo (dolor abdominal, vómito, diarrea)"],["neurologico","Neurológico (cefalea, mareo, déficit)"],
  ["conciencia_paro","Alteración de conciencia / paro"],["fiebre_general","Fiebre / malestar general"],["trauma","Trauma / lesión"],
  ["musculoesqueletico","Musculoesquelético"],["genitourinario_gineco","Genitourinario / ginecológico"],
  ["psiquiatrico_sustancias","Psiquiátrico / sustancias"],["piel_alergia","Piel / alergia"],["orl_ojos_dental","Ojos, oídos, nariz, boca"],["otros","Otro"]];
const pct=v=>`${Math.round(Number(v||0)*100)}%`;
const si=v=>v===true?"true":v===false?"false":"";

export function abrirTriajeIA(encuentro,{tieneVitales,onDone}){
  const dlg=document.createElement("dialog");
  dlg.className="ia-dialog";
  document.body.append(dlg);
  dlg.addEventListener("close",()=>dlg.remove());
  const estado={enc:encuentro,reporte:null,decision:null,onDone,dlg};
  if(!tieneVitales) pasoSinVitales(estado); else pasoDatos(estado);
  dlg.showModal();
}

function marco(titulo,cuerpo){
  return `<div class="ia-dialog-head"><h2>${titulo}</h2><button class="btn btn-ghost btn-icon" data-cerrar type="button" aria-label="Cerrar">✕</button></div>${cuerpo}`;
}
function pintar(est,html){
  est.dlg.innerHTML=html;
  est.dlg.querySelector("[data-cerrar]")?.addEventListener("click",()=>est.dlg.close());
  est.dlg.querySelector("[data-manual]")?.addEventListener("click",()=>pasoNivel(est,null));
}

function pasoSinVitales(est){
  pintar(est,marco("Realizar triage",`
    <p class="ia-aviso">Para que la IA sugiera la categoría primero deben registrarse los <strong>signos vitales</strong> del encuentro (paso 2).</p>
    <div class="ia-dialog-acciones"><button class="btn btn-secondary" data-manual type="button">Clasificar sin IA</button></div>`));
}

function pasoDatos(est){
  const e=est.enc;
  pintar(est,marco("Triage asistido por IA",`
    <p class="muted">Estos datos del ingreso los usa el modelo junto con los signos vitales.</p>
    <form class="ia-dialog-form" id="ia-datos">
      <label>Motivo de consulta (categoría)
        <select name="motivo_categoria" required>
          <option value="">Seleccione…</option>
          ${MOTIVOS.map(([v,t])=>`<option value="${v}" ${e.motivo_categoria===v?"selected":""}>${t}</option>`).join("")}
        </select></label>
      <div class="ia-dialog-fila">
        <label>Llegada
          <select name="llegada_ambulancia"><option value="">No registrado</option>
            <option value="true" ${si(e.llegada_ambulancia)==="true"?"selected":""}>En ambulancia</option>
            <option value="false" ${si(e.llegada_ambulancia)==="false"?"selected":""}>Por sus medios</option></select></label>
        <label>¿Trauma o lesión?
          <select name="lesion"><option value="">No registrado</option>
            <option value="true" ${si(e.lesion)==="true"?"selected":""}>Sí</option>
            <option value="false" ${si(e.lesion)==="false"?"selected":""}>No</option></select></label>
        <label>Dolor (0 a 10)
          <input name="dolor_nrs" type="number" min="0" max="10" step="1" value="${e.dolor_escala??""}"></label>
      </div>
      <div class="ia-dialog-acciones">
        <button class="btn btn-ghost" data-manual type="button">Clasificar sin IA</button>
        <button class="btn btn-primary" type="submit">Obtener sugerencia de la IA</button>
      </div>
    </form>`));
  est.dlg.querySelector("#ia-datos").addEventListener("submit",async ev=>{
    ev.preventDefault();
    const f=ev.currentTarget,boton=f.querySelector("[type=submit]");
    const cuerpo={id_encuentro:est.enc.id_encuentro,motivo_categoria:f.elements.motivo_categoria.value};
    for(const k of ["llegada_ambulancia","lesion"]) if(f.elements[k].value!=="") cuerpo[k]=f.elements[k].value==="true";
    if(f.elements.dolor_nrs.value!=="") cuerpo.signos={dolor_nrs:Number(f.elements.dolor_nrs.value)};
    est.dolor=f.elements.dolor_nrs.value;
    boton.disabled=true;boton.textContent="Analizando…";
    try{
      est.reporte=await apiPost(`/ia/analizar/${est.enc.id_paciente}`,cuerpo);
      if(est.reporte.alerta) showToast("Alerta crítica generada: el equipo ya fue notificado","error");
      pasoSugerencia(est);
    }catch(e){
      errorEnFormulario(f,e.message);   // visible dentro de la ventana abierta
      boton.disabled=false;boton.textContent="Obtener sugerencia de la IA";
    }
  });
}

function pasoSugerencia(est){
  const r=est.reporte,cat=CATEGORIA[r.categoria],P=r.probabilidades||{};
  const lista=(xs,s)=>(xs||[]).map(x=>`<li><span class="ia-flecha">${s}</span>${escapeHtml(x.texto)}</li>`).join("")||'<li class="muted">—</li>';
  pintar(est,marco("Sugerencia de la IA",`
    <div class="ia-sugerencia ${cat.clase}">
      <span class="ia-badge ${cat.clase}">${cat.texto}</span>
      <span>Niveles ${cat.rango[0]===cat.rango[1]?cat.rango[0]:cat.rango.join(" o ")} · P(crítico) ${pct(r.p_critico)}</span>
    </div>
    ${r.alerta?`<p class="ia-alerta-nota">⚠ Se generó una alerta crítica: ${r.alerta.motivo.map(escapeHtml).join(" · ")}</p>`:""}
    <div class="ia-probs">${["critico","medio","no_critico"].map(k=>`
      <div class="ia-prob"><span>${CATEGORIA[k].texto}</span><div class="ia-barra"><div class="${CATEGORIA[k].clase}" style="width:${pct(P[k])}"></div></div><strong>${pct(P[k])}</strong></div>`).join("")}</div>
    <div class="ia-columnas">
      <div><h4>Sube la urgencia</h4><ul class="ia-factores">${lista(r.factores_suben,"▲")}</ul></div>
      <div><h4>La baja</h4><ul class="ia-factores">${lista(r.factores_bajan,"▼")}</ul></div>
    </div>
    ${(r.avisos||[]).length?`<p class="muted small-text">ℹ ${r.avisos.map(escapeHtml).join(" · ")}</p>`:""}
    <label class="ia-dialog-form">Observaciones sobre la sugerencia (opcional)
      <textarea id="ia-obs" rows="2" maxlength="2000"></textarea></label>
    <div class="ia-dialog-acciones">
      <button class="btn btn-secondary" data-decidir="rechazar" type="button">Rechazar y clasificar manualmente</button>
      <button class="btn btn-primary" data-decidir="aprobar" type="button">Aceptar sugerencia</button>
    </div>`));
  est.dlg.querySelectorAll("[data-decidir]").forEach(b=>b.addEventListener("click",async()=>{
    est.dlg.querySelectorAll("[data-decidir]").forEach(x=>x.disabled=true);
    try{
      const obs=est.dlg.querySelector("#ia-obs").value.trim()||null;
      await apiPatch(`/ia/reportes/${r.id}/${b.dataset.decidir}`,{observaciones:obs});
      est.decision=b.dataset.decidir;
      pasoNivel(est,b.dataset.decidir==="aprobar"?cat:null);
    }catch(e){showToast(e.message,"error");est.dlg.querySelectorAll("[data-decidir]").forEach(x=>x.disabled=false);}
  }));
}

function pasoNivel(est,cat){
  const [min,max]=cat?cat.rango:[1,5];
  const niveles=[1,2,3,4,5].filter(n=>n>=min&&n<=max);
  const dolor=est.dolor??est.enc.dolor_escala??"";
  const titulo=cat?"Confirmar nivel de triage":"Registrar triage";
  pintar(est,marco(titulo,`
    ${cat?`<p class="ia-aviso-ok">Sugerencia aceptada: <strong>${cat.texto}</strong>. Elija el nivel exacto dentro de esa categoría.</p>`:
      est.decision==="rechazar"?'<p class="muted">Sugerencia rechazada (queda registrada como evidencia). Clasifique manualmente.</p>':""}
    <form class="ia-dialog-form" id="ia-nivel">
      <label>Nivel de triage (${min===max?min:`${min} a ${max}`})
        <select name="nivel_triage" required>
          ${niveles.map(n=>`<option value="${n}" ${cat&&n===cat.sugerido?"selected":""}>${n} · ${NIVELES[n]}</option>`).join("")}
        </select></label>
      <label>Escala de dolor (0 a 10, opcional)<input name="dolor_escala" type="number" min="0" max="10" value="${dolor}"></label>
      <label>Observaciones del triage<textarea name="observaciones_triage" rows="3"></textarea></label>
      <div class="ia-dialog-acciones"><button class="btn btn-primary btn-block" type="submit">Guardar triage</button></div>
    </form>`));
  est.dlg.querySelector("#ia-nivel").addEventListener("submit",async ev=>{
    ev.preventDefault();
    const f=ev.currentTarget;
    const cuerpo={nivel_triage:Number(f.elements.nivel_triage.value),
      dolor_escala:f.elements.dolor_escala.value===""?null:Number(f.elements.dolor_escala.value),
      observaciones_triage:f.elements.observaciones_triage.value.trim()||null};
    if(cat) cuerpo.id_reporte_ia=est.reporte.id;     // queda marcado como clasificación asistida por IA
    f.querySelector("[type=submit]").disabled=true;
    try{
      await apiPut(`/encuentros/${est.enc.id_encuentro}/triage`,cuerpo);
      showToast(`Triage nivel ${cuerpo.nivel_triage} registrado${cat?" (sugerencia de IA aceptada)":""}`,"success");
      est.dlg.close();
      est.onDone?.();
    }catch(e){showToast(e.message,"error");f.querySelector("[type=submit]").disabled=false;}
  });
}
