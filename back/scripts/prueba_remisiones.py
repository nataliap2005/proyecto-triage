"""Prueba de R19 (remisión -> especialista, aceptación -> médico), R17 (aislamiento) y R18 (pendientes).
Uso:
  python back/scripts/prueba_remisiones.py <medico> <especialista> <paciente> <contable> <id_paciente> <id_encuentro> <id_especialidad>
El <paciente> idealmente es la cuenta del mismo paciente que se remite.
"""
import getpass
import sys
import time

from utilidades_prueba import ESPERA_MAX, Canal, api, entrar, verificar

medico, especialista, paciente, contable = sys.argv[1:5]
id_paciente, id_encuentro, id_especialidad = map(int, sys.argv[5:8])

tokens = {u: entrar(u, getpass.getpass(f"Clave de {u}: ")) for u in (medico, especialista, paciente, contable)}
canales = {u: Canal(t, u) for u, t in tokens.items()}
verificar("Los cuatro usuarios abren su canal", True)

# Documento del especialista (para la remisión)
_, yo_esp = api("GET", "/auth/me", tokens[especialista])
doc_especialista = yo_esp["numero_documento_usuario"]

# --- R18: contador antes ---
_, antes = api("GET", "/pendientes", tokens[especialista])
print(f"       remisiones_recibidas antes: {antes['remisiones_recibidas']}")

# --- R19 flujo 1: el médico remite ---
inicio = time.time()
estado, creada = api("POST", "/remisiones", tokens[medico], {
    "id_paciente": id_paciente,
    "id_encuentro": id_encuentro,
    "especialista_destino": doc_especialista,
    "id_especialidad": id_especialidad,
    "motivo": "Prueba automática de flujos en tiempo real",
})
if not verificar("El médico crea la remisión (201)", estado == 201, creada if estado != 201 else ""):
    sys.exit("No se pudo crear la remisión: revisa los datos de entrada.")
id_remision = creada["id"]

de_esta = lambda tipo: (lambda e: e.get("tipo") == tipo and e.get("remision_id") == id_remision)

evento, momento = canales[especialista].esperar(de_esta("remision_recibida"))
verificar(f"El especialista recibe 'remision_recibida' en menos de {ESPERA_MAX} s", evento is not None)
if evento:
    print(f"       llegó en {momento - inicio:.2f} s")
    verificar("El evento trae paciente_id", evento.get("paciente_id") == id_paciente)

time.sleep(2)   # margen para que, si algo se filtrara, alcance a llegar
cualquier_aviso = lambda e: e.get("remision_id") == id_remision
verificar("El paciente NO recibe nada por su canal", not canales[paciente].recibio(cualquier_aviso))
verificar("El contable NO recibe nada por su canal", not canales[contable].recibio(cualquier_aviso))

_, bandeja_pac = api("GET", "/notificaciones", tokens[paciente])
verificar("Tampoco queda nada en la bandeja del paciente", not any(cualquier_aviso(n) for n in bandeja_pac))

# --- R18: el contador sube ---
_, durante = api("GET", "/pendientes", tokens[especialista])
verificar("remisiones_recibidas sube en 1",
          durante["remisiones_recibidas"] == antes["remisiones_recibidas"] + 1, durante)

# --- R19 flujo 2: el especialista acepta ---
inicio = time.time()
estado, _ = api("PATCH", f"/remisiones/{id_remision}/aceptar", tokens[especialista],
                {"observacion": "Aceptada en prueba automática"})
verificar("El especialista acepta la remisión (200)", estado == 200, estado)

evento, momento = canales[medico].esperar(de_esta("remision_aceptada"))
verificar(f"El médico recibe 'remision_aceptada' en menos de {ESPERA_MAX} s", evento is not None)
if evento:
    print(f"       llegó en {momento - inicio:.2f} s")

# --- R18: el contador baja ---
_, despues = api("GET", "/pendientes", tokens[especialista])
verificar("remisiones_recibidas vuelve a su valor inicial",
          despues["remisiones_recibidas"] == antes["remisiones_recibidas"], despues)

# --- R18: pendientes responde a los cinco roles (aquí, cuatro) ---
for u in (paciente, contable):
    estado, datos = api("GET", "/pendientes", tokens[u])
    verificar(f"/pendientes responde a {u} con contadores en 0",
              estado == 200 and datos["remisiones_recibidas"] == 0, datos)