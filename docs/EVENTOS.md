# Catálogo de eventos

El sistema avisa en tiempo real mediante Server-Sent Events. Todo aviso pasa por
`core/eventos.publicar()`, que hace dos cosas:

1. Guarda una fila en la tabla `notificaciones` (bandeja persistente, R18).
2. Empuja el evento por el canal `GET /eventos/stream?token=...` a las pestañas
   abiertas del destinatario (R17).

Los eventos se dirigen a **usuarios concretos**, nunca a "todos". Así, un evento
clínico no llega al paciente ni al contable (alcance por rol, R17).

## Formato de cada evento

    {
      "id": 12,
      "tipo": "remision_recibida",
      "mensaje": "Nueva remisión a Cardiología: Ana Pérez",
      "fecha": "2026-10-03T21:10:05+00:00",
      "leida": false,
      "paciente_id": 1083877566,
      "...": "datos propios del hecho (remision_id, especialidad...)"
    }

## Diagrama de eventos

```mermaid
flowchart LR
    subgraph Origen
        L[Login: 3.er intento fallido]
        R[Médico crea remisión]
        E[Especialista acepta o finaliza]
        F[Observation en HAPI FHIR]
        I[POST /ia/analizar]
        T[Hilo de escalamiento, cada 30 s]
        K[Médico reconoce alerta]
        A[Médico aprueba reporte IA]
        D[Admin desactiva médico con encuentros]
    end
    P{{core.eventos.publicar}}
    L -->|cuenta_bloqueada| P
    R -->|remision_recibida| P
    E -->|remision_aceptada / finalizada| P
    F -->|"Subscription rest-hook → /fhir-hook"| P
    I -->|reporte_ia_pendiente, alerta_critica| P
    T -->|alerta_critica_escalada| P
    K -->|alerta_reconocida| P
    A -->|factura_ia_creada| P
    D -->|reasignacion_medica| P
    P --> N[(Tabla notificaciones)]
    P --> S[Canal SSE /eventos/stream]
    N --> B[Bandeja y /pendientes]
    S --> U[Pestañas abiertas del destinatario]
```

Cada evento se guarda **antes** de empujarse por SSE: si el usuario no estaba conectado, lo ve al abrir la bandeja.  En el análisis de IA, los avisos se publican después de confirmar la transacción.

## Eventos

| Evento (`tipo`) | Quién lo dispara | A quién llega | Reacción | Datos extra |
|---|---|---|---|---|
| `cuenta_bloqueada` | 3.er intento fallido de login (`auth/service.py`) | Todos los Admin activos | Aviso en bandeja y en vivo; el Admin puede desbloquear | `usuario_bloqueado`, `documento_usuario` |
| `remision_recibida` | Médico crea una remisión (`POST /remisiones`) | El especialista destino | Aviso; sube `remisiones_recibidas` | `remision_id`, `id_encuentro`, `especialidad`, `medico_remitente` |
| `remision_aceptada` | Especialista acepta (`PATCH /remisiones/{id}/aceptar`) | El médico remitente | Aviso; baja `remisiones_recibidas` del especialista | `remision_id`, `especialidad`, `observacion` |
| `remision_finalizada` | El especialista dueño marca como terminada una remisión **ya aceptada** (`PATCH /remisiones/{id}/finalizar`); si no está aceptada responde 409 | Únicamente el médico remitente (el paciente y el contable no lo reciben) | Aviso en bandeja y en vivo; la remisión pasa a `finalizada`; se audita `FINALIZAR` en `remisiones` | `remision_id`, `id_encuentro`, `especialidad`, `observacion`, `puede_revisar_cierre_encuentro` |
| `observacion_fhir` | Un sistema externo crea o actualiza una `Observation` en HAPI FHIR. HAPI la envía a `/fhir-hook` mediante la Subscription `triaje-observaciones` (rest-hook) | El médico responsable del encuentro activo del paciente; si no hay, los Admin | Aviso en bandeja y en vivo; fila `RECIBIR_FHIR` con `origen = FHIR` en `auditoria_cambios` | `origen`, `fhir_id`, `loinc`, `nombre`, `valor` |

