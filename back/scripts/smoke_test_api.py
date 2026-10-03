"""
Smoke test rápido para la API de Triaje Hospitalario.

Qué comprueba:
- La API responde.
- La BD responde.
- Login JWT y /auth/me.
- Los routers esperados aparecen en OpenAPI.
- GET principales de cada módulo.
- GET con IDs reales tomados automáticamente de la propia API.
- HAPI FHIR responde mediante /fhir/estado.
- Sincronización de un paciente existente hacia HAPI FHIR.
- Consulta del Patient sincronizado desde HAPI FHIR.
- PACS/Orthanc responde mediante /pacs/estado.
- Consulta de imágenes PACS asociadas a un paciente real.
- Soft delete de una observación creada por un médico.
- Verificación de que el médico no puede restaurarla.
- Restauración por Admin y comprobación de la auditoría.

La prueba de soft delete reutiliza una observación existente y la restaura al final.
No altera sus valores clínicos. La auditoría sí conserva la evidencia de la prueba.
La prueba FHIR puede crear o actualizar un recurso Patient dentro de HAPI FHIR.
"""

import getpass
import sys
from typing import Any

import requests


API_URL = input("URL de la API [http://localhost:8000]: ").strip() or "http://localhost:8000"
API_URL = API_URL.rstrip("/")

username = input("Usuario Admin: ").strip()
password = getpass.getpass("Contraseña: ")

session = requests.Session()
session.headers.update({"Accept": "application/json"})

ok = 0
fail = 0
warn = 0


def mostrar(nombre: str, estado: str, detalle: str = ""):
    icono = {
        "OK": "✅",
        "FAIL": "❌",
        "WARN": "⚠️"
    }[estado]

    print(
        f"{icono} {nombre}: {estado}"
        + (f" — {detalle}" if detalle else "")
    )


def request(method: str, path: str, *, expected=(200,), client=None, **kwargs):
    global ok, fail

    url = f"{API_URL}{path}"
    client = client or session

    try:
        r = client.request(
            method,
            url,
            timeout=25,
            **kwargs
        )

    except requests.RequestException as e:
        fail += 1
        mostrar(
            f"{method} {path}",
            "FAIL",
            str(e)
        )
        return None

    if r.status_code in expected:
        ok += 1
        mostrar(
            f"{method} {path}",
            "OK",
            f"HTTP {r.status_code}"
        )
        return r

    fail += 1

    detalle = r.text[:250].replace("\n", " ")

    mostrar(
        f"{method} {path}",
        "FAIL",
        f"HTTP {r.status_code}: {detalle}"
    )

    return r


# ============================================================
# 1. SISTEMA
# ============================================================

print("\n=== 1. SISTEMA ===")

request(
    "GET",
    "/"
)

# /estado-bd está protegido y se prueba después del login.


# ============================================================
# 2. AUTENTICACIÓN
# ============================================================

print("\n=== 2. AUTENTICACIÓN ===")

r = request(
    "POST",
    "/auth/login",
    json={
        "username": username,
        "password": password
    },
)

if r is None or r.status_code != 200:
    print("\nNo se puede continuar sin token.")
    sys.exit(1)

data = r.json()

token = data.get("access_token")

if not token:
    print(
        "❌ El login respondió 200 "
        "pero no devolvió access_token."
    )
    sys.exit(1)

session.headers.update({
    "Authorization": f"Bearer {token}"
})

request(
    "GET",
    "/auth/me"
)

request(
    "GET",
    "/estado-bd"
)

request(
    "GET",
    "/auth/logs"
)


# ============================================================
# 3. ROUTERS REGISTRADOS
# ============================================================

print("\n=== 3. ROUTERS REGISTRADOS ===")

openapi = request(
    "GET",
    "/openapi.json"
)

expected_paths = [
    "/usuarios",
    "/pacientes",
    "/antecedentes",
    "/reportes-previos",
    "/encuentros",
    "/observaciones",
    "/diagnosticos",
    "/notas-clinicas",
    "/examenes",
    "/medicamentos",
    "/prescripciones",
    "/facturas",
    "/auditoria",
    "/fhir/estado",
    "/pacs/estado",
]

