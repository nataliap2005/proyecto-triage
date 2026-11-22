# Contrato de interoperabilidad R30 · Remisiones FHIR entre instituciones

Documento para el **equipo socio** (R33). Describe cómo nos envían remisiones, cómo les respondemos y cómo nos responden a las que les enviamos. Todo viaja en FHIR R4 (JSON), sin correos ni archivos manuales.

`<base>` = nuestra URL pública + `/api`, por ejemplo `https://<tunel>.trycloudflare.com/api`. La URL del túnel cambia al reiniciarse: se confirma el día de la prueba.

## 1. Autenticación (R31)

Cada institución entra con **credenciales de sistema** (no con un usuario humano). Nosotros les creamos un `client_id` y un `client_secret` y se los entregamos por un canal privado; ustedes nos dan los suyos por la misma vía.

```http
POST <base>/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=<id>&client_secret=<secreto>
```

Respuesta: `{"access_token": "...", "token_type": "Bearer", "expires_in": 600, "scope": "bundle:write task:write"}`. El token dura **10 minutos** y solo sirve para los dos endpoints de entrada; en la API clínica responde 401.

Cada petición de entrada lleva:

| Cabecera | Valor |
|---|---|
| `Authorization` | `Bearer <access_token>` |
| `x-nonce` | Valor **nuevo en cada envío**: 16 a 128 caracteres de `A-Z a-z 0-9 - _` (un UUID sin llaves sirve) |
| `Content-Type` | `application/fhir+json` |

### 1.1 Alternativa: clave fija por institución (sin token)

R31 admite "client credentials **o API key** por institución". Si su sistema no pide token, puede entrar con una **clave fija**: es el mismo `client_secret` que les entregamos, enviado directamente en cada petición. Este modo lo activamos para **una institución a la vez** (`R30_ENTRADA_CLIENT_ID` en nuestro servidor); confírmenlo con nosotros antes de usarlo.

| Cabecera | Valor |
|---|---|
| `X-System-Key` (o `X-API-Key`, o `Authorization: Bearer <clave>`) | Su `client_secret` |
| `Content-Type` | `application/fhir+json` o `application/json` |
| `x-nonce` | Opcional en este modo; si lo envían, se valida igual (409 si se repite) |

- Clave vacía o incorrecta: **401**. Rotar o desactivar la credencial con nuestro script la revoca de inmediato.
- **Prueba de conexión:** `POST <base>/fhir/remisiones-r30/recibir` con la cabecera `X-Interop-Ping: true` o un cuerpo `{"resourceType": "Parameters"}` responde **200** con un `OperationOutcome` informativo, sin guardar nada.
- Para socios de clave fija toleramos diferencias de formato que no cambian el contenido clínico: se ignora `security_envelope`; si faltan, se completan `ServiceRequest.status = active` / `intent = order`, `Observation.status = final`, `Consent.provision.type = permit` y la referencia al único `Patient` del Bundle (también si lo nombran por su documento en `identifier`); un `ServiceRequest` que solo trae `code.text` recibe además el código SNOMED CT `3457005` (remisión) sin perder su texto. Un valor presente e inválido (por ejemplo `provision.type = deny` o un recurso de otro paciente) se sigue rechazando con 422.

## 2. Ustedes nos remiten un paciente

```http
POST <base>/fhir/remisiones-r30/recibir        (permiso bundle:write)
```

Cuerpo: un `Bundle` de tipo `transaction` (o `collection`) con **una remisión**:

| Recurso | Cantidad | Reglas |
|---|---|---|
| `Patient` | exactamente 1 | Los datos de identidad son opcionales: envíen solo lo necesario (R32) |
| `ServiceRequest` | exactamente 1 | `status = active`; `intent` = `order`, `original-order`, `plan` o `proposal`; `code` con un código **SNOMED CT** (`http://snomed.info/sct`) o **LOINC**; `subject` al Patient del Bundle. La especialidad va en **`performerType.text`** (por ejemplo `"Cardiología"`) y el motivo en `reasonCode[].text` |
| `Observation` | 0 o más | Código **LOINC** (`http://loinc.org`); `status` = `final`, `amended` o `corrected`; `subject` al Patient |
| `DiagnosticReport` | 0 o más | Solo el reporte de IA **aprobado**: `status` = `final`, `amended` o `corrected`; `code` con `coding` o `text`; `subject` al Patient |
| `Consent` | exactamente 1 | `status = active`, `patient` al Patient, `provision.type = permit`; si trae `provision.period.end`, no puede estar vencido |
| `Task` | 0 o 1 | `status = requested`, `focus` al ServiceRequest y `for` al Patient. **Recomendado**: con él les respondemos |
| `Practitioner`, `PractitionerRole`, `Organization`, `Condition` | opcionales | Sin reglas adicionales |

