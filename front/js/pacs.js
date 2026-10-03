import {api,apiGet} from "./api.js";
import {isRole} from "./auth.js";
import {loadPreview,bindViewer,destroyViewer} from "./viewer.js";
import {formatDate,escapeHtml,showToast} from "./ui.js";

let studies=[];
const MAX_DICOM_BYTES=20*1024*1024;

function studyButton(s){
  return `<button class="study-card" data-study="${s.id_estudio}"><strong>${escapeHtml(s.examen||s.descripcion||"Estudio de imagen")}</strong><div class="study-meta"><span class="badge info">${escapeHtml(s.modalidad||"DICOM")}</span><span>${formatDate(s.fecha_estudio||s.created_at)}</span>${s.nivel_triage?`<span>Triage ${s.nivel_triage}</span>`:""}</div><div class="muted small-text" style="margin-top:.35rem">${escapeHtml(s.descripcion||"")}</div></button>`;
}

function uploadCard(historia){
  if(!isRole("Medico")) return "";
  const encuentros=(historia?.encuentros||[]).filter(e=>(e.examenes||[]).length>0);
  const opciones=encuentros.map(e=>`<option value="${e.id_encuentro}">Encuentro #${e.id_encuentro} · ${formatDate(e.fecha_hora_ingreso)} · ${escapeHtml(e.estado||"")}</option>`).join("");
  return `<section class="card dicom-upload-card">
    <div class="section-head"><div><h3>Cargar estudio DICOM</h3><div class="muted small-text">La imagen quedará relacionada con este paciente, un encuentro y un examen existente.</div></div><span class="badge info">.dcm · máx. 20 MB</span></div>
    ${encuentros.length?`<form id="dicom-upload-form" class="stack-form">
      <div class="grid grid-2">
        <label>Encuentro
          <select id="dicom-encuentro" name="id_encuentro" required>${opciones}</select>
        </label>
        <label>Examen
          <select id="dicom-examen" name="id_examen" required></select>
        </label>
      </div>
      <label>Descripción del estudio (opcional)
        <input id="dicom-descripcion" name="descripcion" maxlength="250" placeholder="Ej. Radiografía de tórax">
      </label>
      <label>Archivo DICOM
        <input id="dicom-file" name="dicom" type="file" accept=".dcm,application/dicom" required>
      </label>
      <div id="dicom-file-info" class="muted small-text">Seleccione un archivo .dcm de hasta 20 MB.</div>
      <div class="actions"><button id="dicom-upload-button" class="btn btn-primary" type="submit">Subir imagen al PACS</button></div>
    </form>`:`<div class="history-empty"><strong>No hay exámenes disponibles para asociar una imagen.</strong><p>Primero cree un encuentro y solicite un examen de imagen para este paciente.</p></div>`}
  </section>`;
}

function studiesPanel(){
  if(!studies.length){
    return `<div class="empty-state"><strong>Sin imágenes asociadas</strong><p>El paciente todavía no tiene estudios DICOM relacionados.</p></div>`;
  }
  return `<div class="pacs-layout"><aside><div class="section-head"><div><h3>Estudios</h3><span class="muted small-text">${studies.length} estudio(s)</span></div></div><div id="study-list" class="study-list">${studies.map(studyButton).join("")}</div></aside><section><div id="viewer-info" class="viewer-info"><strong>Seleccione un estudio</strong><div class="muted small-text">Se consultarán sus instancias desde Orthanc.</div></div><div class="viewer-shell" style="margin-top:.8rem"><div class="viewer-toolbar"><label>Brillo <input id="viewer-brightness" type="range" min="20" max="220" value="100"></label><label>Contraste <input id="viewer-contrast" type="range" min="20" max="220" value="100"></label><button id="viewer-zoom-out" class="btn btn-secondary" type="button">− Zoom</button><button id="viewer-zoom-in" class="btn btn-secondary" type="button">+ Zoom</button><button id="viewer-invert" class="btn btn-secondary" type="button">Invertir</button><button id="viewer-reset" class="btn btn-secondary" type="button">Reset</button><select id="instance-select" class="instance-select" title="Instancia DICOM"><option value="">Instancia</option></select></div><div id="viewer-stage" class="viewer-stage"><div id="viewer-placeholder" class="viewer-placeholder">Seleccione un estudio de la lista.</div><img id="dicom-preview" class="viewer-image" alt="Preview DICOM" hidden></div></div></section></div>`;
}

