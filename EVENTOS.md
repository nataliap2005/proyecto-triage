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

## Eventos

| Evento (`tipo`) | Quién lo dispara | A quién llega | Reacción | Datos extra |
|---|---|---|---|---|
| `cuenta_bloqueada` | 3.er intento fallido de login (`auth/service.py`) | Todos los Admin activos | Aviso en bandeja y en vivo; el Admin puede desbloquear | `usuario_bloqueado`, `documento_usuario` |
| `remision_recibida` | Médico crea una remisión (`POST /remisiones`) | El especialista destino | Aviso; sube `remisiones_recibidas` | `remision_id`, `id_encuentro`, `especialidad`, `medico_remitente` |
| `remision_aceptada` | Especialista acepta (`PATCH /remisiones/{id}/aceptar`) | El médico remitente | Aviso; baja `remisiones_recibidas` del especialista | `remision_id`, `especialidad`, `observacion` |
| `remision_rechazada` | Especialista rechaza (`PATCH /remisiones/{id}/rechazar`) | El médico remitente | Aviso; baja `remisiones_recibidas` del especialista | `remision_id`, `especialidad`, `observacion` |

## Pendiente de documentar

- Aprobación de reporte IA → factura en MongoDB con `reporte_id` (R10, R19).
- Alerta crítica y su escalamiento (R20).
- Nueva `Observation` en FHIR → aviso al médico responsable (R21).