- En `transaction`, cada entrada usa solo `POST` (url = tipo) o `PUT` (url = `Tipo/id`). `DELETE`, `GET` y `PATCH` se rechazan.
- Las referencias pueden ser `Tipo/id` o `urn:uuid:`. Una referencia a algo que no viene en el Bundle se conserva solo como texto.
- **Para que podamos responderles, envíen ids estables** (`PUT ServiceRequest/<id>` y `PUT Task/<id>`): nuestra respuesta apunta a esos ids.
- Límites: 2 MB, máximo 50 recursos, JSON con profundidad máxima de 40.
- Nosotros guardamos sus recursos con **ids propios** (`ext-...`): no pueden sobrescribir nada nuestro.

| Respuesta | Cuándo | Cuerpo |
|---|---|---|
| **200** | Remisión recibida; el especialista la ve en vivo | `Bundle` `transaction-response`; cabecera `X-Remision-Externa: <id>` |
| 400 | Falta `x-nonce` o es inválido; el cuerpo no es JSON | JSON `detail` / `OperationOutcome` |
| 401 | Sin token, token vencido o alterado, institución desactivada | JSON `detail` |
| 403 | El token no tiene el permiso | JSON `detail` |
| 409 | `x-nonce` repetido, **o** esa misma remisión (`ServiceRequest`) ya fue recibida | JSON `detail` / `OperationOutcome` `duplicate` |
| 413 / 415 | Demasiado grande / `Content-Type` que no es FHIR | `OperationOutcome` |
| **422** | Bundle o recurso inválido. **No se guarda nada** | `OperationOutcome` con el motivo en `diagnostics` |
| 502 / 503 | Nuestro servidor FHIR falló o no está disponible; reintenten con un nonce nuevo | `OperationOutcome` |

El nonce se gasta aunque el Bundle se rechace: un reintento necesita uno nuevo.

## 3. Les respondemos (aceptación o rechazo)

Cuando nuestro especialista acepta o rechaza, enviamos un `Task` a **su** endpoint de respuesta, autenticándonos con las credenciales que ustedes nos den (client credentials o API key) y un `x-nonce` nuevo:

```json
{
  "resourceType": "Task",
  "id": "<id del Task que ustedes enviaron, si lo enviaron con id>",
  "status": "accepted",
  "intent": "order",
  "focus": {"reference": "ServiceRequest/<su id>"},
  "basedOn": [{"reference": "ServiceRequest/<su id>"}],
  "for": {"reference": "Patient/<su id>"},
  "statusReason": {"text": "Cupo mañana 8 a. m. en consulta de cardiología"},
  "businessStatus": {"text": "Aceptada por el especialista"},
  "owner": {"display": "<nuestra institución>"},
  "lastModified": "2026-11-18T22:22:06-05:00",
  "identifier": [{"system": "urn:salud-digital:remision-externa", "value": "<nuestro id>"}]
}
```

`status` es `accepted` o `rejected`. Esperamos de ustedes un **200 o 201**; con cualquier otro código la respuesta queda pendiente y nuestro especialista puede reintentar.

**Necesitamos de ustedes:** la URL de ese endpoint y nuestras credenciales en su sistema (URL de token, `client_id` y `client_secret`, o una API key y el nombre de su cabecera).

**Cuando les enviamos una remisión**, damos el envío por confirmado si su sistema responde 200 o 201 con **un** `Bundle` `transaction-response` (una respuesta 200/201 por recurso) **o** con un `Task` en estado `requested`, `received`, `accepted`, `in-progress` o `completed`. Un `Task` `rejected` o cualquier otra respuesta se muestra como envío no confirmado.

## 4. Ustedes nos responden (a remisiones que les enviamos)

```http
POST <base>/fhir/remisiones-r30/respuesta      (permiso task:write)
```

Cuerpo: un `Task` con:
- `status` = `accepted` o `rejected`;
- **o** `id` igual al del Task que les enviamos, **o** `focus` / `basedOn` apuntando a nuestro `ServiceRequest/<id>`;
- el motivo en `statusReason.text` (opcional).

Solo se aceptan respuestas a remisiones que **les enviamos a ustedes**.

| Respuesta | Cuándo |
|---|---|
| **200** | Registrada; el médico que remitió recibe el aviso en vivo. Devolvemos el mismo Task |
| 200 | La misma respuesta otra vez (reintento): no se repite nada |
| 404 | Ese Task no corresponde a ninguna remisión que les hayamos enviado |
| 409 | Ya habían respondido distinto (no se puede cambiar de opinión) |
| 401 / 403 / 400 / 415 / 413 / 422 | Igual que en la sección 2 (máx. 64 KB) |

## 5. Lo que enviamos nosotros (resumen)

Nuestro Bundle (`transaction`, todo con `PUT` e ids estables `r30-...`) trae: `Patient` seudonimizado sin nombre ni documento, `Consent` activo con su vigencia, `ServiceRequest` (SNOMED `306206005`, motivo y especialidad), `Task` `requested`, `Observation` de signos vitales con LOINC y el `DiagnosticReport` de IA solo si fue aprobado. Solo se envía si el paciente autorizó compartir con **su** institución (R32).

## 6. Auditoría

Los dos lados auditan el intercambio. Nosotros registramos cada recepción, cada rechazo por validación, cada respuesta suya y cada decisión de nuestro especialista, con `origen = 'SOCIO'` (o el usuario, si es nuestro), dentro de la auditoría encadenada con hashes (R28).
