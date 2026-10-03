import {apiGet,apiPost,apiPatch,apiDelete} from "./api.js";
import {escapeHtml,formatDate,showToast,modal} from "./ui.js";

export async function renderUsuarios(container){
  container.innerHTML='<div class="card">Cargando usuarios…</div>';
  try{
    const users=await apiGet("/usuarios");
    container.innerHTML=`<div class="admin-grid"><div class="admin-toolbar"><div><h2>Gestión de usuarios</h2><p class="muted">Administración, restauración y desbloqueo de cuentas.</p></div><button id="new-user" class="btn btn-primary">Crear usuario</button></div><div class="table-wrap"><table class="data-table"><thead><tr><th>Documento</th><th>Usuario</th><th>Nombre</th><th>Rol</th><th>Especialidad</th><th>Estado</th><th>Acciones</th></tr></thead><tbody>${users.map(rowUser).join("")}</tbody></table></div></div>`;
    bindUserActions(container);
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
function rowUser(u){
  const active=u.estado&&!u.is_deleted;
  return `<tr><td>${u.numero_documento_usuario}</td><td>${escapeHtml(u.username)}</td><td>${escapeHtml(`${u.nombres||""} ${u.apellidos||""}`)}</td><td><span class="badge info">${escapeHtml(u.rol)}</span></td><td>${escapeHtml(u.especialidades||"—")}</td><td><span class="badge ${active?'success':'danger'}">${active?'Activo':'Inactivo'}</span></td><td><div class="actions"><button class="btn btn-secondary" data-unlock="${u.numero_documento_usuario}">Desbloquear</button>${u.is_deleted?`<button class="btn btn-success" data-restore="${u.numero_documento_usuario}">Restaurar</button>`:`<button class="btn btn-danger" data-delete="${u.numero_documento_usuario}">Eliminar</button>`}</div></td></tr>`;
}
function bindUserActions(container){
  container.querySelector("#new-user")?.addEventListener("click",newUserModal);
  container.querySelectorAll("[data-unlock]").forEach(b=>b.onclick=async()=>action(()=>apiPatch(`/usuarios/${b.dataset.unlock}/desbloquear`),"Usuario desbloqueado",()=>renderUsuarios(container)));
  container.querySelectorAll("[data-restore]").forEach(b=>b.onclick=async()=>action(()=>apiPatch(`/usuarios/${b.dataset.restore}/restaurar`),"Usuario restaurado",()=>renderUsuarios(container)));
  container.querySelectorAll("[data-delete]").forEach(b=>b.onclick=async()=>{if(confirm("¿Eliminar lógicamente este usuario?"))await action(()=>apiDelete(`/usuarios/${b.dataset.delete}`),"Usuario eliminado",()=>renderUsuarios(container));});
}
async function action(fn,msg,after){try{await fn();showToast(msg,"success");after?.()}catch(e){showToast(e.message,"error")}}
async function newUserModal(){
  try{
    const [roles,especialidades]=await Promise.all([apiGet("/roles"),apiGet("/especialidades")]);
    const roleOptions=roles.map(r=>`<option value="${r.id_rol}" data-role="${escapeHtml(r.nombre)}">${escapeHtml(r.nombre)}</option>`).join("");
    const espOptions=especialidades.map(e=>`<option value="${e.id_especialidad}">${escapeHtml(e.nombre)}</option>`).join("");
    const m=modal("Crear usuario",`<form id="new-user-form" class="stack-form"><div class="grid grid-2"><label>Documento<input name="numero_documento_usuario" type="number" required></label><label>Rol<select id="new-role" name="id_rol" required><option value="">Seleccione…</option>${roleOptions}</select></label><label id="specialty-field" hidden>Especialidad<select name="id_especialidad"><option value="">Seleccione…</option>${espOptions}</select></label><label>Usuario<input name="username" minlength="3" maxlength="50" pattern="[A-Za-z0-9._-]+" required></label><label>Contraseña<input name="password" type="password" minlength="8" maxlength="128" required></label><label>Nombres<input name="nombres" required></label><label>Apellidos<input name="apellidos" required></label><label>Correo<input name="email" type="email"></label><label>Teléfono<input name="telefono"></label></div><button class="btn btn-primary" type="submit">Crear usuario</button></form><p class="muted small-text">Solo el rol Especialista requiere seleccionar una especialidad.</p>`);
    const roleSelect=m.element.querySelector("#new-role"),specialtyField=m.element.querySelector("#specialty-field"),specialtySelect=specialtyField.querySelector("select");
    const syncSpecialty=()=>{const selected=roleSelect.options[roleSelect.selectedIndex];const isSpecialist=selected?.dataset.role==="Especialista";specialtyField.hidden=!isSpecialist;specialtySelect.required=isSpecialist;if(!isSpecialist)specialtySelect.value="";};
    roleSelect.addEventListener("change",syncSpecialty);syncSpecialty();
    m.element.querySelector("#new-user-form").onsubmit=async e=>{
      e.preventDefault();const fd=new FormData(e.target);const body=Object.fromEntries(fd.entries());
      body.numero_documento_usuario=Number(body.numero_documento_usuario);body.id_rol=Number(body.id_rol);
      if(body.id_especialidad)body.id_especialidad=Number(body.id_especialidad);else body.id_especialidad=null;
      if(!body.email)body.email=null;if(!body.telefono)body.telefono=null;
      try{const r=await apiPost("/usuarios",body);showToast(r?.paciente_vinculado?"Usuario creado y vinculado a su historia clínica":"Usuario creado","success");m.close();document.querySelector('[data-view="usuarios"]')?.click();}catch(err){showToast(err.message,"error")}
    };
  }catch(e){showToast(e.message,"error")}
}
export async function renderSecurity(container){
  container.innerHTML='<div class="card">Cargando eventos de autenticación…</div>';
  try{const logs=await apiGet("/auth/logs?limite=100");container.innerHTML=`<div class="card"><div class="section-head"><div><h2>Seguridad de acceso</h2><p class="muted">Últimos intentos de autenticación y eventos registrados.</p></div></div>${renderLogs(logs)}</div>`;}catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
export async function renderAuditoria(container){
  container.innerHTML='<div class="card">Cargando auditoría…</div>';
  try{const logs=await apiGet("/auditoria?limite=100");container.innerHTML=`<div class="card"><h2>Auditoría de cambios</h2><p class="muted">Trazabilidad de operaciones sobre registros clínicos y administrativos.</p><div class="table-wrap"><table class="data-table"><thead><tr><th>Fecha</th><th>Tabla</th><th>Registro</th><th>Acción</th><th>Usuario</th><th>Rol</th></tr></thead><tbody>${logs.map(x=>`<tr><td>${formatDate(x.fecha_hora)}</td><td>${escapeHtml(x.tabla_afectada)}</td><td>${escapeHtml(x.registro_id)}</td><td><span class="badge info">${escapeHtml(x.accion)}</span></td><td>${escapeHtml(x.username||x.realizado_por||"—")}</td><td>${escapeHtml(x.rol||"—")}</td></tr>`).join("")}</tbody></table></div></div>`;}catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}
function renderLogs(logs){if(!logs.length)return'<div class="empty-state">No hay eventos registrados.</div>';return `<div class="table-wrap"><table class="data-table"><thead><tr><th>Fecha</th><th>Usuario</th><th>Evento</th><th>Resultado</th><th>Detalle</th></tr></thead><tbody>${logs.map(x=>`<tr><td>${formatDate(x.fecha_hora||x.created_at)}</td><td>${escapeHtml(x.username||x.numero_documento_usuario||"—")}</td><td class="log-event">${escapeHtml(x.evento||x.accion||x.tipo_evento||"—")}</td><td>${escapeHtml(x.resultado ?? x.exitoso ?? "—")}</td><td>${escapeHtml(x.detalle||x.mensaje||"")}</td></tr>`).join("")}</tbody></table></div>`;}
