-- Bandeja persistente de notificaciones y base del canal en tiempo real.
CREATE TABLE IF NOT EXISTS notificaciones(
    id_notificacion          BIGSERIAL PRIMARY KEY,
    numero_documento_usuario BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),
    tipo                     VARCHAR(60)  NOT NULL,
    mensaje                  TEXT         NOT NULL,
    paciente_id             BIGINT
        REFERENCES pacientes(numero_documento_paciente),
    datos                    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    leida                    BOOLEAN      NOT NULL DEFAULT FALSE,
    fecha                    TIMESTAMPTZ  NOT NULL DEFAULT now(),
    leida_at                 TIMESTAMPTZ  
);

CREATE INDEX IF NOT EXISTS idx_notificaciones_usuario_fecha
    ON notificaciones(numero_documento_usuario, fecha DESC);

CREATE INDEX IF NOT EXISTS idx_notificaciones_no_leidas
    ON notificaciones(numero_documento_usuario)
    WHERE leida = false;