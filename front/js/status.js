import {apiGet} from "./api.js";
import {isRole} from "./auth.js";

const services=[
  {key:"api",label:"API",path:"/",allowed:()=>true},
  {key:"db",label:"BD",path:"/estado-bd",allowed:()=>true},
  {key:"fhir",label:"FHIR",path:"/fhir/estado",allowed:()=>isRole("Medico")},
  {key:"pacs",label:"PACS",path:"/pacs/estado",allowed:()=>isRole("Medico")},
];
let timer=null;

function pill(s,state,detail=""){
  return `<div class="service-pill ${state}"><span class="status-dot"></span><span>${s.label}</span>${detail?`<small>${detail}</small>`:""}</div>`;
}
export async function refreshStatus(){
  const el=document.getElementById("status-strip"); if(!el) return;
  el.innerHTML=services.map(s=>pill(s,"loading","Comprobando")).join("");
  const results=await Promise.all(services.map(async s=>{
    if(!s.allowed()) return {s,state:"restricted",detail:"Restringido"};
    try{ const data=await apiGet(s.path); return {s,state:"ok",detail:data?.estado||"Disponible"}; }
    catch(e){ return {s,state:"error",detail:e.status===403?"Restringido":"Sin conexión"}; }
  }));
  el.innerHTML=results.map(x=>pill(x.s,x.state,x.detail)).join("");
}
export function startStatusMonitor(){ stopStatusMonitor(); refreshStatus(); timer=setInterval(refreshStatus,30000); }
export function stopStatusMonitor(){ if(timer) clearInterval(timer); timer=null; }
