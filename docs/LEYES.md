# Marco normativo y controles técnicos (R22)

Este documento relaciona cada norma colombiana relevante con lo que el sistema hace para cumplirla. Es un documento **académico** y no constituye concepto jurídico.

---

## 1. Ley 1581 de 2012 — protección de datos personales

Artículo 4: principios del tratamiento.

| Principio (art. 4) | Qué exige | Control en el sistema |
|---|---|---|
| a) Legalidad | Tratar los datos conforme a la ley | Este mapa normativo; tratamiento solo para atención y gestión del hospital |
| b) Finalidad | Finalidad legítima e informada | Los datos clínicos solo alimentan la atención, la historia clínica y el apoyo de IA; el payload a IA solo lleva los campos necesarios |
| c) Libertad | Consentimiento previo, expreso e informado | **No implementado** como flujo en la aplicación (proyecto académico, pacientes ficticios). Un despliegue real necesitaría registrar el consentimiento |
| d) Veracidad | Datos completos, exactos y actualizados | Historia clínica estructurada; correcciones con trazabilidad en `auditoria_cambios` |
| e) Transparencia | El titular puede consultar sus datos | Rol `Paciente`: consulta su propia información |
| f) Acceso y circulación restringida | Solo personas autorizadas | Control por rol (RBAC) en el API; el `Contable` no ve información clínica; el `Paciente` solo ve lo suyo; CORS restringido |
| g) Seguridad | Medidas técnicas y administrativas | JWT (HS256, 60 min), contraseñas con argon2, bloqueo tras 3 intentos fallidos, cabeceras de seguridad y límite de peticiones en Nginx, auditoría, secretos fuera de Git |
| h) Confidencialidad | Reserva de los datos | Seudonimización (HMAC-SHA256) del paciente en el payload a IA; el servicio `ml` exige token |

## 2. Ley 2015 de 2020 — historia clínica electrónica interoperable (IHCE)

| Artículo | Contenido | Control en el sistema |
|---|---|---|
| 1 | Regula la interoperabilidad de la historia clínica electrónica, para intercambiar datos clínicos relevantes | HAPI FHIR R4 como servidor de interoperabilidad, expuesto en `/fhir/` |
| 2 | Define IHCE como registro integral y cronológico, seguro, fiable y disponible; define interoperabilidad | Historia clínica integrada (encuentros, observaciones, diagnósticos, notas, exámenes, prescripciones, remisiones) y recursos FHIR: Patient, Practitioner, Encounter, Observation, Condition, Medication, MedicationRequest, ServiceRequest, DiagnosticReport, DocumentReference, QuestionnaireResponse, Invoice |
| 3 | Los prestadores registran y ponen a disposición los datos en la plataforma de interoperabilidad | El proyecto simula esa plataforma con HAPI FHIR. **No** se conecta a la plataforma nacional |
| 5 | El prestador conserva la custodia de los registros en sus sistemas | Datos clínicos en PostgreSQL (Neon) bajo responsabilidad de la institución; copias en HAPI |

> Limitación: la ley habla de historia **firmada digitalmente** por el profesional. El proyecto autentica con usuario y contraseña y audita las acciones, pero **no usa firma digital** en sentido legal.

## 3. Resolución 866 de 2021 — datos clínicos relevantes para interoperabilidad

Define el conjunto de **elementos de datos clínicos relevantes** que los prestadores deben intercambiar (art. 5): identificación del usuario, contacto con el servicio de salud (incluye la **prioridad de triaje**, vía de ingreso y diagnóstico inicial), tecnologías en salud y sus resultados (diagnósticos finales, remisiones). Los diagnósticos usan CIE-10.

