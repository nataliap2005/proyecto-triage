# R34 · Secciones pendientes de Sarah, Annie y coordinación

Este archivo **no presenta como implementadas** las partes que aún requieren evidencia. Sustituir cada `...` con información real y enlazar commit, ruta de código, prueba, captura o endpoint antes de enviar al docente.

## 1. Sarah — seguridad de datos y autenticación institucional

| Componente | Evidencia exigida | Estado |
|---|---|---|
| R27 cifrado AES-GCM de datos sensibles | Campos cubiertos, modo nonce, manejo de claves/rotación, prueba descifrado y acceso no autorizado | **Hecho para teléfono y dirección:** `back/core/cifrado.py` (AES-256-GCM, nonce aleatorio de 12 bytes, formato `v1.k1.<nonce>.<cifrado>` con identificador de llave para rotar), descifrado central en `back/core/database.py`, migración `017`, `back/scripts/cifrar_datos_existentes_r27.py`, 18 pruebas (valor alterado, otra llave y otro campo no descifran; sin llave responde 503). **Pendiente:** cifrar los datos existentes en la base compartida y capturas. **No cubierto:** el documento de identidad (llave técnica) |
| R28 auditoría con cadena de hashes | Estructura de hash, orden, prueba de manipulación y validador de integridad | **Hecho (2026-11-15):** hash SHA-256 sobre `auditoria_cambios` por trigger con bloqueo; migración `016`; `back/routers/auditoria_cadena.py`; `back/scripts/prueba_r28_manipulacion.py`; verificación Admin 200 (314 eslabones), sin token 401, médico 403; commit `5f1f14f`, PR #6 |
| R31 autenticación entre instituciones | Mecanismo elegido, identidad del socio, HTTPS, credenciales y rotación, prueba de rechazo | **Hecho para la entrada (2026-11-15):** OAuth2 `client_credentials` con JWT de 10 minutos; `back/auth/institucional.py`, `back/routers/oauth_institucional.py`, migración `015`, script de alta, rotación y baja; 31 pruebas; rechazos 401, 400, 403 y 409 y rotación comprobados; commits `c89ca86`, `4f4dc14`, `33f834f`, PR #6. **Pendiente:** credencial del socio real y HTTPS de extremo a extremo con el socio |
| STRIDE actualizado | Evidencias para Spoofing/Repudiation/Disclosure; riesgos residuales | **Hecho para R27, R28 y R31:** filas S2, T1, R1, I3 y E3 y tabla final de `docs/STRIDE.md` |
| LEYES actualizado | Alcance de controles R27, R28, R31 y normativa aplicable | **Hecho para R27, R28 y R31** en `docs/LEYES.md` |

## 2. Annie — seguridad externa e interoperabilidad de entrada

| Componente | Evidencia exigida | Estado |
|---|---|---|
| Receptor real del Bundle FHIR | URL HTTPS y contrato de `Bundle transaction`, validación de recursos y OperationOutcome | `...` |
| Protección webhook/endpoints | Header/firma/token, validación origen, rechazo de request inválido o repetido | `...` |
| Integración HAPI socio | Pruebas de persistencia y rechazo sin escrituras parciales | `...` |
| Consentimiento y visualización receptor | Cómo se reconoce `Consent`, posibilidad de revocación y vista clínica | `...` |
| Retorno estado Task | Estados aceptado/rechazado/finalizado, payload y transición permitida | `...` |
| Notificaciones socio ↔ remitente | Evento recibido, destinatario, cambios de bandeja y confirmación SSE | `...` |
| STRIDE actualizado | Evidencias de validación/suplantación/manipulación del receptor | `...` |

## 3. Natalia — tareas de cierre individual

- [x] R12, R23, R24, R25, R26 inicial, Bundle R30, consentimiento y envío piloto local.
- [x] Vista previa del Bundle #14 y confirmación de 11 recursos desde frontend.
- [ ] Revisar SQL `r30_envios`, auditoría y entrega SSE real post-envío: `...`.
- [ ] Repetir pruebas completas tras el último cambio (66 eran previas): fecha, comando y resultado `...`.
- [ ] Revisar unidades UCUM y limitaciones de serialización FHIR: `...`.
- [ ] Actualizar STRIDE con evidencias comprobadas de Sarah y Annie: `...`.
- [ ] Resolver y documentar recepción en vivo R30/R33 con Annie y Sarah: `...`.
- [ ] Subir cambios a rama, abrir PR y registrar URL: `...`.
- [ ] Ensayar defensa cruzada de un control STRIDE: `...`.

## 4. Equipo — entrega obligatoria

- [ ] URL Git con acceso docente: `...`.
- [ ] `tester.yaml` vigente en raíz: URL pública correcta, usuarios de prueba revisados: `...`.
- [ ] Un solo `docker compose up -d` reproducible en máquina anfitriona: `...`.
- [ ] Asignar encargado de mantener disponible Quick Tunnel toda la jornada: `...`.
- [ ] Verificar acceso a frontend, API, FHIR y endpoints de evaluación desde red externa: `...`.
- [ ] Compilar capturas, logs anonimizados, diagramas y reporte de tests: `...`.
