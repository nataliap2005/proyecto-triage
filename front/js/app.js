import {apiGet} from "./api.js";
import {login,logout,restoreSession,getCurrentUser,initials,isRole} from "./auth.js";
import {startStatusMonitor,stopStatusMonitor} from "./status.js";
import {renderPacienteWorkspace,renderListaPacientes} from "./pacientes.js";
import {renderUsuarios,renderSecurity,renderAuditoria,renderPacientesEliminados,renderPapeleraClinica} from "./admin.js";
import {renderFacturacion} from "./facturacion.js";
import {renderUrgencias} from "./urgencias.js";
import {renderMisReportes,renderMisEncuentros} from "./paciente_portal.js";
import {renderRemisiones,renderRemisionesEnviadas} from "./remisiones.js";
import {showToast,escapeHtml,enhanceTables} from "./ui.js";
import {conectarCanal,desconectarCanal} from "./tiempo_real.js";          // NUEVO
import {refrescarPendientes,pintarContadores} from "./pendientes.js";    // NUEVO
import {renderNotificaciones} from "./notificaciones.js";                 // NUEVO
import {renderAlertasEscaladas} from "./alertas.js";
import {renderAsistente} from "./asistente.js";                       // Semana 12: RAG

const loginView=document.getElementById("vista-login");
const appView=document.getElementById("vista-app");
const form=document.getElementById("login-form");
const msg=document.getElementById("login-mensaje");
const main=document.getElementById("contenido-principal");
const nav=document.getElementById("nav-principal");

const tableObserver=new MutationObserver(()=>enhanceTables(main));
tableObserver.observe(main,{childList:true,subtree:true});

const TODOS=["Admin","Medico","Especialista","Contable","Paciente"];


// contador: número que se muestra junto al botón del menú (clave de /pendientes).
// refrescarCon: tipos de evento que vuelven a pintar la vista si está abierta ("*" = todos).
const routes={
  inicio:{label:"Inicio",icon:"⌂",roles:TODOS,render:renderHome},
  notificaciones:{label:"Notificaciones",icon:"🔔",roles:TODOS,render:renderNotificaciones,
                  contador:"notificaciones_no_leidas",refrescarCon:["*"]},                    // NUEVO
  urgencias:{label:"Urgencias",icon:"✚",roles:["Medico"],render:renderUrgencias},
  pacientes:{label:"Pacientes",icon:"☰",roles:["Medico"],render:renderListaPacientes},
  paciente:{label:"Paciente / Historia",icon:"♙",roles:["Medico"],render:c=>renderPacienteWorkspace(c)},
  remisionesEnviadas:{label:"Remisiones enviadas",icon:"↗",roles:["Medico"],render:renderRemisionesEnviadas},
  remisiones:{label:"Mis remisiones",icon:"↗",roles:["Especialista"],render:renderRemisiones,contador:"remisiones_recibidas"},                 // NUEVO
  asistente:{label:"Asistente clínico",icon:"✦",roles:["Medico","Especialista"],render:renderAsistente},   // Semana 12: RAG
  miHistoria:{label:"Mi historia",icon:"♡",roles:["Paciente"],render:c=>renderPacienteWorkspace(c,{self:true})},
  misReportes:{label:"Mis reportes",icon:"✎",roles:["Paciente"],render:renderMisReportes},
  misEncuentros:{label:"Mis encuentros",icon:"☰",roles:["Paciente"],render:renderMisEncuentros},
  usuarios:{label:"Usuarios",icon:"⚙",roles:["Admin"],render:renderUsuarios},
  pacientesEliminados:{label:"Pacientes eliminados",icon:"↺",roles:["Admin"],render:renderPacientesEliminados},
  papeleraClinica:{label:"Papelera clínica",icon:"♻",roles:["Admin"],render:renderPapeleraClinica},
  alertasEscaladas:{label:"Alertas escaladas",icon:"!",roles:["Admin"],render:renderAlertasEscaladas,contador:"alertas_activas",refrescarCon:["alerta_critica_escalada","alerta_reconocida"]},
  seguridad:{label:"Seguridad",icon:"🔒",roles:["Admin"],render:renderSecurity},
  auditoria:{label:"Auditoría",icon:"☷",roles:["Admin"],render:renderAuditoria},
  facturacion:{label:"Facturación",icon:"$",roles:["Admin","Contable"],render:renderFacturacion,refrescarCon:["factura_ia_creada"]},
};

