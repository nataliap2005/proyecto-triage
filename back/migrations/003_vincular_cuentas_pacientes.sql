-- =====================================================================
-- MIGRACIÓN 003 - VINCULACIÓN DE CUENTAS DE PACIENTE
-- Sistema de apoyo al triage hospitalario
--
-- Objetivo:
-- 1. Permitir la acción VINCULAR_CUENTA en auditoria_cambios.
-- 2. Vincular pacientes clínicos existentes con cuentas de rol Paciente
--    cuando ambos comparten el mismo número de documento.
-- 3. No sobrescribir vínculos ya existentes ni tocar registros eliminados.
--
-- Esta migración es idempotente respecto al backfill: si no quedan pacientes
-- por vincular, el UPDATE no modifica filas.
-- =====================================================================

BEGIN;

-- El backend registra VINCULAR_CUENTA en auditoria_cambios cuando el enlace
-- ocurre desde POST/PUT /usuarios. El esquema original no incluía esa acción
-- en el CHECK, así que primero se actualiza la restricción.
DO $$
DECLARE
    nombre_constraint TEXT;
BEGIN
    SELECT c.conname
    INTO nombre_constraint
    FROM pg_constraint c
    WHERE c.conrelid = 'public.auditoria_cambios'::regclass
      AND c.contype = 'c'
      AND pg_get_constraintdef(c.oid) ILIKE '%accion%'
    LIMIT 1;

    IF nombre_constraint IS NOT NULL THEN
        EXECUTE format(
            'ALTER TABLE public.auditoria_cambios DROP CONSTRAINT %I',
            nombre_constraint
        );
    END IF;
END $$;

ALTER TABLE public.auditoria_cambios
    ADD CONSTRAINT chk_auditoria_cambios_accion
    CHECK (
        accion IN (
            'CREAR',
            'EDITAR',
            'ELIMINAR',
            'RESTAURAR',
            'DISPENSAR',
            'ANULAR',
            'FINALIZAR',
            'VINCULAR_CUENTA'
        )
    );

-- Backfill: paciente atendido antes de crear su cuenta.
UPDATE public.pacientes p
SET id_usuario = u.numero_documento_usuario,
    updated_at = now()
FROM public.usuarios u
JOIN public.roles r ON r.id_rol = u.id_rol
WHERE r.nombre = 'Paciente'
  AND u.is_deleted = FALSE
  AND u.estado = TRUE
  AND p.numero_documento_paciente = u.numero_documento_usuario
  AND p.id_usuario IS NULL
  AND p.is_deleted = FALSE;

COMMIT;
