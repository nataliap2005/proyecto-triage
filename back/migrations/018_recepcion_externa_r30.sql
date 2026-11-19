-- =====================================================================
-- 018 · RECEPCIÓN DE REMISIONES EXTERNAS (R29, R30, R33)
--
-- Una institución socio nos remite un paciente con un Bundle FHIR.
-- La remisión externa NO cabe en public.remisiones: esa tabla exige un
-- paciente, un encuentro y un médico remitente de NUESTRA base. Por eso
-- vive en su propia tabla, ligada a la institución que la envió (R31).
--
-- También deja lista la parte de datos de la devolución (paso siguiente):
--   - remisiones_externas guarda la respuesta de nuestro especialista;
--   - r30_envios guarda la respuesta del socio a lo que NOSOTROS enviamos.
--
-- Requiere 014 (r30_envios) y 015 (clientes_institucionales).
-- Es aditiva e idempotente: se puede correr dos veces sin error.
-- Uso: python scripts/ejecutar_migracion.py 018_recepcion_externa_r30.sql
-- =====================================================================

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Remisiones que llegan de otra institución
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.remisiones_externas (
    id_remision_externa  BIGSERIAL PRIMARY KEY,

    -- Quién la envió: la identidad sale del token institucional (R31),
    -- nunca del contenido del Bundle.
    socio_client_id      VARCHAR(64) NOT NULL
        REFERENCES public.clientes_institucionales(client_id),

    -- Referencias tal como llegaron del socio. Se necesitan para responderle
    -- con un Task que apunte a SU ServiceRequest (paso de devolución).
    sr_ref_origen        VARCHAR(255) NOT NULL,
    task_ref_origen      VARCHAR(255),
    paciente_ref_origen  VARCHAR(255) NOT NULL,

    -- Correspondencia referencia de origen -> id en nuestro HAPI FHIR.
    -- Los ids del socio se reescriben para que no pueda pisar recursos propios.
    ids_locales          JSONB NOT NULL,

    -- Especialidad pedida. NULL si no se pudo mapear al catálogo local:
    -- en ese caso la ven todos los especialistas y los Admin.
    id_especialidad      INTEGER REFERENCES public.especialidades(id_especialidad),
    especialidad_texto   VARCHAR(150),
    prioridad            VARCHAR(20),
    motivo               TEXT NOT NULL,

    -- Lo necesario para la bandeja: paciente, observaciones, reportes, consentimiento.
    resumen              JSONB NOT NULL DEFAULT '{}'::jsonb,
    recursos             INTEGER NOT NULL CHECK (recursos BETWEEN 2 AND 50),

    -- Ciclo de vida. Se llena en el paso de aceptación o rechazo.
    estado               VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente', 'aceptada', 'rechazada')),
    especialista_asignado BIGINT REFERENCES public.usuarios(numero_documento_usuario),
    observacion_respuesta TEXT,
    fecha_recepcion      TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_respuesta      TIMESTAMPTZ,

    -- Si la respuesta ya llegó al socio (el envío puede fallar y reintentarse).
    respuesta_enviada    BOOLEAN NOT NULL DEFAULT FALSE,
    respuesta_enviada_at TIMESTAMPTZ,

    -- Un mismo ServiceRequest del mismo socio solo se recibe una vez.
    CONSTRAINT uq_remision_externa_origen UNIQUE (socio_client_id, sr_ref_origen),
    -- Una remisión respondida siempre tiene quién y cuándo.
    CONSTRAINT chk_remision_externa_respuesta CHECK (
        estado = 'pendiente'
        OR (especialista_asignado IS NOT NULL AND fecha_respuesta IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_remisiones_externas_pendientes
    ON public.remisiones_externas(id_especialidad, fecha_recepcion DESC)
    WHERE estado = 'pendiente';

CREATE INDEX IF NOT EXISTS idx_remisiones_externas_asignado
    ON public.remisiones_externas(especialista_asignado, fecha_recepcion DESC);

-- ---------------------------------------------------------------------
-- 2. Respuesta del socio a las remisiones que NOSOTROS enviamos
--    Columnas nuevas: no se toca r30_envios.estado ('confirmado'), porque
--    el código de envío lo usa para impedir reenvíos.
-- ---------------------------------------------------------------------
ALTER TABLE public.r30_envios
    ADD COLUMN IF NOT EXISTS respuesta_socio VARCHAR(20),
    ADD COLUMN IF NOT EXISTS respuesta_motivo TEXT,
    ADD COLUMN IF NOT EXISTS respuesta_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS respuesta_client_id VARCHAR(64);

ALTER TABLE public.r30_envios
    DROP CONSTRAINT IF EXISTS chk_r30_envios_respuesta;
ALTER TABLE public.r30_envios
    ADD CONSTRAINT chk_r30_envios_respuesta
    CHECK (respuesta_socio IS NULL OR respuesta_socio IN ('aceptada', 'rechazada'));

-- ---------------------------------------------------------------------
-- 3. Acciones nuevas de auditoría (hechos con origen externo)
--    Se conserva TODA la lista vigente (012) y se agregan las nuevas.
--    Estas filas se auditan con origen = 'SOCIO' y realizado_por NULL,
--    lo que ya permite chk_auditoria_origen_usuario (006). La cadena de
--    hashes de R28 (016) las cubre igual que a las demás.
-- ---------------------------------------------------------------------
ALTER TABLE public.auditoria_cambios
    DROP CONSTRAINT IF EXISTS chk_auditoria_cambios_accion;
ALTER TABLE public.auditoria_cambios
    ADD CONSTRAINT chk_auditoria_cambios_accion
    CHECK (accion IN (
        'CREAR', 'EDITAR', 'ELIMINAR', 'RESTAURAR', 'DISPENSAR', 'ANULAR', 'FINALIZAR',
        'VINCULAR_CUENTA', 'REMITIR', 'ACEPTAR_REMISION', 'RECHAZAR_REMISION', 'RECIBIR_FHIR',
        'ANALIZAR_IA', 'APROBAR_REPORTE', 'RECHAZAR_REPORTE',
        'CREAR_ALERTA', 'RECONOCER_ALERTA', 'ESCALAR_ALERTA', 'REASIGNAR_MEDICO',
        'CONSULTA_RAG', 'INVOCAR_HERRAMIENTA',
        -- 018: interoperabilidad de entrada
        'RECIBIR_REMISION_EXTERNA',     -- llegó un Bundle válido del socio
        'RECHAZO_VALIDACION_EXTERNA',   -- el Bundle del socio fue rechazado (400/415/422)
        'ACEPTAR_REMISION_EXTERNA',     -- nuestro especialista la acepta
        'RECHAZAR_REMISION_EXTERNA',    -- nuestro especialista la rechaza
        'RESPUESTA_SOCIO'               -- el socio acepta o rechaza lo que enviamos
    ));

COMMIT;