export async function renderPacs(documento,container){
  destroyViewer();
  container.innerHTML='<div class="card">Cargando estudios de imagen…</div>';
  let historia=null;
  try{
    const tareas=[apiGet(`/pacientes/${documento}/imagenes`)];
    if(isRole("Medico")) tareas.push(apiGet(`/pacientes/${documento}/historia-clinica`));
    const resultados=await Promise.all(tareas);
    studies=resultados[0]||[];
    historia=resultados[1]||null;
  }catch(e){
    container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;
    return;
  }

  container.innerHTML=`${uploadCard(historia)}${studiesPanel()}`;
  bindUpload(documento,container,historia);

  if(studies.length){
    bindViewer();
    container.querySelectorAll("[data-study]").forEach(btn=>btn.addEventListener("click",()=>selectStudy(Number(btn.dataset.study),btn)));
  }
}

function bindUpload(documento,container,historia){
  const form=container.querySelector("#dicom-upload-form");
  if(!form) return;

  const encuentros=historia?.encuentros||[];
  const encuentroSelect=form.querySelector("#dicom-encuentro");
  const examenSelect=form.querySelector("#dicom-examen");
  const fileInput=form.querySelector("#dicom-file");
  const fileInfo=form.querySelector("#dicom-file-info");
  const submit=form.querySelector("#dicom-upload-button");

  const renderExamenes=()=>{
    const encuentro=encuentros.find(e=>String(e.id_encuentro)===encuentroSelect.value);
    const examenes=encuentro?.examenes||[];
    examenSelect.innerHTML=examenes.map(x=>`<option value="${x.id_examen}">${escapeHtml(x.nombre||`Examen #${x.id_examen}`)}${x.estado?` · ${escapeHtml(x.estado)}`:""}</option>`).join("");
    examenSelect.disabled=!examenes.length;
  };

  encuentroSelect.addEventListener("change",renderExamenes);
  renderExamenes();

  fileInput.addEventListener("change",()=>{
    const file=fileInput.files?.[0];
    if(!file){fileInfo.textContent="Seleccione un archivo .dcm de hasta 20 MB.";return;}
    const mb=(file.size/1024/1024).toFixed(2);
    fileInfo.textContent=`${file.name} · ${mb} MB`;
    fileInfo.classList.toggle("text-danger",file.size>MAX_DICOM_BYTES);
  });

  form.addEventListener("submit",async e=>{
    e.preventDefault();
    const file=fileInput.files?.[0];
    if(!file){showToast("Seleccione un archivo DICOM","error");return;}
    if(!file.name.toLowerCase().endsWith(".dcm")){showToast("El archivo debe tener extensión .dcm","error");return;}
    if(file.size>MAX_DICOM_BYTES){showToast("El archivo supera el límite de 20 MB","error");return;}
    if(!examenSelect.value){showToast("Seleccione un examen para relacionar la imagen","error");return;}

    const params=new URLSearchParams({
      id_paciente:String(documento),
      id_encuentro:encuentroSelect.value,
      id_examen:examenSelect.value,
    });
    const descripcion=form.querySelector("#dicom-descripcion").value.trim();
    if(descripcion) params.set("descripcion",descripcion);

    submit.disabled=true;
    submit.textContent="Subiendo…";
    try{
      await api(`/pacs/estudios?${params.toString()}`,{
        method:"POST",
        body:file,
        headers:{"Content-Type":"application/dicom"}
      });
      showToast("Imagen DICOM almacenada y vinculada al paciente","success");
      await renderPacs(documento,container);
    }catch(err){
      showToast(err.message,"error");
      submit.disabled=false;
      submit.textContent="Subir imagen al PACS";
    }
  });
}

async function selectStudy(id,button){
  document.querySelectorAll(".study-card").forEach(x=>x.classList.toggle("active",x===button));
  const study=studies.find(x=>x.id_estudio===id);
  const info=document.getElementById("viewer-info");
  const select=document.getElementById("instance-select");
  info.innerHTML=`<strong>${escapeHtml(study?.examen||study?.descripcion||"Estudio")}</strong><div class="muted small-text">${escapeHtml(study?.modalidad||"DICOM")} · ${formatDate(study?.fecha_estudio||study?.created_at)} · Encuentro ${study?.id_encuentro??"—"}</div>`;
  try{
    const instances=await apiGet(`/pacs/estudios/${id}/instancias`);
    const ids=normalizeInstances(instances);
    select.innerHTML=ids.length?ids.map((x,i)=>`<option value="${escapeHtml(x)}">Instancia ${i+1}</option>`).join(""):'<option value="">Sin instancias</option>';
    select.onchange=()=>select.value&&loadPreview(select.value).catch(()=>{});
    if(ids[0]) await loadPreview(ids[0]);
  }catch(e){showToast(e.message,"error");}
}

function normalizeInstances(data){
  if(!data)return[];
  const arr=Array.isArray(data)?data:(data.instances||data.Instances||[]);
  return arr.map(x=>typeof x==="string"?x:(x.ID||x.id||x.instance_id)).filter(Boolean);
}
