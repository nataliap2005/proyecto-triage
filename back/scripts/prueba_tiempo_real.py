"""Prueba de R17 (canal), R18 (bandeja) y R19 (bloqueo -> Admin).
Uso:  python back/scripts/prueba_tiempo_real.py <usuario_admin> <usuario_de_prueba>
El usuario de prueba quedará bloqueado y el script lo desbloquea al final.
"""
import getpass
import json
import sys
import threading
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5500/api"   # a través de Nginx, como el navegador
ESPERA_MAX = 8                       # segundos (espera_segundos de R17)


def api(metodo, ruta, token=None, cuerpo=None):
    """Petición a la API. Devuelve (código HTTP, datos JSON). Igual que en los cuadernos."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    if datos is not None:
        peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(peticion, timeout=10) as r:
            return r.status, json.loads(r.read() or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, None


def entrar(usuario, clave):
    estado, datos = api("POST", "/auth/login", cuerpo={"username": usuario, "password": clave})
    assert estado == 200, f"No se pudo entrar como {usuario}: {estado} {datos}"
    return datos["access_token"]


def verificar(descripcion, condicion, detalle=""):
    print(("OK     " if condicion else "FALLA  ") + descripcion, detalle)
    return bool(condicion)


def escuchar(token, recibidos, conectado):
    """Abre el canal SSE como lo haría EventSource y guarda cada evento 'data:'."""
    url = f"{BASE}/eventos/stream?token={token}"
    with urllib.request.urlopen(url, timeout=30) as r:
        conectado.set()
        for linea in r:
            linea = linea.decode("utf-8").strip()
            if linea.startswith("data:"):
                recibidos.append((time.time(), json.loads(linea[5:])))


if __name__ == "__main__":
    admin_user, victima = sys.argv[1], sys.argv[2]
    token_admin = entrar(admin_user, getpass.getpass(f"Clave de {admin_user}: "))

    # --- R17: autenticado ---
    estado, _ = api("GET", "/eventos/stream")
    verificar("Canal sin token: 401/403", estado in (401, 403), estado)
    estado, _ = api("GET", "/eventos/stream?token=basura")
    verificar("Canal con token inválido: 401", estado == 401, estado)

    # --- El admin abre su canal en un hilo aparte ---
    recibidos, conectado = [], threading.Event()
    threading.Thread(target=escuchar, args=(token_admin, recibidos, conectado), daemon=True).start()
    verificar("El admin abre el canal", conectado.wait(5))

    # --- R02 + R19: tres intentos fallidos bloquean la cuenta ---
    for i in range(3):
        estado, datos = api("POST", "/auth/login", cuerpo={"username": victima, "password": "clave-incorrecta"})
    momento_bloqueo = time.time()
    verificar("Tercer intento fallido: cuenta bloqueada (403)", estado == 403, datos)

    # --- R17 + R19: el aviso llega en vivo, en menos de 8 s ---
    evento = None
    while time.time() - momento_bloqueo < ESPERA_MAX and evento is None:
        evento = next((e for t, e in recibidos if e.get("tipo") == "cuenta_bloqueada"
                       and e.get("usuario_bloqueado") == victima), None)
        time.sleep(0.2)
    verificar(f"El admin recibe 'cuenta_bloqueada' en menos de {ESPERA_MAX} s", evento is not None)
    if evento:
        segundos = next(t for t, e in recibidos if e is evento) - momento_bloqueo
        print(f"       llegó en {segundos:.2f} s")
        verificar("El evento trae tipo, mensaje y fecha",
                  all(k in evento for k in ("tipo", "mensaje", "fecha")), evento)

    # --- R18: la bandeja persiste y se marca como leída ---
    estado, bandeja = api("GET", "/notificaciones", token=token_admin)
    nota = next((n for n in bandeja or [] if n.get("usuario_bloqueado") == victima), None)
    verificar("La notificación quedó en la bandeja del admin", nota is not None)
    if nota:
        verificar("Nace como no leída", nota["leida"] is False)
        estado, leida = api("PATCH", f"/notificaciones/{nota['id']}/leer", token=token_admin)
        verificar("El dueño la marca como leída", estado == 200 and leida["leida"] is True)

    # --- Limpieza: desbloquear al usuario de prueba ---
    if evento:
        estado, _ = api("PATCH", f"/usuarios/{evento['documento_usuario']}/desbloquear", token=token_admin)
        verificar("El admin desbloquea al usuario de prueba", estado == 200, estado)