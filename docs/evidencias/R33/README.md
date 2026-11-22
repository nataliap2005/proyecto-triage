# R33 · Prueba de interoperabilidad con equipos externos (2026-11-21)

Registro de la prueba hecha el 21 de noviembre de 2026 (hora de Bogotá) con dos equipos de la clase, por las URL públicas de cada uno. Este archivo no contiene secretos ni datos de pacientes: las claves se entregaron por chat privado y los pacientes usados fueron de prueba.

## Equipo 1 · Hospital Universitario UCI - Salud Digital

- **Credencial en nuestro sistema:** `socio-predictivoseb` (creada con `scripts/gestionar_cliente_institucional.py`, permisos `bundle:write` y `task:write`).
- **Mecanismo R31:** el equipo no pide token; envía su clave directamente (`X-System-Key`). Para ellos se agregó el modo de clave fija por institución (PR #16), que R31 admite ("client credentials o API key por institución").
- **Su contrato:** recepción en `/interoperabilidad/remisiones`, clave en `X-System-Key`, aceptación automática con respuesta `Task` `completed` (201).

| Hora aprox. | Paso | Resultado |
|---|---|---|
| 16:14 | Primer intento desde su sistema, sin `/api` en la URL | 405: la petición llegaba a la página web, no a la API |
| 17:27 | Su Bundle de ejemplo (`collection`, con `security_envelope`, paciente referenciado por su documento) pasado por nuestra validación | Rechazado al inicio (referencia al paciente); corregido en PR #16 y aceptado |
| 17:52 | Nuestra prueba de conexión hacia su servidor (`X-Interop-Ping`) | 200 `OperationOutcome`: "R31 OK: credencial institucional X-System-Key autenticada" |
| 18:22 | Su "Probar conexión" hacia nuestro túnel con la URL completa | 401: probablemente el Docker aún no tenía el cambio o la configuración del modo de clave fija (no se registró la causa exacta) |
| 18:25 | Mismo intento, ya con la configuración | 500: la tabla `oauth_eventos` no admitía los eventos nuevos (`CLAVE_ACEPTADA`) |
| 18:27 | Migración `020_oauth_eventos_clave_fija_r31.sql` aplicada en la base | Aplicada |
| 18:28 | Su "Probar conexión" | Conectado (200) |
| Después | Remisión enviada por el equipo | Llegó a nuestra bandeja: notificación al Admin y a la especialista de Cardiología, que pudo aceptarla o rechazarla |

## Equipo 2 · credencial `socio-prueba2`

- **Credencial en nuestro sistema:** `socio-prueba2`, entregada por chat privado junto con nuestra URL pública.
- **Credenciales en su sistema:** nos entregaron `client_id`, `client_secret` y una API key; su sistema acepta token o API key.
- **Mecanismo R31:** **token** (OAuth2 client credentials): `oauth_eventos` registra `TOKEN_EMITIDO` para `socio-prueba2` a las 19:51 y 19:55 (hora de Bogotá), con permisos `bundle:write task:write` y vigencia de 10 minutos.
- **Resultado:** se conectaron con la versión vigente del código, sin cambios adicionales. La remisión externa #9 (`Cirugía cardiovascular`, prioridad `urgent`, `Consent` activo, 4 recursos) llegó y la especialista la **aceptó** (`estado = aceptada`). Annie reportó además la notificación al Admin y a la especialista de Cardiología.

## Capturas (Swagger como Admin, base compartida)

Las horas de las respuestas están en UTC (`+00:00`); en Bogotá son 5 horas menos.

| Archivo | Qué muestra |
|---|---|
| `R33_eventos_oauth_admin_200.png` | `GET /oauth/eventos`: `socio-prueba2` con `TOKEN_EMITIDO` (token) y `socio-predictivoseb` con `CLAVE_ACEPTADA` (clave fija, 19:08 en Bogotá). Las dos formas de R31 con socios reales |
| `R33_remisiones_externas_recibidas_200.png` | `GET /remisiones-externas`: remisión #9 de `socio-prueba2`, `Consent` activo, `estado = aceptada`. Nombre, fecha de nacimiento y documento de la especialista tapados |
| `R33_cadena_R28_integra_200.png` | `GET /auditoria/verificar-cadena` después de la prueba: íntegra, 383 eslabones, 0 sin encadenar (22 de noviembre, 00:53 en Bogotá) |

## Cambios de código que salieron de la prueba

| PR | Cambio |
|---|---|
| #16 | Entrada con clave fija por institución (R31) y tolerancia al formato del socio |
| #17 | Aceptar un `Task` del socio como confirmación del envío, además de `transaction-response` |
| #18 | Migración `020`: eventos `CLAVE_ACEPTADA` y `CLAVE_RECHAZADA` en `oauth_eventos`; la prueba automática ahora simula esa restricción de la base |

## Por confirmar con evidencia

- Captura de la notificación en la bandeja (pantalla de la app).
- Envío desde nuestro sistema hacia cada equipo (botón "Enviar remisión FHIR") y la respuesta vista en su sistema.

## Operación para la sustentación

- El modo de clave fija atiende **un socio a la vez**: el que esté en `R30_ENTRADA_CLIENT_ID` del `pass.env` del servidor. Los socios con token pueden ser varios.
- Para cambiar de socio: ajustar en `back/pass.env` `R30_ENTRADA_CLIENT_ID` y el bloque `R30_SOCIO_...` (URL y credenciales del socio) y reiniciar la API (`docker compose up -d --force-recreate api`).
- La URL del túnel cambia cada vez que se reinicia: comunicarla al socio y actualizar `tester.yaml`.
- Después de la sustentación, rotar las credenciales que circularon en capturas (`python scripts/gestionar_cliente_institucional.py rotar <client_id>`).