> **Rechazo de una remisión.** `PATCH /remisiones/{id}/rechazar` (solo el especialista destino, remisión `pendiente`) cambia el estado a `rechazada` y registra `RECHAZAR_REMISION` en la auditoría. No publica notificación: el médico remitente ve el nuevo estado y la observación en su lista de remisiones.

> `remision_finalizada` es adicional: no reemplaza el flujo obligatorio de R19 (`remision_aceptada`). Avisa al médico que la valoración especializada terminó para que pueda revisar el caso antes de cerrar el encuentro.

> **Encuentros finalizados:** las alertas y los contadores de `/pendientes` solo cuentan encuentros que no están finalizados. Al cerrar un encuentro dejan de aparecer.

## Eventos de IA y alertas críticas (R10, R20)

| Evento (`tipo`) | Quién lo dispara | A quién llega | Reacción |
|---|---|---|---|
| `reporte_ia_pendiente` | `POST /ia/analizar/{documento}` (médico, especialista o admin) | Médico responsable del encuentro; si no tiene, quien pidió el análisis; si fue un admin, todos los médicos | Sube `reportes_por_revisar` en `/pendientes`. Baja al aprobar o rechazar |
| `alerta_critica` | El mismo análisis, cuando el modelo marca alerta: P(crítico) ≥ 0,38 **o** red de seguridad (SpO2 < 88 % o PAS < 90 mmHg) | Los mismos destinatarios del reporte | Se crea la alerta `activa`, sube `alertas_activas` y aparece el aviso persistente hasta que se reconoce |
| `alerta_critica_escalada` | El sistema (hilo de la API), si la alerta sigue `activa` después de `ALERTA_ESCALAR_MINUTOS` (5 por defecto) | Todos los admin | La alerta queda abierta para cualquier médico. Se audita `ESCALAR_ALERTA` con origen `SISTEMA` |
| `alerta_reconocida` | `PATCH /alertas/{id}/reconocer` | El destinatario (o todos los médicos si no tenía), quien la reconoció y, si estaba escalada, los admin | El aviso persistente desaparece en todas sus pantallas abiertas; baja `alertas_activas` |
| `factura_ia_creada` | Un Médico/Especialista aprueba un reporte IA | Contable y Admin | Se crea automáticamente la factura en MongoDB, ligada por `reporte_id`; la vista de facturación se refresca sin recargar |
| `reasignacion_medica` | Admin desactiva un médico con encuentros activos (`DELETE /usuarios/{doc}?medico_reemplazo=`) | El médico de reemplazo | Los encuentros activos pasan al reemplazo; se audita `REASIGNAR_MEDICO` por cada encuentro |

Paciente y Contable no reciben ninguno de estos eventos, ni ven ni reconocen alertas (403).

### Escalamiento (R20.4)
- **Tiempo:** 5 minutos sin reconocimiento (variable `ALERTA_ESCALAR_MINUTOS`). En urgencias, un paciente crítico se valora en minutos (nivel 2 de ESI/KTAS: ≤ 10-15 min), así que el escalamiento debe ocurrir antes de ese plazo.
- **Mecanismo:** un hilo de la API revisa cada 30 s las alertas `activa` sin escalar y más antiguas que el umbral (`FOR UPDATE SKIP LOCKED`, para no chocar con un reconocimiento simultáneo).
- **A quién:** a todos los usuarios con rol Admin. Desde ese momento cualquier médico puede reconocerla, además del destinatario original.
- **Auditoría:** `ESCALAR_ALERTA`, con `origen = 'SISTEMA'` y sin usuario, porque nadie la ejecuta.

## Documentos relacionados

[`CONTABILIDAD.md`](CONTABILIDAD.md) (factura automática de IA) · [`MODELO.md`](MODELO.md) (análisis de IA y alertas) · [`LEYES.md`](LEYES.md) · [README](../README.md)


## R30 · Eventos del envío FHIR saliente (actualización R34)

El módulo `back/routers/remisiones_fhir_r30.py` publica un evento **después** de comprobar que el receptor devolvió un Bundle `transaction-response` con todas sus entradas confirmadas. **No debe confundir la recepción técnica con aceptación clínica.**

