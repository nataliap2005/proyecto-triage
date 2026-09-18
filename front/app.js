const API_CLOUDFLARE="https://announces-scientist-dos-darwin.trycloudflare.com";
const API_LOCAL="http://127.0.0.1:8000";

let API_URL=API_LOCAL;

async function seleccionarApi(){
  try{
    const respuesta=await fetch(`${API_CLOUDFLARE}/estado-bd`,{
      method:"GET"
    });

    if(respuesta.ok){
      API_URL=API_CLOUDFLARE;
      console.log("Usando API pública:",API_URL);
      return;
    }

    throw new Error("Cloudflare no disponible");

  }catch(error){
    API_URL=API_LOCAL;
    console.log("Usando API local:",API_URL);
  }
}

const vistaLogin=document.getElementById("vista-login");
const vistaPanel=document.getElementById("vista-panel");
const loginForm=document.getElementById("login-form");
const loginMensaje=document.getElementById("login-mensaje");
const usuarioActual=document.getElementById("usuario-actual");
const rolActual=document.getElementById("rol-actual");
const contenidoRol=document.getElementById("contenido-rol");
const cerrarSesion=document.getElementById("cerrar-sesion");

function mostrarLogin(){
  vistaLogin.hidden=false;
  vistaPanel.hidden=true;
  usuarioActual.textContent="";
  rolActual.textContent="";
  contenidoRol.innerHTML="";
}

function mostrarPanel(usuario){
  vistaLogin.hidden=true;
  vistaPanel.hidden=false;

  usuarioActual.textContent=usuario.username;
  rolActual.textContent=usuario.rol;

  mostrarContenidoPorRol(usuario.rol);
}

function mostrarContenidoPorRol(rol){
  const mensajes={
    Admin:"Panel de administración.",
    Medico:"Panel médico.",
    Administrativo:"Panel de facturación.",
    Paciente:"Panel del paciente.",
    Paciente_Cuidador:"Panel del paciente/cuidador."
  };

  contenidoRol.innerHTML=`<p>${mensajes[rol] || "Panel de usuario."}</p>`;
}

async function obtenerPerfil(token){
  const respuesta=await fetch(`${API_URL}/auth/me`,{
    headers:{
      "Authorization":`Bearer ${token}`
    }
  });

  if(!respuesta.ok){
    throw new Error("No fue posible validar la sesión");
  }

  return await respuesta.json();
}

loginForm.addEventListener("submit",async(event)=>{
  event.preventDefault();

  const username=document.getElementById("username").value.trim();
  const password=document.getElementById("password").value;

  loginMensaje.textContent="Ingresando...";

  try{
    const respuesta=await fetch(`${API_URL}/auth/login`,{
      method:"POST",
      headers:{
        "Content-Type":"application/json"
      },
      body:JSON.stringify({
        username,
        password
      })
    });

    const data=await respuesta.json();

    if(!respuesta.ok){
      throw new Error(data.detail || "Credenciales incorrectas");
    }

    localStorage.setItem("token",data.access_token);

    const usuario=await obtenerPerfil(data.access_token);

    loginMensaje.textContent="";
    mostrarPanel(usuario);

  }catch(error){
    localStorage.removeItem("token");
    loginMensaje.textContent=error.message;
  }
});

cerrarSesion.addEventListener("click",()=>{
  localStorage.removeItem("token");
  loginForm.reset();
  loginMensaje.textContent="";
  mostrarLogin();
});

async function restaurarSesion(){
  const token=localStorage.getItem("token");

  if(!token){
    mostrarLogin();
    return;
  }

  try{
    const usuario=await obtenerPerfil(token);
    mostrarPanel(usuario);
  }catch{
    localStorage.removeItem("token");
    mostrarLogin();
  }
}

async function iniciarAplicacion(){
  await seleccionarApi();
  await restaurarSesion();
}

iniciarAplicacion();