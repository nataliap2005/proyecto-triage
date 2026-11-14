import {apiGet, apiPost} from './api.js';
import {escapeHtml, formatDate, modal, showToast} from './ui.js';

// Los secretos de R30 solo se guardan y utilizan en FastAPI; nunca en JavaScript.
export async function consultarEstadoEnvioR30(id, boton, etiqueta){
  if (!Number.isSafeInteger(id) || id <= 0) return;
  boton.disabled = true;
  if (etiqueta) etiqueta.textContent = 'Comprobando envío…';
  try {
    const estado = await apiGet(`/fhir/remisiones-r30/${id}/estado-envio`);
    if (estado.confirmado) {
      boton.disabled = true;
      boton.textContent = 'FHIR enviado';
      if (etiqueta) etiqueta.textContent = `Confirmado: ${estado.recursos ?? '—'} recursos · ${estado.fecha_hora ? formatDate(estado.fecha_hora) : 'sin fecha'}`;
    } else {
      boton.disabled = !estado.puede_enviar;
      boton.textContent = 'Enviar remisión FHIR';
      if (etiqueta) etiqueta.textContent = estado.puede_enviar ? 'Aún no enviada a receptor FHIR' : 'Envío no disponible';
    }
  } catch (err) {
    boton.disabled = true;
    boton.textContent = 'Envío no disponible';
    if (etiqueta) etiqueta.textContent = err.status === 403 ? 'No disponible para esta remisión (consentimiento, origen o permisos)' : `No se pudo consultar el estado: ${err.message}`;
  }
}

export async function confirmarEnvioR30(id, boton, etiqueta){
  if (!Number.isSafeInteger(id) || id <= 0 || boton.disabled) return;
  // Segunda consulta reduce el riesgo de reenviar desde una pestaña desactualizada.
  boton.disabled = true;
  try {
    const estado = await apiGet(`/fhir/remisiones-r30/${id}/estado-envio`);
    if (estado.confirmado || !estado.puede_enviar) {
      await consultarEstadoEnvioR30(id,boton,etiqueta);
      return;
    }
    const ventana = modal(`Confirmar envío FHIR · Remisión #${id}`, `
      <div class="r30-send-confirm">
        <p>Esta acción <strong>sí transmite</strong> datos clínicos sintéticos al receptor FHIR configurado en el servidor.</p>
        <p><strong>Destino:</strong> socio-piloto (prueba local o institución configurada por el backend).</p>
        <p>El servidor volverá a verificar el médico remitente, el consentimiento vigente y los recursos aprobados. No se muestran credenciales institucionales.</p>
        <label class="r30-confirm-label"><input type="checkbox" data-r30-ack> Confirmo que deseo enviar esta remisión FHIR.</label>
        <div class="r30-confirm-actions">
          <button type="button" class="btn btn-secondary" data-r30-cancel>Cancelar</button>
          <button type="button" class="btn btn-primary" data-r30-confirm disabled>Confirmar envío</button>
        </div>
        <p class="muted small-text" data-r30-feedback role="status" aria-live="polite"></p>
      </div>`);
    const aceptar = ventana.element.querySelector('[data-r30-ack]');
    const confirmar = ventana.element.querySelector('[data-r30-confirm]');
    const cancelar = ventana.element.querySelector('[data-r30-cancel]');
    const feedback = ventana.element.querySelector('[data-r30-feedback]');
    const cerrar = () => {ventana.close(); consultarEstadoEnvioR30(id,boton,etiqueta);};
    cancelar.addEventListener('click',cerrar);
    aceptar.addEventListener('change',()=>confirmar.disabled = !aceptar.checked);
    confirmar.addEventListener('click',async()=>{
      confirmar.disabled = true; aceptar.disabled = true; cancelar.disabled = true;
      feedback.textContent = 'Enviando y comprobando confirmación de HAPI FHIR…';
      try {
        const r = await apiPost(`/fhir/remisiones-r30/${id}/enviar`, {});
        if (r.estado !== 'confirmado' || r.respuesta_fhir !== 'transaction-response') {
          throw new Error('El receptor no confirmó la transacción completa');
        }
        feedback.textContent = `Confirmado: ${r.recursos} recursos · Task ${r.task_fhir_id ?? '—'}`;
        showToast(`Remisión FHIR #${id} confirmada (${r.recursos} recursos)`, 'success', 5500);
        boton.disabled = true;
        boton.textContent = 'FHIR enviado';
        if (etiqueta) etiqueta.textContent = `Confirmado: ${r.recursos} recursos`;
        confirmar.textContent = 'Envío confirmado';
        cancelar.disabled = false; cancelar.textContent = 'Cerrar';
        // No reintentar automáticamente una operación de envío.
      } catch (err) {
        feedback.textContent = err.status === 409
          ? 'Esta remisión ya fue enviada. Consulta el estado actualizado.'
          : `No se pudo confirmar el envío (${escapeHtml(err.message)}). Antes de reintentar, verifica el estado.`;
        showToast('No se confirmó el envío. Comprueba el estado antes de reintentar.', 'warning', 6000);
        cancelar.disabled = false; cancelar.textContent = 'Cerrar';
        await consultarEstadoEnvioR30(id,boton,etiqueta);
      }
    });
  } catch(err) {
    showToast(`R30: ${err.message}`,'error',6000);
    await consultarEstadoEnvioR30(id,boton,etiqueta);
  }
}
