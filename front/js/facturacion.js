import {apiGet,apiPost} from "./api.js";
import {escapeHtml,formatDate,showToast,modal} from "./ui.js";
import {isRole} from "./auth.js";

const money=v=>new Intl.NumberFormat("es-CO",{style:"currency",currency:"COP",maximumFractionDigits:0}).format(Number(v||0));

export async function renderFacturacion(container){
  container.innerHTML='<div class="card">Cargando facturación…</div>';
  const refresh=()=>renderFacturacion(container);
  try{
    const rows=await apiGet("/facturas");
    container.innerHTML=`<div class="card"><div class="section-head"><div><h2>Facturación</h2><p class="muted">Facturas asociadas a encuentros finalizados.</p></div>${isRole("Contable")?'<button id="new-factura" class="btn btn-primary" type="button">+ Nueva factura</button>':""}</div>${rows.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Factura</th><th>Paciente</th><th>Encuentro</th><th>Fecha</th><th>Total</th><th>Estado</th><th></th></tr></thead><tbody>${rows.map(f=>`<tr><td>${escapeHtml(f.numero_factura||f.id_factura)}</td><td>${escapeHtml(f.id_paciente)}</td><td>${escapeHtml(f.id_encuentro)}</td><td>${formatDate(f.fecha_emision)}</td><td>${money(f.total)}</td><td><span class="badge info">${escapeHtml(f.estado||"activa")}</span></td><td><button class="btn btn-secondary" data-ver="${f.id_factura}" type="button">Detalle</button></td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">No hay facturas registradas.</div>'}</div>`;
    container.querySelector("#new-factura")?.addEventListener("click",()=>nuevaFacturaModal(refresh));
    container.querySelectorAll("[data-ver]").forEach(b=>b.onclick=()=>detalleModal(b.dataset.ver));
  }catch(e){container.innerHTML=`<div class="error-box">${escapeHtml(e.message)}</div>`;}
}

async function detalleModal(id){
  try{
    const f=await apiGet(`/facturas/${id}`);
    const det=f.detalles||[];
    modal(`Factura ${f.numero_factura||f.id_factura}`,`<p class="muted">Encuentro ${escapeHtml(f.id_encuentro)} · Paciente ${escapeHtml(f.id_paciente)}${f.concepto?` · ${escapeHtml(f.concepto)}`:""}</p>${det.length?`<div class="table-wrap"><table class="data-table"><thead><tr><th>Concepto</th><th>Cant.</th><th>Valor unit.</th><th>Total</th></tr></thead><tbody>${det.map(d=>`<tr><td>${escapeHtml(d.concepto)}</td><td>${escapeHtml(d.cantidad)}</td><td>${money(d.valor_unitario)}</td><td>${money(d.valor_total)}</td></tr>`).join("")}</tbody></table></div>`:'<div class="empty-state">Sin detalles.</div>'}<p><strong>Total: ${money(f.total)}</strong></p>`);
  }catch(e){showToast(e.message,"error");}
}

function detalleRow(){
  return `<div class="grid grid-3 detalle-row"><label>Concepto<input name="d_concepto" maxlength="200"></label><label>Cantidad<input name="d_cantidad" type="number" min="1" value="1"></label><label>Valor unitario<input name="d_valor" type="number" min="0" step="any"></label></div>`;
}

function nuevaFacturaModal(refresh){
  const m=modal("Nueva factura",`<form id="f-factura" class="stack-form">
    <div class="grid grid-2"><label>ID del encuentro (finalizado)<input name="id_encuentro" type="number" min="1" required></label><label>Número de factura<input name="numero_factura" maxlength="50" required></label></div>
    <label>Concepto (opcional)<input name="concepto"></label>
    <label class="check-row"><input type="checkbox" name="incluir_prescripciones_dispensadas" checked> Incluir prescripciones dispensadas</label>
    <label class="check-row"><input type="checkbox" name="incluir_examenes_completados" checked> Incluir exámenes completados</label>
    <div><strong>Detalles adicionales</strong><div id="detalles">${detalleRow()}</div><button id="add-detalle" class="btn btn-ghost" type="button">+ Agregar línea</button></div>
    <button class="btn btn-primary" type="submit">Crear factura</button></form>`);
  const form=m.element.querySelector("#f-factura");
  m.element.querySelector("#add-detalle").onclick=()=>m.element.querySelector("#detalles").insertAdjacentHTML("beforeend",detalleRow());
  form.onsubmit=async e=>{
    e.preventDefault();
    const fd=new FormData(form);
    const detalles=[...m.element.querySelectorAll(".detalle-row")].map(r=>({
      concepto:r.querySelector('[name=d_concepto]').value.trim(),
      cantidad:Number(r.querySelector('[name=d_cantidad]').value||1),
      valor_unitario:Number(r.querySelector('[name=d_valor]').value||0)
    })).filter(d=>d.concepto);
    const body={
      id_encuentro:Number(fd.get("id_encuentro")),
      numero_factura:fd.get("numero_factura").trim(),
      concepto:fd.get("concepto").trim()||null,
      incluir_prescripciones_dispensadas:form.incluir_prescripciones_dispensadas.checked,
      incluir_examenes_completados:form.incluir_examenes_completados.checked,
      detalles_adicionales:detalles
    };
    try{await apiPost("/facturas",body);showToast("Factura creada","success");m.close();await refresh();}
    catch(err){showToast(err.message,"error");}
  };
}
