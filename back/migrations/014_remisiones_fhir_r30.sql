BEGIN;
-- El paciente autoriza o revoca el intercambio con un sistema socio específico.
CREATE TABLE IF NOT EXISTS public.r30_consentimientos (
    id_paciente BIGINT NOT NULL REFERENCES public.pacientes(numero_documento_paciente),
    socio VARCHAR(100) NOT NULL,
    vigente BOOLEAN NOT NULL DEFAULT FALSE,
    registrado_por BIGINT NOT NULL REFERENCES public.usuarios(numero_documento_usuario),
    actualizado_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expira_at TIMESTAMPTZ,
    PRIMARY KEY(id_paciente,socio)
);
CREATE TABLE IF NOT EXISTS public.r30_envios (
    id_envio BIGSERIAL PRIMARY KEY,
    id_remision BIGINT NOT NULL REFERENCES public.remisiones(id_remision),
    socio VARCHAR(100) NOT NULL,
    remitido_por BIGINT NOT NULL REFERENCES public.usuarios(numero_documento_usuario),
    estado VARCHAR(24) NOT NULL CHECK (estado IN ('confirmado')),
    recursos INTEGER NOT NULL CHECK(recursos BETWEEN 2 AND 30),
    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_r30_envios_remision ON public.r30_envios(id_remision,fecha_hora DESC);
COMMIT;
