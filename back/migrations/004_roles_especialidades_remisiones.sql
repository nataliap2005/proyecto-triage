-- Migración 004: roles del Corte 2, especialidades y remisiones.
-- 1) Renombra Administrativo a Contable.
-- 2) Agrega el rol Especialista.
-- 3) Crea catálogo de especialidades y relación usuario-especialidad.
-- 4) Crea remisiones entre Médico y Especialista.
-- 5) Amplía auditoría para registrar el flujo de remisión.

BEGIN;

-- Actualizar el CHECK de roles antes de cambiar/insertar nombres.
ALTER TABLE public.roles
DROP CONSTRAINT IF EXISTS roles_nombre_check;

UPDATE public.roles
SET nombre='Contable',
    descripcion='Gestión de procesos contables y facturación, sin acceso a datos clínicos'
WHERE nombre='Administrativo';

INSERT INTO public.roles(nombre, descripcion, is_active)
VALUES (
    'Especialista',
    'Recibe remisiones y atiende únicamente a los pacientes que le fueron remitidos',
    TRUE
)
ON CONFLICT(nombre) DO UPDATE
SET descripcion=EXCLUDED.descripcion,
    is_active=TRUE;

ALTER TABLE public.roles
ADD CONSTRAINT roles_nombre_check
CHECK (nombre IN ('Admin','Medico','Especialista','Paciente','Contable'));

-- Catálogo de especialidades.
CREATE TABLE IF NOT EXISTS public.especialidades (
    id_especialidad INTEGER PRIMARY KEY,
    nombre VARCHAR(120) NOT NULL UNIQUE,
    descripcion TEXT,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO public.especialidades (id_especialidad, nombre, descripcion, activo) VALUES
(1, 'Medicina de Urgencias y Emergencias', 'Atención inicial, reanimación y clasificación de riesgo vital inmediato', TRUE),
(2, 'Medicina General', 'Valoración inicial y atención de patologías agudas de baja y mediana complejidad', TRUE),
(3, 'Medicina Interna', 'Evaluación de patologías médicas complejas no quirúrgicas y descompensaciones crónicas', TRUE),
(4, 'Pediatría', 'Atención de urgencias en lactantes, niños y adolescentes', TRUE),
(5, 'Ginecología y Obstetricia', 'Atención de emergencias gestacionales, parto y urgencias ginecológicas', TRUE),
(6, 'Cirugía General', 'Valoración de abdomen agudo y patologías de resolución quirúrgica urgente', TRUE),
(7, 'Traumatología y Ortopedia', 'Atención de fracturas, luxaciones, heridas complejas y politraumatismos', TRUE),
(8, 'Cardiología', 'Manejo de dolor torácico, síndrome coronario agudo y arritmias severas', TRUE),
(9, 'Neurología', 'Evaluación de eventos cerebrovasculares agudos (Código ACV) y déficits neurológicos', TRUE),
(10, 'Psiquiatría', 'Atención de crisis de salud mental, agitación psicomotora y riesgo de autolesión', TRUE),
(11, 'Medicina Intensiva', 'Manejo e ingreso de pacientes en estado crítico que requieren soporte vital en UCI', TRUE),
(12, 'Toxicología Clínica', 'Atención de intoxicaciones agudas, sobredosis de sustancias o envenenamientos', TRUE)
ON CONFLICT (id_especialidad) DO UPDATE
SET nombre=EXCLUDED.nombre,
    descripcion=EXCLUDED.descripcion,
    activo=EXCLUDED.activo;

CREATE TABLE IF NOT EXISTS public.usuario_especialidades (
    numero_documento_usuario BIGINT NOT NULL
        REFERENCES public.usuarios(numero_documento_usuario) ON DELETE CASCADE,
    id_especialidad INTEGER NOT NULL
        REFERENCES public.especialidades(id_especialidad),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY(numero_documento_usuario, id_especialidad)
);

CREATE INDEX IF NOT EXISTS idx_usuario_especialidades_especialidad
ON public.usuario_especialidades(id_especialidad);

-- Remisión vinculada a paciente, encuentro, médico remitente, especialista y especialidad.
CREATE TABLE IF NOT EXISTS public.remisiones (
    id_remision BIGSERIAL PRIMARY KEY,
    id_paciente BIGINT NOT NULL
        REFERENCES public.pacientes(numero_documento_paciente),
    id_encuentro INTEGER NOT NULL
        REFERENCES public.encuentros(id_encuentro),
    medico_remitente BIGINT NOT NULL
        REFERENCES public.usuarios(numero_documento_usuario),
    especialista_destino BIGINT NOT NULL
        REFERENCES public.usuarios(numero_documento_usuario),
    id_especialidad INTEGER NOT NULL
        REFERENCES public.especialidades(id_especialidad),
    motivo TEXT NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('pendiente','aceptada','rechazada','finalizada')),
    fecha_remision TIMESTAMPTZ NOT NULL DEFAULT now(),
    fecha_respuesta TIMESTAMPTZ,
    observacion_respuesta TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    deleted_at TIMESTAMPTZ,
    deleted_by BIGINT REFERENCES public.usuarios(numero_documento_usuario),
    CONSTRAINT fk_remision_encuentro_paciente
        FOREIGN KEY(id_encuentro,id_paciente)
        REFERENCES public.encuentros(id_encuentro,id_paciente)
);

CREATE INDEX IF NOT EXISTS idx_remisiones_especialista
ON public.remisiones(especialista_destino, estado)
WHERE is_deleted=FALSE;

CREATE INDEX IF NOT EXISTS idx_remisiones_medico
ON public.remisiones(medico_remitente, estado)
WHERE is_deleted=FALSE;

CREATE INDEX IF NOT EXISTS idx_remisiones_paciente
ON public.remisiones(id_paciente)
WHERE is_deleted=FALSE;

-- Evita duplicar una remisión activa del mismo encuentro al mismo especialista.
CREATE UNIQUE INDEX IF NOT EXISTS uq_remision_activa_encuentro_especialista
ON public.remisiones(id_encuentro, especialista_destino)
WHERE is_deleted=FALSE AND estado IN ('pendiente','aceptada');

-- Acciones nuevas en auditoría.
ALTER TABLE public.auditoria_cambios
DROP CONSTRAINT IF EXISTS chk_auditoria_cambios_accion;

ALTER TABLE public.auditoria_cambios
ADD CONSTRAINT chk_auditoria_cambios_accion
CHECK (accion IN (
    'CREAR','EDITAR','ELIMINAR','RESTAURAR','DISPENSAR','ANULAR','FINALIZAR',
    'VINCULAR_CUENTA','REMITIR','ACEPTAR_REMISION','RECHAZAR_REMISION'
));

COMMIT;
