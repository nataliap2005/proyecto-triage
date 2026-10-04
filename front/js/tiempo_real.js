// tiempo_real.js — canal en vivo con el servidor (R17) mediante Server-Sent Events.
// Cada evento que llega se reenvía como CustomEvent "tr:evento" para que cada
// pantalla reaccione por su cuenta, igual que "auth:expired" en api.js.
import {apiGet,getToken} from "./api.js";

let fuente=null;
let reintento=null;
let activo=false;

function marcarEstado(conectado){
  const punto=document.getElementById("estado-canal");
  if(!punto) return;
  punto.classList.toggle("on",conectado);
  punto.title=conectado?"Tiempo real: conectado":"Tiempo real: reconectando…";
}

export function conectarCanal(){
  cerrarFuente();
  const token=getToken();
  if(!token) return;
  activo=true;

  // EventSource no permite enviar cabeceras: el token viaja como parámetro (R17 lo admite).
  fuente=new EventSource(`/api/eventos/stream?token=${encodeURIComponent(token)}`);

  fuente.onopen=()=>{
    marcarEstado(true);
    // Al (re)conectar se refrescan bandeja y contadores: lo que llegó mientras
    // el canal estuvo caído ya está guardado en la bandeja del servidor.
    window.dispatchEvent(new CustomEvent("tr:conectado"));
  };

  fuente.onmessage=e=>{
    let evento;
    try{ evento=JSON.parse(e.data); }catch{ return; }
    window.dispatchEvent(new CustomEvent("tr:evento",{detail:evento}));
  };

  fuente.onerror=()=>{
    marcarEstado(false);
    // Si el servidor rechazó la conexión (p. ej. token vencido), EventSource se rinde
    // y queda CLOSED. Si fue un corte de red, reintenta solo y no hay que hacer nada.
    if(fuente && fuente.readyState===EventSource.CLOSED) programarReconexion();
  };
}

function programarReconexion(){
  if(!activo || reintento) return;
  reintento=setTimeout(async()=>{
    reintento=null;
    if(!activo) return;
    try{
      await apiGet("/auth/me");   // ¿la sesión sigue viva?
      conectarCanal();
    }catch(e){
      // 401: api.js ya disparó "auth:expired" y app.js cierra la sesión.
      // Otro error (API caída): se vuelve a intentar más tarde.
      if(e.status!==401) programarReconexion();
    }
  },5000);
}

function cerrarFuente(){
  clearTimeout(reintento);
  reintento=null;
  if(fuente){ fuente.close(); fuente=null; }
  marcarEstado(false);
}

export function desconectarCanal(){
  activo=false;
  cerrarFuente();
}