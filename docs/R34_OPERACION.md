# R34 · Guía operativa de despliegue, sustentación y revisión

**Responsables:** equipo completo. Esta guía prioriza el requisito de **disponibilidad durante toda la jornada** y la revisión del repositorio, no solo la demostración puntual.

## 1. Artefactos obligatorios del repositorio

```text
proyecto_triaje/
├── README.md
├── docker-compose.yml
├── tester.yaml          # en la raíz, URL pública vigente
├── back/                # FastAPI, migraciones, tests
├── front/               # Nginx, HTML/CSS/JS
├── ml/                  # servicio ML
├── rag/                 # corpus y evaluación (sin PHI real)
└── docs/
    ├── STRIDE.md
    ├── EVENTOS.md
    ├── DATASETS.md      # ## Corpus
    ├── LEYES.md
    ├── R30_FHIR.md
    ├── R34_NATALIA.md
    ├── R34_PENDIENTES_EQUIPO.md
    └── R34_OPERACION.md
```

Repositorio: `https://github.com/nataliap2005/proyecto-triage`. **Pendiente:** confirmar que el docente tiene acceso de lectura. Los PR del equipo están fusionados en `main` sin conflictos.

## 2. Arranque reproducible (PowerShell, raíz del repositorio)

```powershell
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 api
docker compose logs --tail=60 cloudflared
```

El entorno utiliza nueve servicios de Docker Compose: `api`, `frontend`, `ml`, `mongodb`, `orthanc`, `hapi-fhir`, `hapi-postgres`, `cloudflared` y `postgres`. La base clínica suele apuntar a Neon; verificar conectividad y cadena de conexión protegida. No se requieren brokers Kafka/RabbitMQ.

**Variables internas:** completar desde ejemplos en `.env`/`back/pass.env` **sin subir los secretos**. `R30_IDENTIFICADOR_SECRETO`, `R30_SOCIO_URL`, `R30_SOCIO_TOKEN`, `R30_RECEPTOR_TOKEN`, `GROQ_API_KEY`, secretos JWT/HMAC, URLs DB. Una prueba local R30 usa `http://api:8000/fhir/remisiones-r30/recibir`; el receptor socio real requiere HTTPS y credenciales institucionales.

## 3. Comprobaciones de salud antes de clase

- [ ] `docker compose ps`: todos los servicios requeridos `Up`, bases/ML con healthcheck `healthy` donde corresponda.
- [ ] Abrir `http://localhost:5500` y comprobar inicio de sesión de prueba.
- [ ] Abrir `http://localhost:8000/docs` y verificar API.
- [ ] Abrir `http://localhost:8080/fhir/metadata` y revisar FHIR si se requiere.
- [ ] Probar la **URL pública desde una red distinta** (datos móviles) y su ruta `/api/`.
- [ ] Leer el log de `cloudflared` para obtener la URL `trycloudflare.com` actual; mantener el túnel y ordenador encendidos.
- [ ] Actualizar `tester.yaml.url_publica` antes de la entrega, con la URL vigente y sin barra final.
- [ ] Comprobar `/api/auth/login`, `/api/auth/me`, recuperación RAG, herramienta de agente y consentimiento sintético.
- [ ] Confirmar remisión 14 como `FHIR enviado` **sin reenviarla**; vista previa 11 recursos.
- [ ] Confirmar tablero/bandeja y suscripción SSE con sesión autenticada.
- [ ] Confirmar la prueba real con Annie solo cuando su receptor y credenciales estén disponibles.

**Nota de riesgo:** Quick Tunnel cambia de URL al reiniciarse; una URL antigua en `tester.yaml` rompe la verificación. No cerrar Docker Desktop, no permitir suspensión de Windows, mantener energía y conectividad. El hosting en un solo equipo sin HA implica riesgo de caída; prever persona de monitoreo y conectividad de respaldo.

## 4. Verificaciones Git y secretos

```powershell
git status --short
git ls-files | Select-String -Pattern '(^|/)(pass\.env|\.env)$'
python -m pytest back/tests/test_remisiones_fhir_r30.py -q  # ejecutar desde entorno con PYTHONPATH correcto
```

