/* R30: consentimiento de intercambio interinstitucional del paciente autenticado.
 * La UI no decide permisos ni crea remisiones: FastAPI valida rol y vínculo.
 */
import {apiGet, apiPost} from "./api.js";
import {getCurrentUser} from "./auth.js";
import {escapeHtml, showToast} from "./ui.js";

const RUTA = "/fhir/remisiones-r30/consentimiento";
const SOCIO = "socio-piloto";

function formatFecha(fecha) {
  if (!fecha) return "No disponible";
  const d = new Date(fecha);
  return Number.isNaN(d.getTime()) ? "No disponible" : d.toLocaleString("es-CO", {dateStyle: "medium", timeStyle: "short"});
}

export async function renderConsentimientoR30(container) {
  const usuario = getCurrentUser();
  if (!usuario || usuario.rol !== "Paciente") {
    container.innerHTML = '<div class="error-box">Esta sección es exclusiva para pacientes.</div>';
    return;
  }

  const idPaciente = Number(usuario.numero_documento_usuario);
  if (!Number.isSafeInteger(idPaciente) || idPaciente <= 0) {
    container.innerHTML = '<div class="error-box">No fue posible identificar la cuenta del paciente.</div>';
    return;
  }

  container.innerHTML = `<section class="page-hero"><div><p class="eyebrow">Interoperabilidad · R30</p><h2>Consentimiento para compartir información clínica</h2><p class="muted">Decide si autorizas el intercambio de información clínica para una remisión con la institución receptora del piloto.</p></div></section>
    <section class="card r30-consent-card">
      <div class="section-head"><div><h3>Tu autorización</h3><p class="muted small-text">El consentimiento se guarda en el sistema y puede revocarse.</p></div><span id="r30-consent-status" class="badge info" role="status" aria-live="polite">Consultando…</span></div>
      <p id="r30-consent-details" class="muted small-text">Consultando tu consentimiento vigente…</p>
      <div class="r30-consent-details">
        <h4>¿Qué estás autorizando?</h4>
        <p>El envío al <strong>sistema socio del piloto (${escapeHtml(SOCIO)})</strong> de los datos mínimos necesarios para una remisión clínica autorizada.</p>
        <ul>
          <li>Una referencia seudonimizada del paciente y la solicitud de remisión.</li>
          <li>Observaciones clínicas pertinentes, como signos vitales codificados con LOINC.</li>
          <li>Reportes diagnósticos <strong>únicamente si están aprobados</strong>.</li>
          <li>El consentimiento y el estado de seguimiento de la remisión en formato FHIR R4.</li>
        </ul>
        <p class="muted small-text">Esta autorización no crea ni envía por sí sola una remisión. Antes de cualquier envío el backend comprueba el consentimiento, los permisos del profesional y la remisión existente. Para este piloto únicamente se permiten pacientes sintéticos.</p>
      </div>
      <div id="r30-consent-error" class="error-box" role="alert" hidden></div>
      <div id="r30-consent-actions" class="r30-consent-actions" hidden>
        <label class="r30-consent-check"><input id="r30-consent-confirm" type="checkbox"> He leído qué datos se compartirán y entiendo que puedo revocar mi autorización.</label>
        <div class="actions"><button type="button" id="r30-consent-authorize" class="btn btn-primary" disabled>Autorizar intercambio</button><button type="button" id="r30-consent-revoke" class="btn btn-danger" disabled>Revocar autorización</button><button type="button" id="r30-consent-refresh" class="btn btn-secondary">Actualizar estado</button></div>
      </div>
      <p class="muted small-text">Tu decisión quedará registrada en la auditoría. No se transmite información clínica al pulsar “Autorizar”.</p>
    </section>`;

  const $ = selector => container.querySelector(selector);
  const status = $("#r30-consent-status");
  const details = $("#r30-consent-details");
  const errorBox = $("#r30-consent-error");
  const actions = $("#r30-consent-actions");
  const consentCheck = $("#r30-consent-confirm");
  const autorizar = $("#r30-consent-authorize");
  const revocar = $("#r30-consent-revoke");
  const actualizar = $("#r30-consent-refresh");
  let vigente = null;
  let ocupado = false;

  function ponerError(mensaje) {
    errorBox.textContent = mensaje;
    errorBox.hidden = !mensaje;
  }
  function botones() {
    autorizar.disabled = ocupado || vigente === true || !consentCheck.checked;
    revocar.disabled = ocupado || vigente !== true;
    actualizar.disabled = ocupado;
    consentCheck.disabled = ocupado || vigente === true;
  }
  function pintarEstado(info) {
    vigente = Boolean(info.consentimiento_vigente);
    status.className = `badge ${vigente ? "success" : "warning"}`;
    status.textContent = vigente ? "Autorizado" : "No autorizado";
    details.textContent = info.registrado
      ? `Última actualización: ${formatFecha(info.actualizado_at)}. Receptor: ${info.socio || SOCIO}.`
      : "Aún no has registrado un consentimiento para este intercambio.";
    consentCheck.checked = false;
    botones();
  }
  async function cargarEstado() {
    ocupado = true;
    accionesVisibles(false);
    status.textContent = "Consultando…";
    status.className = "badge info";
    ponerError("");
    try {
      const data = await apiGet(`${RUTA}/estado`);
      pintarEstado(data);
    } catch (err) {
      vigente = null;
      status.textContent = "No disponible";
      status.className = "badge warning";
      details.textContent = "No se pudo consultar el consentimiento. No se asume que esté autorizado.";
      ponerError(err.message || "No fue posible consultar el estado.");
    } finally {
      ocupado = false;
      accionesVisibles(true);
      botones();
    }
  }
  function accionesVisibles(visibles) { actions.hidden = !visibles; }
  async function guardar(autoriza) {
    if (ocupado) return;
    if (autoriza && (vigente !== false || !consentCheck.checked)) return;
    if (!autoriza && vigente !== true) return;
    const pregunta = autoriza
      ? "¿Confirmas que autorizas el intercambio de información clínica para remisiones del piloto?"
      : "¿Confirmas que deseas revocar tu autorización? Se impedirán nuevos envíos que requieran este consentimiento.";
    if (!window.confirm(pregunta)) return;
    ocupado = true;
    botones();
    ponerError("");
    try {
      const respuesta = await apiPost(RUTA, {id_paciente: idPaciente, autoriza});
      showToast(respuesta.consentimiento_vigente ? "Consentimiento registrado" : "Consentimiento revocado", "success");
      await cargarEstado();
    } catch (err) {
      ponerError(err.message || "No fue posible guardar la autorización.");
      showToast(err.message || "Error al actualizar el consentimiento", "error");
    } finally {
      ocupado = false;
      botones();
    }
  }
  consentCheck.addEventListener("change", botones);
  autorizar.addEventListener("click", () => guardar(true));
  revocar.addEventListener("click", () => guardar(false));
  actualizar.addEventListener("click", cargarEstado);
  await cargarEstado();
}
