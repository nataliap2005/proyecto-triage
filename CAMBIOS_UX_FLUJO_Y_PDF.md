# Cambios UX, flujo clínico y PDF

- Historia clínica PDF ampliada con signos legibles, diagnósticos, notas, exámenes, imágenes PACS, prescripciones, remisiones y solo reportes IA aprobados.
- Cada PDF descargado también se archiva en `historias_clinicas/` mediante un volumen del servicio API; los PDF están ignorados por Git.
- Cola de Urgencias muestra médico responsable y evita que otro médico abra una atención ya asignada.
- El especialista puede **Finalizar valoración** de una remisión aceptada; el médico remitente recibe notificación SSE `remision_finalizada`.
- Todas las tablas del SPA reciben buscador y filtros automáticos por columnas relevantes (Rol, Estado, Origen, Servicio, Acción, Tabla, Especialidad, Triage).
- Contable/Admin pueden cambiar el estado de una factura entre `pendiente`, `pagada` y `anulada`; el cambio queda auditado.

## Compatibilidad con requisitos

No se cambió el disparador obligatorio de R19: la factura IA sigue creándose automáticamente al aprobar el reporte. R08 conserva el flujo remitir → aceptar; finalizar valoración es una mejora adicional. R11 conserva el requisito de mostrar únicamente reportes IA aprobados.