if openapi is not None and openapi.status_code == 200:

    paths = openapi.json().get("paths", {})

    for prefijo in expected_paths:

        existe = any(
            p == prefijo or p.startswith(prefijo + "/")
            for p in paths
        )

        if existe:
            ok += 1

            mostrar(
                f"Router {prefijo}",
                "OK"
            )

        else:
            fail += 1

            mostrar(
                f"Router {prefijo}",
                "FAIL",
                "No aparece en OpenAPI"
            )


# ============================================================
# 4. GET PRINCIPALES
# ============================================================

print("\n=== 4. GET PRINCIPALES ===")

responses: dict[str, Any] = {}

for nombre, path in [

    ("usuarios", "/usuarios"),
    ("pacientes", "/pacientes"),
    ("encuentros", "/encuentros"),
    ("medicamentos", "/medicamentos"),
    ("prescripciones", "/prescripciones"),
    ("facturas", "/facturas"),
    ("auditoria", "/auditoria"),

]:

    r = request(
        "GET",
        path
    )

    if r is not None and r.status_code == 200:

        try:
            responses[nombre] = r.json()

        except ValueError:
            responses[nombre] = None


# ============================================================
# 5. GET CON DATOS REALES
# ============================================================

print("\n=== 5. GET CON DATOS REALES ===")


# ------------------------------------------------------------
# USUARIOS
# ------------------------------------------------------------

usuarios = responses.get("usuarios") or []

if usuarios:

    doc_usuario = usuarios[0]["numero_documento_usuario"]

    request(
        "GET",
        f"/usuarios/{doc_usuario}"
    )

else:

    warn += 1

    mostrar(
        "GET usuario individual",
        "WARN",
        "No hay usuarios devueltos"
    )


# ------------------------------------------------------------
# PACIENTES
# ------------------------------------------------------------

pacientes = responses.get("pacientes") or []

if pacientes:

    doc_paciente = pacientes[0][
        "numero_documento_paciente"
    ]

    request(
        "GET",
        f"/pacientes/{doc_paciente}"
    )

    request(
        "GET",
        f"/pacientes/{doc_paciente}/antecedentes"
    )

    request(
        "GET",
        f"/pacientes/{doc_paciente}/historia-clinica"
    )

else:

    warn += 1

    mostrar(
        "GET paciente individual",
        "WARN",
        "No hay pacientes devueltos"
    )


# ------------------------------------------------------------
# ENCUENTROS
# ------------------------------------------------------------

encuentros = responses.get("encuentros") or []

if encuentros:

    id_encuentro = encuentros[0]["id_encuentro"]

    request(
        "GET",
        f"/encuentros/{id_encuentro}"
    )

    request(
        "GET",
        f"/encuentros/{id_encuentro}/observaciones"
    )

    request(
        "GET",
        f"/encuentros/{id_encuentro}/diagnosticos"
    )

    request(
        "GET",
        f"/encuentros/{id_encuentro}/notas-clinicas"
    )

    request(
        "GET",
        f"/encuentros/{id_encuentro}/examenes"
    )

    request(
        "GET",
        f"/encuentros/{id_encuentro}/prescripciones"
    )

else:

    warn += 1

    mostrar(
        "GET encuentro individual",
        "WARN",
        "No hay encuentros devueltos"
    )


# ------------------------------------------------------------
# FACTURAS
# ------------------------------------------------------------

facturas = responses.get("facturas") or []

if facturas:

    id_factura = facturas[0]["id_factura"]

    request(
        "GET",
        f"/facturas/{id_factura}"
    )

else:

    warn += 1

    mostrar(
        "GET factura individual",
        "WARN",
        "No hay facturas devueltas"
    )


# ============================================================
# 6. SOFT DELETE / RESTAURACIÓN
# ============================================================

print("\n=== 6. SOFT DELETE / RESTAURACIÓN ===")

# Busca automáticamente una observación activa creada por un usuario Medico.
medicos = {
    int(u["numero_documento_usuario"]): u
    for u in usuarios
    if u.get("rol") == "Medico" and not u.get("is_deleted", False)
}

prueba_soft = None

