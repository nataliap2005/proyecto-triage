-- R24: incorporar invocaciones de herramientas al CHECK de auditoría.
-- Ejecutar DESPUÉS de 011, mediante scripts/ejecutar_migracion.py.
BEGIN;
ALTER TABLE auditoria_cambios DROP CONSTRAINT IF EXISTS chk_auditoria_cambios_accion;
ALTER TABLE auditoria_cambios DROP CONSTRAINT IF EXISTS auditoria_cambios_accion_check;
ALTER TABLE auditoria_cambios ADD CONSTRAINT chk_auditoria_cambios_accion CHECK (accion IN (
    'CREAR', 'EDITAR', 'ELIMINAR', 'RESTAURAR', 'DISPENSAR', 'ANULAR', 'FINALIZAR',
    'VINCULAR_CUENTA', 'REMITIR', 'ACEPTAR_REMISION', 'RECHAZAR_REMISION', 'RECIBIR_FHIR',
    'ANALIZAR_IA', 'APROBAR_REPORTE', 'RECHAZAR_REPORTE',
    'CREAR_ALERTA', 'RECONOCER_ALERTA', 'ESCALAR_ALERTA', 'REASIGNAR_MEDICO',
    'CONSULTA_RAG', 'INVOCAR_HERRAMIENTA'
));
COMMIT;
