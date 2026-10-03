-- =====================================================================
-- MIGRACIÓN 001 - SEMANA 8: SEGURIDAD DE AUTENTICACIÓN
-- Sistema de apoyo al triage hospitalario
--
-- Objetivo:
-- 1. Contar intentos fallidos de inicio de sesión.
-- 2. Bloquear la cuenta al alcanzar 3 intentos fallidos.
-- 3. Guardar la fecha del bloqueo.
-- 4. Registrar eventos de autenticación en auth_log.
--
-- Esta migración modifica la BD EXISTENTE sin eliminar datos.
-- No ejecutar squema_bd.sql sobre la BD productiva para aplicar este cambio.
-- =====================================================================

BEGIN;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS intentos_fallidos SMALLINT NOT NULL DEFAULT 0;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS bloqueado BOOLEAN NOT NULL DEFAULT false;

ALTER TABLE usuarios
    ADD COLUMN IF NOT EXISTS bloqueado_at TIMESTAMPTZ;

-- Agrega la validación de intentos_fallidos solo si todavía no existe.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname='chk_usuarios_intentos_fallidos'
    ) THEN
        ALTER TABLE usuarios
            ADD CONSTRAINT chk_usuarios_intentos_fallidos
            CHECK (intentos_fallidos >= 0);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS auth_log (
    id_auth_log BIGSERIAL PRIMARY KEY,

    numero_documento_usuario BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    username_intentado VARCHAR(50) NOT NULL,

    evento VARCHAR(30) NOT NULL
        CHECK (
            evento IN (
                'LOGIN_OK',
                'LOGIN_FALLIDO',
                'USUARIO_BLOQUEADO',
                'USUARIO_DESBLOQUEADO'
            )
        ),

    exitoso BOOLEAN NOT NULL,

    detalle TEXT,

    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_auth_log_usuario
    ON auth_log(numero_documento_usuario);

CREATE INDEX IF NOT EXISTS idx_auth_log_fecha
    ON auth_log(fecha_hora);

CREATE INDEX IF NOT EXISTS idx_auth_log_evento
    ON auth_log(evento);

COMMIT;

-- Verificación opcional después de ejecutar la migración:
-- SELECT column_name,data_type,column_default
-- FROM information_schema.columns
-- WHERE table_name='usuarios'
--   AND column_name IN ('intentos_fallidos','bloqueado','bloqueado_at')
-- ORDER BY ordinal_position;
--
-- SELECT to_regclass('public.auth_log') AS tabla_auth_log;
