import {apiBlob} from "./api.js";

let objectUrl=null;
const state={brightness:100,contrast:100,zoom:1,x:0,y:0,invert:0,dragging:false,lastX:0,lastY:0};
function cleanup(){ if(objectUrl){URL.revokeObjectURL(objectUrl);objectUrl=null;} }
function transform(img){
  if(!img)return;
  img.style.filter=`brightness(${state.brightness}%) contrast(${state.contrast}%) invert(${state.invert}%)`;
  img.style.transform=`translate(${state.x}px, ${state.y}px) scale(${state.zoom})`;
}
function reset(img,controls=true){
  Object.assign(state,{brightness:100,contrast:100,zoom:1,x:0,y:0,invert:0,dragging:false});
  transform(img);
  if(controls){
    const b=document.getElementById("viewer-brightness"),c=document.getElementById("viewer-contrast");
    if(b)b.value=100;if(c)c.value=100;
  }
}
export async function loadPreview(instanceId){
  const img=document.getElementById("dicom-preview"); const ph=document.getElementById("viewer-placeholder");
  if(!img) return;
  ph.textContent="Cargando imagen desde PACS…"; ph.hidden=false; img.hidden=true;
  cleanup();
  try{
    const blob=await apiBlob(`/pacs/instancias/${encodeURIComponent(instanceId)}/preview`);
    objectUrl=URL.createObjectURL(blob); img.src=objectUrl; img.hidden=false; ph.hidden=true; reset(img);
  }catch(e){ ph.textContent=`No fue posible cargar el preview: ${e.message}`; ph.hidden=false; img.hidden=true; throw e; }
}
export function bindViewer(){
  const stage=document.getElementById("viewer-stage"), img=document.getElementById("dicom-preview");
  if(!stage||!img)return;
  document.getElementById("viewer-brightness")?.addEventListener("input",e=>{state.brightness=Number(e.target.value);transform(img)});
  document.getElementById("viewer-contrast")?.addEventListener("input",e=>{state.contrast=Number(e.target.value);transform(img)});
  document.getElementById("viewer-zoom-in")?.addEventListener("click",()=>{state.zoom=Math.min(5,state.zoom+.2);transform(img)});
  document.getElementById("viewer-zoom-out")?.addEventListener("click",()=>{state.zoom=Math.max(.2,state.zoom-.2);transform(img)});
  document.getElementById("viewer-invert")?.addEventListener("click",()=>{state.invert=state.invert?0:100;transform(img)});
  document.getElementById("viewer-reset")?.addEventListener("click",()=>reset(img));
  stage.addEventListener("wheel",e=>{e.preventDefault();state.zoom=Math.max(.2,Math.min(5,state.zoom+(e.deltaY<0?.1:-.1)));transform(img)},{passive:false});
  stage.addEventListener("pointerdown",e=>{state.dragging=true;state.lastX=e.clientX;state.lastY=e.clientY;stage.classList.add("dragging");stage.setPointerCapture(e.pointerId)});
  stage.addEventListener("pointermove",e=>{if(!state.dragging)return;state.x+=e.clientX-state.lastX;state.y+=e.clientY-state.lastY;state.lastX=e.clientX;state.lastY=e.clientY;transform(img)});
  const stop=()=>{state.dragging=false;stage.classList.remove("dragging")};stage.addEventListener("pointerup",stop);stage.addEventListener("pointercancel",stop);
}
export function destroyViewer(){cleanup()}
