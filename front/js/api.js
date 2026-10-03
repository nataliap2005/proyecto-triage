const API_BASE = "/api";

export class ApiError extends Error {
  constructor(message, status = 0, payload = null) {
    super(message); this.name = "ApiError"; this.status = status; this.payload = payload;
  }
}

export function getToken(){ return localStorage.getItem("triaje_token"); }
export function setToken(token){ token ? localStorage.setItem("triaje_token", token) : localStorage.removeItem("triaje_token"); }

async function parseResponse(response){
  const type=response.headers.get("content-type")||"";
  if(response.status===204) return null;
  if(type.includes("application/json")) return await response.json();
  return await response.text();
}

export async function api(path,{method="GET",body=null,headers={},auth=true,raw=false}={}){
  const finalHeaders={...headers};
  const token=getToken();
  if(auth && token) finalHeaders.Authorization=`Bearer ${token}`;
  if(body!==null && !(body instanceof Blob) && !(body instanceof FormData) && !finalHeaders["Content-Type"]){
    finalHeaders["Content-Type"]="application/json";
  }
  const payload=(body!==null && finalHeaders["Content-Type"]==="application/json" && typeof body!=="string")?JSON.stringify(body):body;
  let response;
  try{ response=await fetch(`${API_BASE}${path}`,{method,headers:finalHeaders,body:payload}); }
  catch(error){ throw new ApiError("No fue posible conectar con la API",0,error); }
  if(raw){
    if(!response.ok) throw new ApiError(`Error HTTP ${response.status}`,response.status,null);
    return response;
  }
  const data=await parseResponse(response);
  if(!response.ok){
    const message=(data && typeof data==="object" && data.detail)?(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail)):`Error HTTP ${response.status}`;
    if(response.status===401) window.dispatchEvent(new CustomEvent("auth:expired",{detail:{message}}));
    throw new ApiError(message,response.status,data);
  }
  return data;
}

export const apiGet=(p,o={})=>api(p,{...o,method:"GET"});
export const apiPost=(p,b,o={})=>api(p,{...o,method:"POST",body:b});
export const apiPut=(p,b,o={})=>api(p,{...o,method:"PUT",body:b});
export const apiPatch=(p,b=null,o={})=>api(p,{...o,method:"PATCH",body:b});
export const apiDelete=(p,o={})=>api(p,{...o,method:"DELETE"});

export async function apiBlob(path){ const r=await api(path,{raw:true}); return await r.blob(); }