for encuentro in encuentros:
    if prueba_soft:
        break

    ide = encuentro.get("id_encuentro")
    if not ide:
        continue

    try:
        r_obs = session.get(
            f"{API_URL}/encuentros/{ide}/observaciones",
            timeout=25
        )
    except requests.RequestException:
        continue

    if r_obs.status_code != 200:
        continue

    try:
        observaciones = r_obs.json()
    except ValueError:
        continue

    for obs in observaciones:
        autor = obs.get("registrado_por")
        if autor is None:
            continue

        try:
            autor = int(autor)
        except (TypeError, ValueError):
            continue

        if autor in medicos:
            prueba_soft = {
                "id_encuentro": ide,
                "id_observacion": obs.get("id_observacion"),
                "medico": medicos[autor],
            }
            break

if not prueba_soft:
    warn += 1
    mostrar(
        "Soft delete/restauración",
        "WARN",
        "No se encontró una observación activa creada por un Medico"
    )
else:
    id_obs = prueba_soft["id_observacion"]
    id_enc = prueba_soft["id_encuentro"]
    medico = prueba_soft["medico"]
    medico_username = medico["username"]

    print(
        f"Registro seleccionado automáticamente: observación {id_obs} "
        f"del médico {medico_username}"
    )

    medico_password = getpass.getpass(
        f"Contraseña del Medico {medico_username} "
        "(Enter para omitir esta prueba): "
    )

    if not medico_password:
        warn += 1
        mostrar(
            "Soft delete/restauración",
            "WARN",
            "Prueba omitida porque no se ingresó la contraseña del Medico"
        )
    else:
        medico_session = requests.Session()
        medico_session.headers.update({"Accept": "application/json"})

        r_login_medico = request(
            "POST",
            "/auth/login",
            client=medico_session,
            json={
                "username": medico_username,
                "password": medico_password
            }
        )

        if r_login_medico is not None and r_login_medico.status_code == 200:
            token_medico = r_login_medico.json().get("access_token")

            if not token_medico:
                fail += 1
                mostrar(
                    "Token del Medico",
                    "FAIL",
                    "El login no devolvió access_token"
                )
            else:
                medico_session.headers.update({
                    "Authorization": f"Bearer {token_medico}"
                })

                eliminado = False

                try:
                    r_delete = request(
                        "DELETE",
                        f"/observaciones/{id_obs}",
                        client=medico_session
                    )
                    eliminado = (
                        r_delete is not None
                        and r_delete.status_code == 200
                    )

                    if eliminado:
                        r_lista = request(
                            "GET",
                            f"/encuentros/{id_enc}/observaciones"
                        )

                        if r_lista is not None and r_lista.status_code == 200:
                            ids_visibles = {
                                x.get("id_observacion")
                                for x in r_lista.json()
                            }

                            if id_obs not in ids_visibles:
                                ok += 1
                                mostrar(
                                    "Registro oculto tras soft delete",
                                    "OK"
                                )
                            else:
                                fail += 1
                                mostrar(
                                    "Registro oculto tras soft delete",
                                    "FAIL",
                                    "La observación sigue apareciendo como activa"
                                )

                        request(
                            "PATCH",
                            f"/observaciones/{id_obs}/restaurar",
                            client=medico_session,
                            expected=(403,)
                        )

                        r_restore = request(
                            "PATCH",
                            f"/observaciones/{id_obs}/restaurar"
                        )

                        if r_restore is not None and r_restore.status_code == 200:
                            eliminado = False

                            r_lista = request(
                                "GET",
                                f"/encuentros/{id_enc}/observaciones"
                            )

                            if r_lista is not None and r_lista.status_code == 200:
                                ids_visibles = {
                                    x.get("id_observacion")
                                    for x in r_lista.json()
                                }

                                if id_obs in ids_visibles:
                                    ok += 1
                                    mostrar(
                                        "Registro visible tras restauración Admin",
                                        "OK"
                                    )
                                else:
                                    fail += 1
                                    mostrar(
                                        "Registro visible tras restauración Admin",
                                        "FAIL"
                                    )

                        r_audit = request(
                            "GET",
                            f"/auditoria/observaciones/{id_obs}"
                        )

                        if r_audit is not None and r_audit.status_code == 200:
                            acciones = {
                                x.get("accion")
                                for x in r_audit.json()
                            }

                            faltan = {"ELIMINAR", "RESTAURAR"} - acciones

                            if not faltan:
                                ok += 1
                                mostrar(
                                    "Auditoría soft delete/restauración",
                                    "OK"
                                )
                            else:
                                fail += 1
                                mostrar(
                                    "Auditoría soft delete/restauración",
                                    "FAIL",
                                    "Faltan acciones: " + ", ".join(sorted(faltan))
                                )

                finally:
                    # Salvaguarda: si algo falla después del DELETE, el Admin intenta restaurar.
                    if eliminado:
                        try:
                            r_seguro = session.patch(
                                f"{API_URL}/observaciones/{id_obs}/restaurar",
                                timeout=25
                            )
                            if r_seguro.status_code == 200:
                                mostrar(
                                    "Restauración de seguridad",
                                    "OK",
                                    f"Observación {id_obs} restaurada"
                                )
                            else:
                                mostrar(
                                    "Restauración de seguridad",
                                    "WARN",
                                    f"HTTP {r_seguro.status_code}: {r_seguro.text[:150]}"
                                )
                        except requests.RequestException as e:
                            mostrar(
                                "Restauración de seguridad",
                                "WARN",
                                str(e)
                            )


