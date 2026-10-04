-- =====================================================================
-- 006 · AUDITORÍA CON ORIGEN (R21)
-- Permite auditar hechos que no hizo un usuario sino un sistema externo
-- (HAPI FHIR). Idempotente.
-- =====================================================================

BEGIN;

-- De dónde viene el hecho auditado. Las filas existentes quedan como 'API'.
ALTER TABLE auditoria_cambios
    ADD COLUMN IF NOT EXISTS origen VARCHAR(30) NOT NULL DEFAULT 'API';

-- Un sistema externo no es un usuario: realizado_por puede quedar vacío...
ALTER TABLE auditoria_cambios
    ALTER COLUMN realizado_por DROP NOT NULL;

-- ...pero SOLO si el origen no es la API. Una acción hecha desde la API
-- siempre debe tener un usuario responsable.
ALTER TABLE auditoria_cambios
    DROP CONSTRAINT IF EXISTS chk_auditoria_origen_usuario;
ALTER TABLE auditoria_cambios
    ADD CONSTRAINT chk_auditoria_origen_usuario
    CHECK (realizado_por IS NOT NULL OR origen <> 'API');

-- Nueva acción. Se eliminan ambos nombres posibles del CHECK: el original
-- del esquema (sin nombre explícito) y el de la migración 004.
ALTER TABLE auditoria_cambios
    DROP CONSTRAINT IF EXISTS auditoria_cambios_accion_check;
ALTER TABLE auditoria_cambios
    DROP CONSTRAINT IF EXISTS chk_auditoria_cambios_accion;
ALTER TABLE auditoria_cambios
    ADD CONSTRAINT chk_auditoria_cambios_accion
    CHECK (accion IN (
        'CREAR','EDITAR','ELIMINAR','RESTAURAR','DISPENSAR','ANULAR','FINALIZAR',
        'VINCULAR_CUENTA','REMITIR','ACEPTAR_REMISION','RECHAZAR_REMISION',
        'RECIBIR_FHIR'
    ));

COMMIT;