// pendientes.js — contadores de trabajo pendiente (R18).
// Cualquier elemento con data-contador="clave" se actualiza solo con el valor de /pendientes.
// Si vale 0 se oculta, salvo que tenga el atributo data-mostrar-cero.
import {apiGet} from "./api.js";

let ultimo={};

export async function refrescarPendientes(){
  try{ ultimo=await apiGet("/pendientes"); }
  catch{ return ultimo; }
  pintarContadores();
  return ultimo;
}

export function pintarContadores(raiz=document){
  raiz.querySelectorAll("[data-contador]").forEach(el=>{
    const n=Number(ultimo[el.dataset.contador]??0);
    el.textContent=n>99?"99+":String(n);
    if(!("mostrarCero" in el.dataset)) el.hidden=n===0;
  });
}