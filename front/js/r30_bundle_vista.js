import {apiGet} from './api.js';
import {escapeHtml,showToast,modal} from './ui.js';

const ETIQUETAS = {
  Patient: 'Paciente seudonimizado',
  Consent: 'Consentimiento FHIR',
  ServiceRequest: 'Solicitud de remisión',
  Task: 'Seguimiento de la remisión',
  Observation: 'Signo vital / observación',
  DiagnosticReport: 'Informe clínico aprobado'
};

function dato(valor){return escapeHtml(valor == null || valor === '' ? '—' : String(valor));}
function fila(titulo, valor){return `<div class="r30-detail"><span>${dato(titulo)}</span><strong>${dato(valor)}</strong></div>`;}
function describir(r){
  switch(r.resourceType){
    case 'Patient': return 'Identificador técnico del paciente, sin nombre, documento ni dirección.';
    case 'Consent': return `Estado: ${r.status||'—'} · Permiso: ${r.provision?.type||'—'} · Finalidad: ${(r.provision?.purpose||[]).map(x=>x.code).join(', ')||'—'}`;
    case 'ServiceRequest': return `Estado: ${r.status||'—'} · SNOMED: ${r.code?.coding?.[0]?.code||'—'} · Motivo: ${r.reasonCode?.[0]?.text||'—'}`;
    case 'Task': return `Estado: ${r.status||'—'} · Vinculado a: ${r.focus?.reference||'—'}`;
    case 'Observation': return `LOINC: ${r.code?.coding?.[0]?.code||'—'} · ${r.code?.coding?.[0]?.display||'Observación'}: ${r.valueQuantity?.value??'—'} ${r.valueQuantity?.unit||''}`;
    case 'DiagnosticReport': return `Estado: ${r.status||'—'} · ${r.conclusion||'Sin conclusión'}`;
    default: return 'Recurso FHIR';
  }
}

export async function abrirVistaPreviaR30(idRemision, boton=null){
  const id=Number(idRemision);
  if(!Number.isSafeInteger(id)||id<=0){showToast('Identificador de remisión inválido','error');return;}
  if(boton){boton.disabled=true;boton.textContent='Consultando FHIR…';}
  try{
    // GET: solo lectura. No sincroniza con HAPI ni envía al socio.
    const bundle=await apiGet(`/fhir/remisiones-r30/${id}/bundle`);
    if(bundle?.resourceType!=='Bundle'||bundle?.type!=='transaction'||!Array.isArray(bundle.entry)){
      throw new Error('El servidor no devolvió un Bundle FHIR transaction válido');
    }
    const recursos=bundle.entry.map(e=>e.resource).filter(Boolean);
    const tipos=recursos.reduce((a,r)=>(a[r.resourceType]=(a[r.resourceType]||0)+1,a),{});
    const consent=recursos.find(r=>r.resourceType==='Consent');
    const task=recursos.find(r=>r.resourceType==='Task');
    const reportes=recursos.filter(r=>r.resourceType==='DiagnosticReport');
    const resumen=Object.entries(ETIQUETAS).map(([tipo,nombre])=>{
      const n=tipos[tipo]||0;
      return `<div class="r30-count"><strong>${n}</strong><span>${dato(nombre)}</span></div>`;
    }).join('');
    const listado=recursos.map((r,i)=>`<details class="r30-resource"><summary>${i+1}. ${dato(ETIQUETAS[r.resourceType]||r.resourceType)}</summary><p>${dato(describir(r))}</p><small>FHIR ID: ${dato(r.id)}</small></details>`).join('');
    const m=modal(`R30 · Vista previa FHIR · Remisión #${id}`,`
      <div class="r30-preview">
        <p class="muted">Esta vista solo consulta el Bundle. <strong>No envía información</strong> a otra institución ni modifica la remisión.</p>
        <div class="r30-detail-grid">
          ${fila('FHIR','R4 (4.0.1) · Bundle transaction')}
          ${fila('Recursos',recursos.length)}
          ${fila('Consentimiento',consent?.status==='active'?'Activo':'No confirmado')}
          ${fila('Task',task?.status||'No incluido')}
          ${fila('Informes IA incluidos',reportes.length)}
          ${fila('Envío','No realizado')}
        </div>
        <h3>Recursos incluidos</h3><div class="r30-count-grid">${resumen}</div>
        <h3>Información que contiene el Bundle</h3><div class="r30-resource-list">${listado}</div>
        <details class="r30-json-details"><summary>Ver JSON FHIR completo (datos clínicos sintéticos)</summary><pre class="r30-json"></pre><button type="button" class="btn btn-secondary" data-copy-bundle>Copiar JSON</button></details>
        <p class="muted small-text">El backend verifica autorización del médico remitente, origen sintético del paciente y consentimiento vigente. Los informes no aprobados no se incluyen.</p>
      </div>`);
    // textContent evita interpretar el contenido FHIR como HTML.
    m.element.querySelector('.r30-json').textContent=JSON.stringify(bundle,null,2);
    m.element.querySelector('[data-copy-bundle]').addEventListener('click',async()=>{
      try{await navigator.clipboard.writeText(JSON.stringify(bundle,null,2));showToast('Bundle copiado','success');}
      catch{showToast('No se pudo copiar; selecciona el JSON manualmente','warning');}
    });
  }catch(error){showToast(`Vista previa R30: ${error.message}`,'error',6500);}
  finally{if(boton){boton.disabled=false;boton.textContent='Ver Bundle FHIR R30';}}
}