| Evento | Disparador | Destinatario | Datos mínimos | Persistencia / canal | Evidencia |
|---|---|---|---|---|---|
| `remision_fhir_confirmada` | `POST /fhir/remisiones-r30/{id}/enviar` retorna confirmación completa | Médico remitente | `remision_id`, `recursos` | `core.eventos.publicar`; notificación interna y SSE existente | Código de R30; remisión 14, HTTP 200, 11 recursos y estado “FHIR enviado” en interfaz |
| `remision_socio_aceptada` / `remision_socio_rechazada` | El socio responde con un `Task` `accepted`/`rejected` en `POST /fhir/remisiones-r30/respuesta` (token R31 con `task:write` + `x-nonce`), solo para remisiones que le enviamos | Médico remitente | `remision_id`, institución, estado, motivo y `paciente_id` | `core.eventos.publicar`: bandeja persistente + SSE; auditoría `RESPUESTA_SOCIO` con `origen = SOCIO` (cadena R28) | `back/routers/recepcion_externa.py`; `back/tests/test_devolucion_r30.py`; ida y vuelta en autoprueba local el 2026-11-18 |

## R30 · Eventos de entrada desde la institución socia (R19 ampliado)

El enunciado del proyecto final pide agregar al catálogo los eventos externos: remisión recibida de otro sistema, respuesta del socio y rechazo por validación. Los publica `back/routers/recepcion_externa.py`; todos quedan además en la auditoría con `origen = SOCIO` y `realizado_por` vacío (hecho causado por otra institución), dentro de la cadena de R28.

| Evento | Disparador | Destinatario | Datos mínimos | Auditoría | Evidencia |
|---|---|---|---|---|---|
| `remision_externa_recibida` | `POST /fhir/remisiones-r30/recibir` con un Bundle válido (token R31 con `bundle:write` + `x-nonce` nuevo) | Especialistas de la especialidad pedida; si no hay o no se reconoce, todos los especialistas y Admin | `remision_externa_id`, institución, `client_id`, especialidad, prioridad | `RECIBIR_REMISION_EXTERNA` | `back/tests/test_recepcion_externa_r30.py`; `docs/evidencias/R29_R30/prueba_recepcion.txt` (Bundle válido → 200) |
| `remision_externa_invalida` | El Bundle del socio se rechaza por validación (400, 413, 415 o 422 con `OperationOutcome`); no se guarda nada del Bundle | Admin | `client_id`, código HTTP y motivo | `RECHAZO_VALIDACION_EXTERNA` | `docs/evidencias/R29_R30/prueba_recepcion.txt` (9 rechazos esperados) |
| `remision_socio_aceptada` / `remision_socio_rechazada` | Respuesta del socio a una remisión nuestra (ver tabla anterior) | Médico remitente | `remision_id`, estado, motivo | `RESPUESTA_SOCIO` | `back/tests/test_devolucion_r30.py` |

Cuando nuestro especialista acepta o rechaza una remisión externa (`PATCH /remisiones-externas/{id}/aceptar` o `/rechazar`), se audita `ACEPTAR_REMISION_EXTERNA` o `RECHAZAR_REMISION_EXTERNA` y se envía al socio un `Task` con el estado (contrato en [`CONTRATO_R30.md`](CONTRATO_R30.md)). La bandeja de trabajo del especialista cuenta también las remisiones externas pendientes.

### Secuencia del evento R30

```mermaid
sequenceDiagram
  participant M as Médico / frontend
  participant API as FastAPI R30
  participant RX as Receptor piloto / HAPI
  participant DB as Neon / auditoría
  participant EV as Notificaciones y SSE
  M->>API: POST enviar remisión
  API->>API: Consent vigente, permisos y Bundle
  API->>RX: Bundle transaction
  alt confirmación completa
    RX-->>API: transaction-response
    API->>DB: r30_envios confirmado + REMITIR
    API->>EV: remision_fhir_confirmada
    EV-->>M: Aviso interno / SSE
  else rechazo o error
    RX-->>API: OperationOutcome / error
    API-->>M: Error sin confirmación
  end
```

**Comprobación en vivo (2026-11-21, R33):** las remisiones que llegaron de los dos equipos externos aparecieron como notificación al Admin y a la especialista de Cardiología, que pudo aceptarlas o rechazarlas. **Por confirmar con evidencia:** captura del evento SSE y del retorno visto en el sistema socio.
