export function escapeHtml(v){return String(v??"").replace(/[&<>'"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));}
export function formatDate(v){if(!v)return"—";const d=new Date(v);if(Number.isNaN(d.getTime()))return escapeHtml(v);return new Intl.DateTimeFormat("es-CO",{dateStyle:"medium",timeStyle:"short",timeZone:"America/Bogota"}).format(d)}
export function formatDateOnly(v){if(!v)return"—";const d=new Date(`${String(v).slice(0,10)}T12:00:00`);return Number.isNaN(d.getTime())?escapeHtml(v):new Intl.DateTimeFormat("es-CO",{dateStyle:"medium"}).format(d)}
export function showToast(message,type="info",ms=3500){const c=document.getElementById("toast-container");if(!c)return;const t=document.createElement("div");t.className=`toast ${type}`;t.textContent=message;c.appendChild(t);setTimeout(()=>t.remove(),ms)}
export function initialsFromName(nombres="",apellidos=""){return `${nombres.trim()[0]||""}${apellidos.trim()[0]||""}`.toUpperCase()||"P"}
export function triageBadge(n){return n?`<span class="badge triage-${n}">Triage ${n}</span>`:'<span class="badge">Sin triage</span>'}
export function modal(title,content){const b=document.createElement("div");b.className="modal-backdrop";b.innerHTML=`<div class="modal"><div class="modal-head"><h2>${escapeHtml(title)}</h2><button class="btn btn-ghost" data-close type="button">✕</button></div><div>${content}</div></div>`;document.body.appendChild(b);const close=()=>b.remove();b.querySelector("[data-close]").onclick=close;b.addEventListener("click",e=>{if(e.target===b)close()});return {element:b,close};}


export function enhanceTables(container){
  if(!container)return;
  const filterable=new Set(["Rol","Estado","Origen","Servicio","Acción","Tabla","Especialidad","Triage","Resultado","Evento"]);
  container.querySelectorAll("table.data-table").forEach((table,idx)=>{
    if(table.dataset.enhanced==="1")return;
    table.dataset.enhanced="1";
    const headers=[...table.querySelectorAll("thead th")].map(th=>th.textContent.trim());
    const wrap=table.closest(".table-wrap");
    if(!wrap)return;
    const bar=document.createElement("div");
    bar.className="table-filters";
    bar.innerHTML=`<label class="table-search"><span>Buscar</span><input type="search" placeholder="Buscar en la tabla…" aria-label="Buscar en tabla"></label>`;
    const search=bar.querySelector("input");
    const selects=[];
    headers.forEach((h,i)=>{
      if(!filterable.has(h))return;
      const values=[...new Set([...table.querySelectorAll("tbody tr")].map(tr=>tr.children[i]?.textContent.trim()).filter(Boolean))].sort((a,b)=>a.localeCompare(b,"es"));
      if(values.length<2||values.length>30)return;
      const label=document.createElement("label");
      label.className="table-select-filter";
      label.innerHTML=`<span>${escapeHtml(h)}</span><select aria-label="Filtrar por ${escapeHtml(h)}"><option value="">Todos</option>${values.map(v=>`<option value="${escapeHtml(v)}">${escapeHtml(v)}</option>`).join("")}</select>`;
      bar.appendChild(label);
      selects.push([i,label.querySelector("select")]);
    });
    const count=document.createElement("span");
    count.className="table-filter-count muted small-text";
    bar.appendChild(count);
    wrap.parentNode.insertBefore(bar,wrap);
    // Paginación: solo cambia qué filas se ven, no los datos ni los filtros.
    let page=1,pageSize=10;
    const pager=document.createElement("div");
    pager.className="table-pager";
    pager.innerHTML=`<span class="table-pager-info muted small-text"></span><label class="table-pager-size"><span>Filas</span><select aria-label="Filas por página"><option>10</option><option>15</option><option>25</option><option>50</option></select></label><div class="table-pager-nav"><button type="button" class="btn btn-secondary btn-icon" data-pg="prev" aria-label="Página anterior">‹</button><span class="table-pager-page small-text"></span><button type="button" class="btn btn-secondary btn-icon" data-pg="next" aria-label="Página siguiente">›</button></div>`;
    wrap.parentNode.insertBefore(pager,wrap.nextSibling);
    const info=pager.querySelector(".table-pager-info"),pageLbl=pager.querySelector(".table-pager-page");
    const prev=pager.querySelector('[data-pg="prev"]'),next=pager.querySelector('[data-pg="next"]'),sizeSel=pager.querySelector("select");
    const apply=(resetPage=true)=>{
      if(resetPage)page=1;
      const q=search.value.trim().toLowerCase();
      const matches=[];
      table.querySelectorAll("tbody tr").forEach(tr=>{
        const text=tr.textContent.toLowerCase();
        const okText=!q||text.includes(q);
        const okSelect=selects.every(([i,sel])=>!sel.value||tr.children[i]?.textContent.trim()===sel.value);
        if(okText&&okSelect)matches.push(tr);else tr.hidden=true;
      });
      const total=matches.length,pages=Math.max(1,Math.ceil(total/pageSize));
      page=Math.min(page,pages);
      const from=(page-1)*pageSize,to=from+pageSize;
      matches.forEach((tr,i)=>{tr.hidden=!(i>=from&&i<to);});
      count.textContent=`${total} resultado${total===1?"":"s"}`;
      info.textContent=total?`Mostrando ${from+1}–${Math.min(to,total)} de ${total}`:"Sin resultados";
      pageLbl.textContent=`Página ${page} de ${pages}`;
      prev.disabled=page<=1;next.disabled=page>=pages;
      pager.hidden=total<=10&&pageSize===10;
    };
    search.addEventListener("input",()=>apply());
    selects.forEach(([,sel])=>sel.addEventListener("change",()=>apply()));
    prev.addEventListener("click",()=>{page--;apply(false)});
    next.addEventListener("click",()=>{page++;apply(false)});
    sizeSel.addEventListener("change",()=>{pageSize=Number(sizeSel.value);apply()});
    apply();
  });
}
/* Error visible dentro del formulario abierto (no solo como aviso flotante). */
export function errorEnFormulario(form,mensajes){
  let caja=form.querySelector(".form-error");
  if(!caja){caja=document.createElement("div");caja.className="form-error";caja.setAttribute("role","alert");
    let ref=form.querySelector("[type=submit]");while(ref&&ref.parentElement!==form)ref=ref.parentElement;form.insertBefore(caja,ref||null);}
  const lista=(Array.isArray(mensajes)?mensajes:[mensajes]).filter(Boolean);
  caja.hidden=!lista.length;
  caja.innerHTML=lista.length>1?`<ul>${lista.map(m=>`<li>${escapeHtml(m)}</li>`).join("")}</ul>`:escapeHtml(lista[0]||"");
  if(lista.length) caja.scrollIntoView({block:"nearest"});
}