| Aspecto | Control en el sistema |
|---|---|
| Datos de identificación, contacto y resultados (art. 5) | Pacientes, encuentros (con nivel de triaje), diagnósticos con código CIE-10 (`Condition`), remisiones |
| Codificación CIE-10 | Los diagnósticos usan `codigo_cie10` y el sistema ICD-10 en FHIR |
| Corrección con trazabilidad (art. 10, par. 2) | Los cambios no sobrescriben sin rastro: `auditoria_cambios` guarda tabla, acción, datos anteriores y nuevos, usuario y fecha |
| Uso solo para atención en salud (art. 22) | Los datos no se comercializan; la IA recibe solo el mínimo y seudonimizado |
| Seguridad y privacidad (art. 19) y privacidad por diseño (art. 18) | Minimización y seudonimización del payload; RBAC; auditoría |

> Aclaración: la resolución **no nombra HL7 FHIR**. Remite al "lenguaje común de intercambio" y al anexo técnico que administra el Ministerio de Salud. FHIR R4 fue una decisión de diseño del equipo; este proyecto no implementa el anexo técnico oficial de la resolución.

## 4. Resolución 5596 de 2015 — criterios técnicos del triage

Define el triage como la evaluación clínica breve que ordena la atención según la necesidad clínica y los recursos, y establece **cinco categorías (Triage I a V)**: la I requiere atención inmediata y la II dentro de 30 minutos. Dispone que **el triage no puede usarse para negar la atención de urgencias**.

| Aspecto | Control en el sistema |
|---|---|
| Cinco niveles de triage | El sistema usa niveles 1–5 y los agrupa en tres categorías para el modelo (crítico 1–2, medio 3, no crítico 4–5) |
| Triage que cambia con el estado del paciente | Los signos vitales se registran en cada encuentro; las alertas críticas persisten y se escalan al Admin si nadie las reconoce en 5 minutos |
| El triage no niega atención | La IA solo apoya: **la decisión final es del profesional** y ningún paciente se rechaza por el resultado |

## 5. Resolución 1995 de 1999 — historia clínica

Establece normas para el manejo de la historia clínica. Artículos aplicados:

| Artículo | Tema | Control en el sistema |
|---|---|---|
| 13 | Custodia de la historia clínica a cargo del prestador que la generó, que puede entregar copia al usuario | Los datos permanecen en la infraestructura del hospital; no se entregan a terceros |
| 14 | Acceso a la historia: el usuario, el equipo de salud, las autoridades judiciales y de salud en los casos previstos por la ley y quienes la ley determine; solo para fines legalmente procedentes y manteniendo la reserva | Acceso por rol; el paciente ve la suya; auditoría de los accesos y cambios |
| 16 | Seguridad del archivo: área restringida, acceso solo del personal autorizado, conservación de la integridad sin alteraciones | Autenticación, bloqueo de cuentas, contraseñas con hash, auditoría; el PDF de la historia solo se descarga con sesión y permiso |

## 6. Resolución 3100 de 2019 — habilitación de servicios

Define los procedimientos y condiciones de inscripción de prestadores y de habilitación de servicios de salud, incluidos los de urgencias, con estándares de historia clínica y registros. El proyecto no es un servicio habilitable; se toma como referencia de buenas prácticas.

| Aspecto | Control en el sistema |
|---|---|
| Registro y trazabilidad de la atención | Encuentro con signos vitales, triaje, diagnósticos, notas, exámenes y prescripciones; auditoría integral de acciones |
| Remisión a otro servicio | Módulo de remisiones con aceptación, rechazo y finalización |

---

## Controles transversales

| Control | Dónde |
|---|---|
| Autenticación (JWT, 60 min) y roles (`Admin`, `Medico`, `Especialista`, `Paciente`, `Contable`) | `back/` |
| Contraseñas con hash argon2 | `back/` |
| Bloqueo tras 3 intentos fallidos; desbloqueo solo por `Admin`; evento `cuenta_bloqueada` | `back/auth/service.py` y `docs/EVENTOS.md` |
| Auditoría: `auditoria_cambios` y `auth_log` | `back/squema_bd.sql` |
| Eliminación lógica (soft delete) y restauración por `Admin` | R14; pantalla "Pacientes eliminados" |
| Nginx: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, límite de 10 peticiones/s | `front/nginx.conf` |
| Seudonimización y minimización para IA | `back/services/seudonimizacion.py` |
| Secretos fuera de Git | `.gitignore`; solo se versionan `.env.example` y `back/example.pass.env` |