let vistaActual=null;   // NUEVO: para saber qué pantalla repintar cuando llega un evento

function showLogin(){
  desconectarCanal();   // NUEVO
  stopStatusMonitor();
  vistaActual=null;
  loginView.hidden=false;
  appView.hidden=true;
  msg.textContent="";
}

function showApp(){
  const u=getCurrentUser();
  loginView.hidden=true;
  appView.hidden=false;
  document.getElementById("usuario-actual").textContent=u.username;
  document.getElementById("rol-actual").textContent=u.rol;
  document.getElementById("user-avatar").textContent=initials(u);
  buildNav();
  startStatusMonitor();
  conectarCanal();        // NUEVO: R17
  refrescarPendientes();  // NUEVO: R18
  navigate("inicio");
}

function buildNav(){
  const role=getCurrentUser().rol;
  nav.innerHTML=Object.entries(routes)
    .filter(([,r])=>r.roles.includes(role))
    .map(([k,r])=>`<button class="nav-button" data-view="${k}" type="button">`+
      `<span class="nav-icon">${r.icon}</span>${escapeHtml(r.label)}`+
      (r.contador?`<span class="nav-count" data-contador="${r.contador}" hidden></span>`:"")+   // NUEVO
      `</button>`)
    .join("");
  nav.querySelectorAll("[data-view]").forEach(b=>b.onclick=()=>navigate(b.dataset.view));
  pintarContadores(nav);   // NUEVO
}

async function navigate(key){
  const r=routes[key];
  if(!r||!r.roles.includes(getCurrentUser().rol)) return;
  vistaActual=key;   // NUEVO
  document.querySelectorAll(".nav-button").forEach(b=>b.classList.toggle("active",b.dataset.view===key));
  document.getElementById("page-title").textContent=r.label;
  document.getElementById("page-eyebrow").textContent=getCurrentUser().rol;
  main.innerHTML="";
  try{
    await r.render(main);
    enhanceTables(main);
    pintarContadores(main);   // NUEVO: la vista recién pintada puede traer data-contador
  }catch(e){
    main.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;
  }
}

// NUEVO: qué contadores ve cada rol en Inicio (R18).
const CONTADORES_POR_ROL={
  Medico:[["reportes_por_revisar","Reportes de IA por revisar"],["alertas_activas","Alertas activas"]],
  Especialista:[["remisiones_recibidas","Remisiones por responder"],["reportes_por_revisar","Reportes de IA por revisar"],["alertas_activas","Alertas activas"]],
};

async function renderHome(container){
  const u=getCurrentUser();
  let cards="";
  if(isRole("Admin"))cards='<div class="metric"><strong>Usuarios</strong><span>Crear, desbloquear, eliminar y restaurar cuentas</span></div><div class="metric"><strong>Seguridad</strong><span>Eventos de autenticación</span></div><div class="metric"><strong>Auditoría</strong><span>Trazabilidad de cambios</span></div>';
  else if(isRole("Medico"))cards='<div class="metric"><strong>Pacientes</strong><span>Búsqueda por documento</span></div><div class="metric"><strong>Historia</strong><span>Eventos clínicos integrados</span></div><div class="metric"><strong>FHIR</strong><span>Sincronización clínica</span></div><div class="metric"><strong>PACS</strong><span>Visor de imágenes médicas</span></div><div class="metric"><strong>Asistente clínico</strong><span>Preguntas a guías e historia aprobada, con citas</span></div>';
  else if(isRole("Especialista"))cards='<div class="metric"><strong>Remisiones</strong><span>Reciba, acepte y atienda pacientes remitidos</span></div><div class="metric"><strong>Historia clínica</strong><span>Acceso restringido a remisiones aceptadas</span></div>';
  else if(isRole("Paciente"))cards='<div class="metric"><strong>Mi historia</strong><span>Consulta de información propia</span></div><div class="metric"><strong>Mis reportes</strong><span>Reporte de síntomas previos</span></div><div class="metric"><strong>Mis encuentros</strong><span>Seguimiento clínico</span></div><div class="metric"><strong>Imágenes</strong><span>Estudios vinculados</span></div>';
  else cards='<div class="metric"><strong>Facturación</strong><span>Consulta y creación de facturas en MongoDB</span></div>';

  // NUEVO: tarjetas de trabajo pendiente; los números los llena pendientes.js
  const filas=[...(CONTADORES_POR_ROL[u.rol]||[]),["notificaciones_no_leidas","Notificaciones sin leer"]];
  const pendientes=`<section class="card"><h3>Trabajo pendiente</h3><div class="grid grid-4">`+
    filas.map(([clave,texto])=>`<div class="metric"><strong class="metric-num" data-contador="${clave}" data-mostrar-cero>0</strong><span>${escapeHtml(texto)}</span></div>`).join("")+
    `</div><p class="muted small-text">Se actualiza solo, en tiempo real.</p></section>`;

  let atencionActual="";
  if(isRole("Paciente")){
    try{
      const encuentros=await apiGet("/encuentros/mios");
      const activo=(encuentros||[]).find(e=>e.estado!=="finalizado");
      if(activo)atencionActual=`<section class="card"><div class="section-head"><div><p class="eyebrow">Atención actual</p><h3>Encuentro #${activo.id_encuentro}</h3></div><span class="badge info">${escapeHtml(activo.estado)}</span></div><p><strong>Servicio:</strong> ${escapeHtml(activo.servicio||"Urgencias")}</p><p><strong>Motivo:</strong> ${escapeHtml(activo.motivo_consulta||"—")}</p><p class="muted small-text">Su atención está en curso. El nivel de triage aparecerá cuando el profesional complete la clasificación.</p></section>`;
    }catch{}
  }

  container.innerHTML=`<section class="page-hero"><div><p class="eyebrow">Sesión activa</p><h2>Bienvenido, ${escapeHtml(u.username)}</h2><p class="muted">El contenido y las acciones se adaptan al rol <strong>${escapeHtml(u.rol)}</strong>. Los accesos siguen siendo validados por el backend.</p></div><span class="badge success">JWT validado</span></section>${atencionActual}${pendientes}<section class="grid grid-4">${cards}</section><section class="card"><h3>Arquitectura activa</h3><p class="muted">Frontend SPA → FastAPI → Neon PostgreSQL / HAPI FHIR R4 / Orthanc PACS. Use los indicadores superiores para verificar disponibilidad.</p></section>`;
}