# ============================================================
# 7. FHIR
# ============================================================

print("\n=== 7. FHIR ===")


# ------------------------------------------------------------
# ESTADO HAPI FHIR
# ------------------------------------------------------------

request(
    "GET",
    "/fhir/estado"
)


# ------------------------------------------------------------
# SINCRONIZACIÓN REAL DE PATIENT
# ------------------------------------------------------------

FHIR_TEST_PATIENT = 1087048983

paciente_fhir_existe = any(
    str(
        p.get("numero_documento_paciente")
    ) == str(FHIR_TEST_PATIENT)
    for p in pacientes
)

if paciente_fhir_existe:

    r_fhir = request(
        "PUT",
        f"/fhir/pacientes/{FHIR_TEST_PATIENT}",
        expected=(200, 201)
    )

    if (
        r_fhir is not None
        and r_fhir.status_code in (200, 201)
    ):

        request(
            "GET",
            f"/fhir/pacientes/{FHIR_TEST_PATIENT}"
        )

else:

    warn += 1

    mostrar(
        "Sincronización Patient FHIR",
        "WARN",
        (
            f"El paciente {FHIR_TEST_PATIENT} "
            "no existe en la BD clínica"
        )
    )


# ============================================================
# 8. PACS
# ============================================================

print("\n=== 8. PACS ===")


# ------------------------------------------------------------
# ESTADO ORTHANC
# ------------------------------------------------------------

request(
    "GET",
    "/pacs/estado"
)


# ------------------------------------------------------------
# IMÁGENES PACS DE PACIENTE
# ------------------------------------------------------------

if pacientes:

    doc_paciente = pacientes[0][
        "numero_documento_paciente"
    ]

    request(
        "GET",
        f"/pacientes/{doc_paciente}/imagenes"
    )

else:

    warn += 1

    mostrar(
        "GET imágenes PACS del paciente",
        "WARN",
        "No hay pacientes para probar"
    )


# ============================================================
# 9. RESUMEN
# ============================================================

print("\n" + "=" * 55)

print("RESUMEN")

print("=" * 55)

print(f"✅ OK:   {ok}")
print(f"⚠️ WARN: {warn}")
print(f"❌ FAIL: {fail}")


if fail == 0:

    print(
        "\n🎉 RESULTADO: "
        "TODO EL SMOKE TEST PASÓ CORRECTAMENTE."
    )

    print(
        "La API, la modularización, "
        "FHIR y PACS están respondiendo."
    )

    sys.exit(0)

else:

    print(
        "\n❌ RESULTADO: "
        "HAY PRUEBAS FALLIDAS."
    )

    print(
        "Revisa las líneas marcadas "
        "con FAIL antes de continuar."
    )

    sys.exit(1)