import {apiGet,apiPost,getToken,setToken} from "./api.js";

let currentUser=null;
export const getCurrentUser=()=>currentUser;
export const isRole=(...roles)=>!!currentUser && roles.includes(currentUser.rol);

export async function login(username,password){
  const data=await apiPost("/auth/login",{username,password},{auth:false});
  setToken(data.access_token);
  currentUser=await apiGet("/auth/me");
  return currentUser;
}
export async function restoreSession(){
  if(!getToken()) return null;
  try{ currentUser=await apiGet("/auth/me"); return currentUser; }
  catch{ logout(); return null; }
}
export function logout(){ setToken(null); currentUser=null; }
export function initials(user=currentUser){
  if(!user) return "U"; const base=user.username||String(user.numero_documento_usuario||"U");
  return base.split(/[._-]/).filter(Boolean).slice(0,2).map(x=>x[0]?.toUpperCase()).join("")||"U";
}