## Limitaciones que debe conocer quien evalúe

- No hay flujo de **consentimiento informado** ni gestión de derechos del titular (consulta, rectificación, supresión).
- No hay **firma digital** de la historia clínica.
- No se conecta a la plataforma nacional de interoperabilidad.
- Todos los pacientes son ficticios; el hospital San Andrés de Tumaco es el escenario, no un cliente real.

## Fuentes

- [Ley 1581 de 2012, art. 4](http://www.secretariasenado.gov.co/senado/basedoc/ley_1581_2012.html) — Secretaría del Senado.
- [Ley 2015 de 2020](https://normograma.supersalud.gov.co/compilacion/docs/ley_2015_2020.htm) — Normograma Supersalud.
- [Resolución 866 de 2021](https://normativa.colpensiones.gov.co/compilacion/docs/resolucion_minsaludps_0866_2021.htm) — Normativa Colpensiones.
- [Resolución 3100 de 2019](https://normograma.supersalud.gov.co/compilacion/docs/resolucion_minsaludps_3100_2019.htm) — Normograma Supersalud.
- Resolución 5596 de 2015 (Ministerio de Salud y Protección Social), Diario Oficial 49.739, 28 de diciembre de 2015.
- [Resolución 1995 de 1999](https://normograma.invima.gov.co/normograma/compilacion/docs/resolucion_minsalud_r1995_99.htm) — Normograma Invima; coincide con el [texto en PDF de la Unidad para las Víctimas](https://www.unidadvictimas.gov.co/wp-content/uploads/Documentos/resoluciones/RESOLUCI%c3%93N_1995_1999.pdf).

## Documentos relacionados

[`MODELO.md`](MODELO.md) (seudonimización del payload) · [`EVENTOS.md`](EVENTOS.md) · [`CONTABILIDAD.md`](CONTABILIDAD.md) · [`DATASETS.md`](DATASETS.md) · [README](../README.md)


## R34 · Mapa de requisitos y controles adicionales R23–R33

> **Nota de alcance:** esta matriz relaciona decisiones técnicas con temas normativos; **no constituye concepto jurídico ni certificación de cumplimiento**. Las referencias son las normas listadas en este documento. “Pendiente” no se debe presentar como control disponible.

| Requisito | Control / evidencia verificable | Relación normativa relevante | Estado y responsable |
|---|---|---|---|
| R23 · RAG con fuentes | Autorización por paciente/encuentro, fragmentos citados o abstención, sin datos no aprobados en contexto | Ley 1581/2012 (finalidad, circulación restringida, seguridad); Res. 1995/1999 (reserva documental) | **Natalia:** demostrado con consultas y tests |
| R12 · Seudonimización | HMAC y filtro por historia sintética aprobada, canario sin fugas detectadas | Ley 1581/2012; Res. 1995/1999 | **Natalia:** prueba acotada |
| R24 · Herramientas | RBAC backend, auditoría de invocación, no ejecución libre desde LLM, borrador no enviado | Ley 1581/2012; Res. 1995/1999; Res. 3100/2019 (seguridad/calidad en prestación) | **Natalia:** tres herramientas probadas |
| R25 · Inyección y bloqueo | Detección, registro de cuenta e IP observada, bloqueo temporal; filtrado clínico continúa en backend | Ley 1581/2012 (seguridad); Res. 1995/1999 | **Natalia:** bloqueo/desbloqueo verificados en piloto |
| R26 · STRIDE | DFD, fronteras de confianza, amenazas y riesgos residuales por categoría | Ley 1581/2012; Res. 1995/1999; Res. 866/2021; Res. 3100/2019 | **Natalia:** análisis documentado, evidencias externas `...` |
| R27 · Cifrado sensible AES-GCM | Documento de identidad, teléfono y dirección cifrados con AES-256-GCM en PostgreSQL (el documento se reemplaza en las tablas por un número interno HMAC y se guarda cifrado en `identidades`); llave en variable de entorno (`CIFRADO_LLAVE_K1`), nunca en el repositorio; descifrado en un solo punto y auditoría con valores cifrados | Ley 1581/2012 | **Sarah:** implementado (18 + 22 pruebas). Residual: auditoría anterior a R27 sin reescribir (cadena R28), HAPI FHIR y MongoDB fuera de PostgreSQL |
| R28 · Auditoría encadenada | Cadena SHA-256 sobre `auditoria_cambios` (trigger); `GET /auditoria/verificar-cadena`, solo Admin, informa el primer registro roto; prueba de manipulación con reversión | Ley 1581/2012; Res. 1995/1999 | **Sarah:** implementado y probado el 2026-11-15 (314 eslabones íntegros). Residual: `auth_log` y `oauth_eventos` quedan fuera de la cadena; borrar la cola exige anclar el `hash_cabeza` fuera de la base |
| R30 · FHIR remisiones | Consent previo, minimización de datos, LOINC/SNOMED, `Bundle transaction`, `OperationOutcome` | Ley 1581/2012; Ley 2015/2020; Res. 866/2021; Res. 1995/1999 | **Natalia:** piloto local con remisión #14, 11 recursos |
| R31 · Identidad institucional | Credenciales de sistema por institución (no usuario humano), secreto en hash, token de 10 minutos, permisos mínimos, nonce antirreplay, bloqueo por intentos, revocación inmediata; HTTPS lo aporta el túnel en el despliegue | Ley 1581/2012; Ley 2015/2020 | **Sarah:** implementado y probado para la entrada (2026-11-15). PENDIENTE: credencial del socio real (depende de la pareja de R33) y conexión al endpoint real de recepción |
| R29 · Entradas externas autenticadas | Receptor del socio con token institucional (`bundle:write`/`task:write`) + `x-nonce`; `fhir-hook` con token en tiempo constante; ambos validan el recurso antes de procesarlo (401/403 sin credencial, 400/413/415/422 con `OperationOutcome` si es inválido); Nginx solo publica de HAPI lo que exige R21 | Ley 1581/2012 (seguridad, art. 4 g); Res. 866/2021; Res. 1995/1999 | **Annie:** implementado y probado el 2026-11-18 (`test_recepcion_externa_r30.py`, `test_fhir_hook_r29.py`, script 12/12 en `docs/evidencias/R29_R30/`) |
| R30 · Recepción y respuesta | Validación sin escrituras parciales, ids del socio reescritos, remisión en bandeja del especialista y en vivo, aceptación/rechazo devuelto como `Task`, respuesta del socio avisada al médico; todo auditado con `origen = SOCIO` dentro de la cadena R28 | Ley 1581/2012 (circulación restringida); Ley 2015/2020 (interoperabilidad de la historia clínica); Res. 866/2021; Res. 1995/1999 | **Annie:** implementado; ida y vuelta probada en autoprueba local el 2026-11-18. PENDIENTE: prueba con el socio real (R33) |
| R32 · Consentimiento hacia el socio | El consentimiento es por **institución destino** (`R30_SOCIO_ID`), vence (`R30_CONSENTIMIENTO_DIAS`, 365 por defecto), se revoca de inmediato y queda auditado; sin consentimiento vigente no se envía (403) y el receptor rechaza Bundles sin `Consent` activo (422) | Ley 1581/2012 (arts. 6 y 9: autorización previa para datos sensibles; transferencia); Decreto 1377/2013 | **Annie + Natalia:** implementado el 2026-11-18; pacientes con consentimiento del piloto (`socio-piloto`) deben volver a autorizar para la institución real |
| R33 · Demostración cruzada | Ida y vuelta entre URL públicas, sin recargar, con auditoría en ambos lados | Ley 2015/2020; Res. 866/2021 | **Equipo:** PENDIENTE (depende del socio asignado) |

El piloto exitoso R30 acredita recepción técnica de HAPI dentro del equipo, **no** intercambio jurídico/operativo con una institución externa. Las pruebas con pacientes sintéticos y el consentimiento del prototipo no representan un consentimiento clínico productivo.
