"""Utilidades compartidas por los scripts de prueba (mismo estilo de los cuadernos de clase)."""
import json
import threading
import time
import urllib.error
import urllib.request

BASE = "http://localhost:5500/api"   # a través de Nginx, como el navegador
ESPERA_MAX = 8                       # espera_segundos de R17


def api(metodo, ruta, token=None, cuerpo=None):
    """Petición a la API. Devuelve (código HTTP, datos JSON)."""
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    peticion = urllib.request.Request(BASE + ruta, data=datos, method=metodo)
    if datos is not None:
        peticion.add_header("Content-Type", "application/json")
    if token:
        peticion.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(peticion, timeout=15) as r:
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


class Canal:
    """Abre el canal SSE de un usuario en un hilo aparte, como lo haría EventSource."""

    def __init__(self, token, nombre):
        self.nombre = nombre
        self.eventos = []                    # lista de (momento, evento)
        self.conectado = threading.Event()
        threading.Thread(target=self._escuchar, args=(token,), daemon=True).start()
        if not self.conectado.wait(5):
            raise RuntimeError(f"No se pudo abrir el canal de {nombre}")

    def _escuchar(self, token):
        with urllib.request.urlopen(f"{BASE}/eventos/stream?token={token}", timeout=30) as r:
            self.conectado.set()
            for linea in r:
                linea = linea.decode("utf-8").strip()
                if linea.startswith("data:"):
                    self.eventos.append((time.time(), json.loads(linea[5:])))

    def esperar(self, condicion, segundos=ESPERA_MAX):
        """Devuelve (evento, momento) del primer evento que cumpla la condición, o (None, None)."""
        limite = time.time() + segundos
        while time.time() < limite:
            for momento, evento in self.eventos:
                if condicion(evento):
                    return evento, momento
            time.sleep(0.1)
        return None, None

    def recibio(self, condicion):
        return any(condicion(e) for _, e in self.eventos)