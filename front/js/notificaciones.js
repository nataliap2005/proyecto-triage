// notificaciones.js — bandeja persistente (R18). Sobrevive a recargar la página
// porque vive en la base de datos, no en el navegador.
import {apiGet,apiPatch} from "./api.js";
import {escapeHtml,formatDate,showToast} from "./ui.js";
import {refrescarPendientes} from "./pendientes.js";

const ETIQUETAS={
  cuenta_bloqueada:"Cuenta bloqueada",
  remision_recibida:"Remisión recibida",
  remision_aceptada:"Remisión aceptada",
  remision_rechazada:"Remisión rechazada",
  observacion_fhir:"Resultado FHIR",
};
export const etiquetaEvento=tipo=>ETIQUETAS[tipo]||tipo;

export async function renderNotificaciones(container){
  container.innerHTML=`
    <section class="card">
      <div class="card-head">
        <h3>Bandeja de notificaciones</h3>
        <button id="notif-leer-todas" class="btn btn-secondary" type="button">Marcar todas como leídas</button>
      </div>
      <div id="notif-lista" class="notif-lista"><p class="muted">Cargando…</p></div>
    </section>`;

  container.querySelector("#notif-leer-todas").onclick=async()=>{
    try{
      await apiPatch("/notificaciones/leer-todas");
      await pintarLista(container);
      refrescarPendientes();
    }catch(e){ showToast(e.message,"error"); }
  };

  await pintarLista(container);
}

async function pintarLista(container){
  const lista=container.querySelector("#notif-lista");
  const items=await apiGet("/notificaciones?limite=100");

  if(!items.length){
    lista.innerHTML='<p class="muted">No tienes notificaciones.</p>';
    return;
  }

  // escapeHtml en todo lo que viene del servidor: un mensaje nunca se ejecuta como HTML.
  lista.innerHTML=items.map(n=>`
    <article class="notif-item ${n.leida?"":"no-leida"}" data-id="${Number(n.id)}">
      <div>
        <span class="badge">${escapeHtml(etiquetaEvento(n.tipo))}</span>
        <p>${escapeHtml(n.mensaje)}</p>
        <small class="muted">${formatDate(n.fecha)}</small>
      </div>
      ${n.leida?"":'<button class="btn btn-ghost" data-leer type="button">Marcar leída</button>'}
    </article>`).join("");

  lista.querySelectorAll("[data-leer]").forEach(boton=>{
    boton.onclick=async()=>{
      const item=boton.closest(".notif-item");
      try{
        await apiPatch(`/notificaciones/${item.dataset.id}/leer`);
        item.classList.remove("no-leida");
        boton.remove();
        refrescarPendientes();
      }catch(e){ showToast(e.message,"error"); }
    };
  });
}