El comando de secretos no debería mostrar archivos sensibles. **ALERTA:** el `tester.yaml` revisado contiene contraseñas de cuentas demo en texto claro y `url_publica` vacía. Antes de publicar, revisar y rotar cualquier credencial que haya salido de un entorno sintético controlado. Coordinar con el docente el formato requerido para usuarios de evaluación; nunca publicar credenciales administrativas de uso real.

**Regresión completa:** `python -m pytest tests -q` desde `back/` → **213 passed** (2026-11-20, `main` en `f03550f`; incluye R23–R32). Antes se habían reportado 66 para R23–R30.

## 5. Evidencias sugeridas para la carpeta de entrega

- Captura R23 con fuentes y otra de abstención.
- R24: tres herramientas, auditoría `INVOCAR_HERRAMIENTA` con payload depurado.
- R25: rechazo, intento registrado (IP observada interna) y ciclo de bloqueo/desbloqueo.
- R26: captura del DFD STRIDE y matriz con controles de Sarah/Annie.
- R30: consentimiento vigente, vista previa 11 recursos, HTTP 422 OperationOutcome, HTTP 200 transaction-response y botón “FHIR enviado”.
- R29–R30 (entrada): `docs/evidencias/R29_R30/prueba_recepcion.txt` (12 de 12). R33: registro de la prueba con dos equipos externos (2026-11-21) en `docs/evidencias/R33/`.

Evitar capturas con nombres de pacientes reales, documentos reales, contraseñas, JWT, tokens o cadenas de conexión.

## 6. Sustentación cruzada: preguntas y retos de código

1. **¿R23 es igual a R24?** No: R23 recupera documentos y cita fuentes; R24 clasifica intención y llama una herramienta cerrada autorizada por FastAPI.
2. **¿Por qué el LLM no decide permisos?** Porque el prompt es manipulable. JWT/RBAC, titularidad, consentimiento y filtros se verifican en backend/SQL.
3. **¿Qué prueba R25?** Rechazo y bloqueo de intentos explícitos; el filtro no es universal. Las amenazas residuales aparecen en STRIDE.
4. **Defiende una fila STRIDE:** por ejemplo divulgación de información: activo historia clínica, amenaza exfiltración, control minimización/HMAC + permisos, evidencia canario, riesgo residual metadatos/citas no verificadas, norma Ley 1581 y Res. 1995.
5. **¿Por qué transaction y no batch?** Porque la intención es aplicar la operación como una unidad en el servidor receptor. La atomicidad bajo fallos internos aún requiere prueba específica.
6. **¿Qué significa Task requested?** Remisión pendiente de gestión, no aceptada. HTTP 200 `transaction-response` confirma persistencia técnica, no valoración clínica.
7. **Reto vivo:** buscar un middleware, explicar el control de roles del endpoint, localizar la comprobación del Consent o identificar dónde se rechaza un recurso FHIR inválido.

## 7. Responsables y campos que faltan

| Dependencia | Persona | Evidencia / enlace pendiente |
|---|---|---|
| Cifrado AES-GCM, auditoría encadenada, identidad institucional | Sarah | Hecho: `docs/evidencias/R27/`, `docs/evidencias/R28_R31/` |
| Receptor institucional, webhook seguro, retorno Task aceptación/rechazo | Annie | Hecho: `docs/CONTRATO_R30.md`, `docs/evidencias/R29_R30/` |
| URL pública sostenida durante toda la jornada | Equipo | **Pendiente:** URL vigente en `tester.yaml` y responsable de monitoreo |
| Repositorio público / permiso docente + PR + tester.yaml | Equipo / Natalia | Repositorio `https://github.com/nataliap2005/proyecto-triage`, PR fusionados. **Pendiente:** acceso docente y `url_publica` |
| Demo cruzada y firma de entrega | Equipo | Probado con dos equipos el 2026-11-21 (`docs/evidencias/R33/`); falta la demostración en la sustentación |
