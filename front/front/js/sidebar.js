// sidebar.js — contraer/expandir el menú lateral (solo presentación, todos los roles).
// No toca la navegación ni la sesión: únicamente alterna la clase "sidebar-collapsed".
const KEY="triaje_sidebar_colapsado";
const shell=document.getElementById("vista-app");
const btn=document.getElementById("sidebar-collapse");
const nav=document.getElementById("nav-principal");

const leer=()=>{try{return localStorage.getItem(KEY)==="1"}catch{return false}};
const guardar=v=>{try{localStorage.setItem(KEY,v?"1":"0")}catch{}};

function aplicar(colapsado){
  shell.classList.toggle("sidebar-collapsed",colapsado);
  const texto=colapsado?"Expandir menú":"Contraer menú";
  btn.setAttribute("aria-expanded",String(!colapsado));
  btn.setAttribute("aria-label",texto);
  btn.title=texto;
}

// Con el menú contraído solo se ven los iconos: cada botón recibe su nombre como tooltip.
function rotular(){
  nav.querySelectorAll(".nav-button").forEach(b=>{
    const nombre=[...b.childNodes].filter(n=>n.nodeType===3).map(n=>n.textContent).join("").trim();
    if(nombre&&b.title!==nombre){b.title=nombre;b.setAttribute("aria-label",nombre);}
  });
}

if(shell&&btn&&nav){
  aplicar(leer());
  btn.addEventListener("click",()=>{const v=!shell.classList.contains("sidebar-collapsed");aplicar(v);guardar(v);});
  new MutationObserver(rotular).observe(nav,{childList:true});
  rotular();
}
