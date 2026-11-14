-- R25. Ejecutar antes de desplegar la API con defensa contra prompt injection.
-- Identidad: cuenta autenticada. IP observada: solo contexto, NO base del bloqueo.
BEGIN;
CREATE TABLE IF NOT EXISTS public.r25_intentos_prompt (
    id_intento BIGSERIAL PRIMARY KEY,
    numero_documento_usuario BIGINT NOT NULL,
    ip_observada VARCHAR(64),
    ruta VARCHAR(96) NOT NULL,
    motivo VARCHAR(64) NOT NULL,
    huella_texto CHAR(64) NOT NULL,
    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_r25_intentos_usuario_fecha
    ON public.r25_intentos_prompt (numero_documento_usuario, fecha_hora DESC);
CREATE TABLE IF NOT EXISTS public.r25_bloqueos_prompt (
    numero_documento_usuario BIGINT PRIMARY KEY,
    bloqueado_hasta TIMESTAMPTZ NOT NULL,
    ultima_ip VARCHAR(64),
    motivo VARCHAR(64) NOT NULL
);
COMMIT;
