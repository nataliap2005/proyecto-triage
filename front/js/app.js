import {login,logout,restoreSession,getCurrentUser,initials,isRole} from "./auth.js";
import {startStatusMonitor,stopStatusMonitor} from "./status.js";
import {renderPacienteWorkspace} from "./pacientes.js";
import {renderUsuarios,renderSecurity,renderAuditoria} from "./admin.js";
import {renderFacturacion} from "./facturacion.js";
import {renderMisReportes,renderMisEncuentros} from "./paciente_portal.js";
import {renderRemisiones} from "./remisiones.js";
import {showToast,escapeHtml} from "./ui.js";

const loginView=document.getElementById("vista-login"),appView=document.getElementById("vista-app"),form=document.getElementById("login-form"),msg=document.getElementById("login-mensaje"),main=document.getElementById("contenido-principal"),nav=document.getElementById("nav-principal");
const routes={
  inicio:{label:"Inicio",icon:"⌂",roles:["Admin","Medico","Especialista","Contable","Paciente"],render:renderHome},
  paciente:{label:"Paciente / Historia",icon:"♙",roles:["Medico"],render:c=>renderPacienteWorkspace(c)},
  remisiones:{label:"Mis remisiones",icon:"↗",roles:["Especialista"],render:renderRemisiones},
  miHistoria:{label:"Mi historia",icon:"♡",roles:["Paciente"],render:c=>renderPacienteWorkspace(c,{self:true})},
  misReportes:{label:"Mis reportes",icon:"✎",roles:["Paciente"],render:renderMisReportes},
  misEncuentros:{label:"Mis encuentros",icon:"☰",roles:["Paciente"],render:renderMisEncuentros},
  usuarios:{label:"Usuarios",icon:"⚙",roles:["Admin"],render:renderUsuarios},
  seguridad:{label:"Seguridad",icon:"🔒",roles:["Admin"],render:renderSecurity},
  auditoria:{label:"Auditoría",icon:"☷",roles:["Admin"],render:renderAuditoria},
  facturacion:{label:"Facturación",icon:"$",roles:["Contable"],render:renderFacturacion},
};
function showLogin(){stopStatusMonitor();loginView.hidden=false;appView.hidden=true;msg.textContent="";}
function showApp(){const u=getCurrentUser();loginView.hidden=true;appView.hidden=false;document.getElementById("usuario-actual").textContent=u.username;document.getElementById("rol-actual").textContent=u.rol;document.getElementById("user-avatar").textContent=initials(u);buildNav();startStatusMonitor();navigate("inicio");}
function buildNav(){const role=getCurrentUser().rol;nav.innerHTML=Object.entries(routes).filter(([,r])=>r.roles.includes(role)).map(([k,r])=>`<button class="nav-button" data-view="${k}" type="button"><span class="nav-icon">${r.icon}</span>${escapeHtml(r.label)}</button>`).join("");nav.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>navigate(b.dataset.view));}
async function navigate(key){const r=routes[key];if(!r||!r.roles.includes(getCurrentUser().rol))return;document.querySelectorAll(".nav-button").forEach(b=>b.classList.toggle("active",b.dataset.view===key));document.getElementById("page-title").textContent=r.label;document.getElementById("page-eyebrow").textContent=getCurrentUser().rol;main.innerHTML="";try{await r.render(main);}catch(e){main.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}}
async function renderHome(container){const u=getCurrentUser();let cards="";if(isRole("Admin"))cards='<div class="metric"><strong>Usuarios</strong><span>Crear, desbloquear, eliminar y restaurar cuentas</span></div><div class="metric"><strong>Seguridad</strong><span>Eventos de autenticación</span></div><div class="metric"><strong>Auditoría</strong><span>Trazabilidad de cambios</span></div>';else if(isRole("Medico"))cards='<div class="metric"><strong>Pacientes</strong><span>Búsqueda por documento</span></div><div class="metric"><strong>Historia</strong><span>Eventos clínicos integrados</span></div><div class="metric"><strong>FHIR</strong><span>Sincronización clínica</span></div><div class="metric"><strong>PACS</strong><span>Visor de imágenes médicas</span></div>';else if(isRole("Especialista"))cards='<div class="metric"><strong>Remisiones</strong><span>Reciba, acepte y atienda pacientes remitidos</span></div><div class="metric"><strong>Historia clínica</strong><span>Acceso restringido a remisiones aceptadas</span></div>';else if(isRole("Paciente"))cards='<div class="metric"><strong>Mi historia</strong><span>Consulta de información propia</span></div><div class="metric"><strong>Mis reportes</strong><span>Reporte de síntomas previos</span></div><div class="metric"><strong>Mis encuentros</strong><span>Seguimiento clínico</span></div><div class="metric"><strong>Imágenes</strong><span>Estudios vinculados</span></div>';else cards='<div class="metric"><strong>Facturación</strong><span>Consulta y creación de facturas de encuentros finalizados</span></div>';
  container.innerHTML=`<section class="page-hero"><div><p class="eyebrow">Sesión activa</p><h2>Bienvenido, ${escapeHtml(u.username)}</h2><p class="muted">El contenido y las acciones se adaptan al rol <strong>${escapeHtml(u.rol)}</strong>. Los accesos siguen siendo validados por el backend.</p></div><span class="badge success">JWT validado</span></section><section class="grid grid-4">${cards}</section><section class="card"><h3>Arquitectura activa</h3><p class="muted">Frontend SPA → FastAPI → Neon PostgreSQL / HAPI FHIR R4 / Orthanc PACS. Use los indicadores superiores para verificar disponibilidad.</p></section>`;}
form.addEventListener("submit",async e=>{e.preventDefault();msg.textContent="Ingresando…";document.getElementById("login-button").disabled=true;try{await login(document.getElementById("username").value.trim(),document.getElementById("password").value);form.reset();showApp();}catch(err){msg.textContent=err.message;showToast(err.message,"error");}finally{document.getElementById("login-button").disabled=false;}});
document.getElementById("toggle-password").onclick=()=>{const p=document.getElementById("password");p.type=p.type==="password"?"text":"password";};
document.getElementById("cerrar-sesion").onclick=()=>{logout();showLogin();};document.getElementById("menu-toggle").onclick=()=>document.querySelector(".sidebar").classList.toggle("open");
window.addEventListener("auth:expired",e=>{if(appView.hidden)return;logout();showLogin();showToast(e.detail?.message||"La sesión expiró. Ingrese nuevamente.","warning")});
(async()=>{const u=await restoreSession();u?showApp():showLogin();})();
