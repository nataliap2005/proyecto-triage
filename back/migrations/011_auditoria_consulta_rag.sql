-- =====================================================================
-- 011 · Acción de auditoría CONSULTA_RAG (Semana 12)
-- POST /rag/preguntar registra cada consulta al asistente: quién preguntó,
-- sobre qué paciente, con qué método, en qué modo respondió y qué
-- fragmentos usó como fuente. Sin esta acción el CHECK la rechaza.
-- Conserva todas las acciones de la 009. Idempotente.
-- Aplicar desde back/: python scripts/ejecutar_migracion.py 011_auditoria_consulta_rag.sql
-- =====================================================================
BEGIN;

ALTER TABLE auditoria_cambios
    DROP CONSTRAINT IF EXISTS chk_auditoria_cambios_accion;
ALTER TABLE auditoria_cambios
    DROP CONSTRAINT IF EXISTS auditoria_cambios_accion_check;

ALTER TABLE auditoria_cambios
    ADD CONSTRAINT chk_auditoria_cambios_accion
    CHECK (accion IN (
        'CREAR', 'EDITAR', 'ELIMINAR', 'RESTAURAR', 'DISPENSAR', 'ANULAR', 'FINALIZAR',
        'VINCULAR_CUENTA', 'REMITIR', 'ACEPTAR_REMISION', 'RECHAZAR_REMISION', 'RECIBIR_FHIR',
        'ANALIZAR_IA', 'APROBAR_REPORTE', 'RECHAZAR_REPORTE',
        'CREAR_ALERTA', 'RECONOCER_ALERTA', 'ESCALAR_ALERTA',
        'REASIGNAR_MEDICO',
        'CONSULTA_RAG'
    ));

COMMIT;
