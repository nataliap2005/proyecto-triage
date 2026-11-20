# Evidencias R28 y R31 (API local, Swagger, 2026-11-15)

| Archivo | Que demuestra | Hora |
|---|---|---|
| R28_verificar_cadena_ok_parte1/2.png | GET /auditoria/verificar-cadena como Admin: 200, integra=true, 314 eslabones, sin_encadenar=0, sin eslabon roto | 16:09 UTC (11:09 Bogota) |
| R28_sin_token_rechazado_401_parte1/2.png | Sin token: 401 "Not authenticated", www-authenticate Bearer | 16:14 UTC |
| R28_medico_rechazado_403.png | Usuario no Admin (rol medico): 403 "No tiene permisos para esta operacion" | 16:25 UTC |
| R31_credenciales_incorrectas_401.png | POST /oauth/token con cliente inexistente: 401 invalid_client "Credenciales invalidas", www-authenticate Basic (datos inventados) | 16:36 UTC (11:36 Bogota) |
| R31_token_valido_200.png | POST /oauth/token con socio-demo: 200, token_type Bearer, expires_in 600 (10 min), scope bundle:write task:write, cache-control no-store (token oculto) | 16:38 UTC (11:38 Bogota) |
| R31_institucion_yo_200.png | GET /institucion/yo con el token de socio-demo: 200, client_id socio-demo, scopes bundle:write y task:write | 16:40 UTC (11:40 Bogota) |
| R31_token_institucional_vs_api_clinica_401.png | El mismo token en GET /auth/me (API clinica): 401 "Token invalido o vencido". Las credenciales del socio no dan acceso a la API clinica | 16:40 UTC (11:40 Bogota) |
| R31_scope_no_concedido_400.png | POST /oauth/token pidiendo un permiso no asignado: 400 invalid_scope "Alguno de los permisos pedidos no esta autorizado" | 16:42 UTC (11:42 Bogota) |
| R31_nonce_primer_envio_200.png | POST /institucion/prueba-bundle con x-nonce nuevo: 200 estado autorizado, institucion socio-demo | 16:44 UTC (11:44 Bogota) |
| R31_nonce_repetido_409.png | Mismo x-nonce repetido: 409 "Solicitud repetida: el nonce ya fue usado" (anti-repeticion) | 16:44 UTC (11:44 Bogota) |
| R31_token_alterado_401.png | Token institucional alterado: 401 "Token institucional invalido o vencido", www-authenticate Bearer error=invalid_token | 16:46 UTC (11:46 Bogota) |
| R31_eventos_oauth_admin_200.png | GET /oauth/eventos como Admin: 200, eventos TOKEN_RECHAZADO, NONCE_REPETIDO, SCOPE_INVALIDO con client_id, exitoso=false, detalle y fecha (todo lo probado quedo registrado) | 16:49 UTC (11:49 Bogota) |
| R31_institucion_prueba_token_200.png | POST /oauth/token con institucion-prueba-r31 (solo task:write): 200, scope task:write, expires_in 600 (token oculto) | 17:18 UTC (12:18 Bogota) |
| R31_scope_insuficiente_403.png | POST /institucion/prueba-bundle con institucion-prueba-r31 (task:write, sin bundle:write): 403 "La institucion no tiene permiso para esta operacion", www-authenticate Bearer error=insufficient_scope scope=bundle:write | 17:20 UTC (12:20 Bogota) |
| R31_secreto_viejo_tras_rotar_401.png | Tras rotar el secreto de institucion-prueba-r31, el secreto anterior da 401 invalid_client | 17:25 UTC (12:25 Bogota) |
| R31_secreto_nuevo_tras_rotar_200.png | Con el secreto nuevo tras rotar: 200, scope task:write (token oculto) | 17:26 UTC (12:26 Bogota) |
| R31_token_tras_baja_401.png | Tras desactivar institucion-prueba-r31, su token (emitido 17:26:44, vigente hasta 17:36:44) da 401 en GET /institucion/yo a las 17:28:29: revocacion inmediata | 17:28 UTC (12:28 Bogota) |

Notas:
- Se recorto el bloque Curl de la primera captura porque mostraba parte del token.
- La captura del login Admin NO se incluye: su bloque Curl mostraba la contrasena.
- hash_cabeza de la verificacion: se conserva el valor completo fuera del repositorio.
- R31 completo. Hechas: credenciales falsas, token valido, /institucion/yo, token vs API clinica, invalid_scope, nonce 200/409, token alterado, eventos, 403 scope insuficiente, rotacion (viejo 401, nuevo 200), baja con revocacion inmediata. institucion-prueba-r31 quedo DESACTIVADA en la base (no se borra). invalid_scope, 403, 409, token institucional vs API clinica.

REGISTRO_SERVIDOR_R28_R31.txt: peticiones HTTP que recibio el servidor durante las pruebas, en orden (login 200, verificar-cadena 200/401/403, oauth/token 401/200/400, institucion/yo 200/401, auth/me 401, prueba-bundle 200/409, oauth/eventos 200). Coincide con las capturas.
