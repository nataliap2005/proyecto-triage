# R34 · Secciones pendientes de Sarah, Annie y coordinación

Este archivo **no presenta como implementadas** las partes que aún requieren evidencia. Sustituir cada `...` con información real y enlazar commit, ruta de código, prueba, captura o endpoint antes de enviar al docente.

## 1. Sarah — seguridad de datos y autenticación institucional

| Componente | Evidencia exigida | Estado |
|---|---|---|
| R27 cifrado AES-GCM de datos sensibles | Campos cubiertos, modo nonce, manejo de claves/rotación, prueba descifrado y acceso no autorizado | **Hecho para teléfono y dirección:** `back/core/cifrado.py` (AES-256-GCM, nonce aleatorio de 12 bytes, formato `v1.k1.<nonce>.<cifrado>` con identificador de llave para rotar), descifrado central en `back/core/database.py`, migración `017`, `back/scripts/cifrar_datos_existentes_r27.py`, 18 pruebas (valor alterado, otra llave y otro campo no descifran; sin llave responde 503). **Documento de identidad:** número interno HMAC en las tablas y documento cifrado en `identidades` (`back/core/identidad.py`, `back/core/identidad_middleware.py`, migración `019`, `back/scripts/migrar_documentos_r27.py`, 22 pruebas). **Aplicado en la base compartida el 2026-11-20** (258 documentos; teléfono y dirección: 43, 41 y 32 valores; 0 en claro). Evidencia en `docs/evidencias/R27/` |
| R28 auditoría con cadena de hashes | Estructura de hash, orden, prueba de manipulación y validador de integridad | **Hecho (2026-11-15):** hash SHA-256 sobre `auditoria_cambios` por trigger con bloqueo; migración `016`; `back/routers/auditoria_cadena.py`; `back/scripts/prueba_r28_manipulacion.py`; verificación Admin 200 (314 eslabones), sin token 401, médico 403; commit `5f1f14f`, PR #6 |
| R31 autenticación entre instituciones | Mecanismo elegido, identidad del socio, HTTPS, credenciales y rotación, prueba de rechazo | **Hecho para la entrada (2026-11-15):** OAuth2 `client_credentials` con JWT de 10 minutos; `back/auth/institucional.py`, `back/routers/oauth_institucional.py`, migración `015`, script de alta, rotación y baja; 31 pruebas; rechazos 401, 400, 403 y 409 y rotación comprobados; commits `c89ca86`, `4f4dc14`, `33f834f`, PR #6. **Pendiente:** credencial del socio real y HTTPS de extremo a extremo con el socio |
| STRIDE actualizado | Evidencias para Spoofing/Repudiation/Disclosure; riesgos residuales | **Hecho para R27, R28 y R31:** filas S2, T1, R1, I3 y E3 y tabla final de `docs/STRIDE.md` |
| LEYES actualizado | Alcance de controles R27, R28, R31 y normativa aplicable | **Hecho para R27, R28 y R31** en `docs/LEYES.md` |

## 2. Annie — seguridad externa e interoperabilidad de entrada

| Componente | Evidencia exigida | Estado |
|---|---|---|
| Receptor real del Bundle FHIR | URL HTTPS y contrato de `Bundle transaction`, validación de recursos y OperationOutcome | **Hecho (2026-11-18):** `POST /fhir/remisiones-r30/recibir` en `back/routers/recepcion_externa.py`; contrato para el socio en `docs/CONTRATO_R30.md`; HTTPS lo aporta el túnel. Validación completa con 422 `OperationOutcome` |
| Protección webhook/endpoints | Header/firma/token, validación origen, rechazo de request inválido o repetido | **Hecho:** entrada del socio con token institucional R31 (`bundle:write`/`task:write`) + `x-nonce` (409 si se repite); `fhir-hook` con token comparado en tiempo constante; Nginx solo publica de HAPI lo que exige R21. Pruebas: `test_recepcion_externa_r30.py`, `test_fhir_hook_r29.py`; `docs/evidencias/R29_R30/prueba_recepcion.txt` (12 de 12) |
| Integración HAPI socio | Pruebas de persistencia y rechazo sin escrituras parciales | **Hecho en autoprueba local:** Bundle válido 200 `transaction-response`; rechazos sin escrituras; ids del socio reescritos (`ext-...`) y compensación si HAPI falla a medias. **Pendiente:** con el socio real (R33) |
| Consentimiento y visualización receptor | Cómo se reconoce `Consent`, posibilidad de revocación y vista clínica | **Hecho:** Bundle sin `Consent` activo o vencido → 422; consentimiento por institución destino con vencimiento y revocación (R32); el especialista ve la remisión externa en su bandeja (`GET /remisiones-externas`) |
| Retorno estado Task | Estados aceptado/rechazado/finalizado, payload y transición permitida | **Hecho:** aceptar/rechazar (`PATCH /remisiones-externas/{id}/aceptar` o `/rechazar`) envía un `Task` `accepted`/`rejected` al socio; la respuesta del socio llega por `POST /fhir/remisiones-r30/respuesta` (no se puede cambiar de decisión: 409). Pruebas: `test_devolucion_r30.py` |
| Notificaciones socio ↔ remitente | Evento recibido, destinatario, cambios de bandeja y confirmación SSE | **Hecho:** `remision_externa_recibida` (especialistas), `remision_externa_invalida` (Admin) y `remision_socio_aceptada`/`rechazada` (médico remitente), por bandeja y SSE; catálogo en `docs/EVENTOS.md` |
| STRIDE actualizado | Evidencias de validación/suplantación/manipulación del receptor | **Hecho:** filas T2 y tabla R34 de `docs/STRIDE.md` |

## 3. Natalia — tareas de cierre individual

- [x] R12, R23, R24, R25, R26 inicial, Bundle R30, consentimiento y envío piloto local.
- [x] Vista previa del Bundle #14 y confirmación de 11 recursos desde frontend.
- [ ] Revisar SQL `r30_envios`, auditoría y entrega SSE real post-envío: `...`.
- [x] Repetir pruebas completas tras el último cambio: `python -m pytest tests -q` desde `back/` → **213 passed** (2026-11-20, `main` en `f03550f`).
- [ ] Revisar unidades UCUM y limitaciones de serialización FHIR: `...`.
- [x] Actualizar STRIDE con evidencias comprobadas de Sarah y Annie (tabla R34 y fila T2 de `docs/STRIDE.md`).
- [x] Recepción R30 documentada (Annie, `docs/CONTRATO_R30.md`) y autenticada con R31 (Sarah).
- [ ] Ida y vuelta con el socio asignado (R33).
- [x] Subir cambios a rama y abrir PR: PR #4 y #5 fusionados en `main`.
- [ ] Ensayar defensa cruzada de un control STRIDE: `...`.

## 4. Equipo — entrega obligatoria

- [ ] URL Git con acceso docente: `https://github.com/nataliap2005/proyecto-triage` (confirmar acceso de lectura del docente).
- [ ] `tester.yaml` vigente en raíz: URL pública correcta, usuarios de prueba revisados: `...`.
- [ ] Un solo `docker compose up -d` reproducible en máquina anfitriona: `...`.
- [ ] Asignar encargado de mantener disponible Quick Tunnel toda la jornada: `...`.
- [ ] Verificar acceso a frontend, API, FHIR y endpoints de evaluación desde red externa: `...`.
- [ ] Compilar capturas, logs anonimizados, diagramas y reporte de tests: `...`.
