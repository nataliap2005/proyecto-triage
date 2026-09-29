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

No crea, edita ni elimina información clínica en la BD principal.
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


def request(method: str, path: str, *, expected=(200,), **kwargs):
    global ok, fail

    url = f"{API_URL}{path}"

    try:
        r = session.request(
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

request(
    "GET",
    "/estado-bd"
)


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
# 6. FHIR
# ============================================================

print("\n=== 6. FHIR ===")


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
# 7. PACS
# ============================================================

print("\n=== 7. PACS ===")


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
# 8. RESUMEN
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