form.addEventListener("submit",async e=>{
  e.preventDefault();
  msg.textContent="Ingresando…";
  document.getElementById("login-button").disabled=true;
  try{
    await login(document.getElementById("username").value.trim(),document.getElementById("password").value);
    form.reset();
    showApp();
  }catch(err){
    msg.textContent=err.message;
    showToast(err.message,"error");
  }finally{
    document.getElementById("login-button").disabled=false;
  }
});

document.getElementById("toggle-password").onclick=()=>{const p=document.getElementById("password");p.type=p.type==="password"?"text":"password";};
document.getElementById("cerrar-sesion").onclick=()=>{logout();showLogin();};
document.getElementById("menu-toggle").onclick=()=>document.querySelector(".sidebar").classList.toggle("open");
document.getElementById("btn-notificaciones").onclick=()=>navigate("notificaciones");   // NUEVO

window.addEventListener("auth:expired",e=>{
  if(appView.hidden) return;
  logout();
  showLogin();
  showToast(e.detail?.message||"La sesión expiró. Ingrese nuevamente.","warning");
});

// NUEVO: reacción a cada evento en vivo, sin recargar (R16).
window.addEventListener("tr:evento",e=>{
  const evento=e.detail;
  showToast(evento.mensaje,"info",6000);
  refrescarPendientes();
  const r=routes[vistaActual];
  if(r?.refrescarCon && (r.refrescarCon.includes("*")||r.refrescarCon.includes(evento.tipo))){
    navigate(vistaActual);   // vuelve a pintar solo la vista abierta, si le interesa este evento
  }
});

// NUEVO: al (re)conectar, se recupera lo que pudo llegar mientras el canal estaba caído.
window.addEventListener("tr:conectado",()=>{
  refrescarPendientes();
  if(vistaActual==="notificaciones") navigate("notificaciones");
});

// Abre directamente la ficha desde la cola de Urgencias.
window.addEventListener("app:open-patient",async e=>{
  if(!isRole("Medico")) return;
  vistaActual="paciente";
  document.querySelectorAll(".nav-button").forEach(b=>b.classList.toggle("active",b.dataset.view==="paciente"));
  document.getElementById("page-title").textContent=routes.paciente.label;
  document.getElementById("page-eyebrow").textContent=getCurrentUser().rol;
  main.innerHTML="";
  await renderPacienteWorkspace(main,{documento:e.detail?.documento});
  enhanceTables(main);
});

(async()=>{const u=await restoreSession();u?showApp():showLogin();})();
