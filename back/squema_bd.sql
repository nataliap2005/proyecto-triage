-- =====================================================================
-- SISTEMA DE APOYO AL TRIAGE HOSPITALARIO
-- ESQUEMA DE BASE DE DATOS - VERSIÓN CORREGIDA
-- =====================================================================

-- =====================================================================
-- ELIMINACIÓN EN ORDEN INVERSO DE DEPENDENCIAS
-- =====================================================================

DROP TABLE IF EXISTS factura_detalle CASCADE;
DROP TABLE IF EXISTS facturas CASCADE;
DROP TABLE IF EXISTS prescripciones CASCADE;
DROP TABLE IF EXISTS medicamentos CASCADE;
DROP TABLE IF EXISTS examenes CASCADE;
DROP TABLE IF EXISTS notas_clinicas CASCADE;
DROP TABLE IF EXISTS diagnosticos CASCADE;
DROP TABLE IF EXISTS observaciones CASCADE;
DROP TABLE IF EXISTS encuentros CASCADE;
DROP TABLE IF EXISTS reportes_previos CASCADE;
DROP TABLE IF EXISTS antecedentes CASCADE;
DROP TABLE IF EXISTS pacientes CASCADE;
DROP TABLE IF EXISTS auditoria_cambios CASCADE;
DROP TABLE IF EXISTS usuarios CASCADE;
DROP TABLE IF EXISTS roles CASCADE;


-- =====================================================================
-- 1. ROLES
-- =====================================================================

CREATE TABLE roles (
    id_rol SERIAL PRIMARY KEY,

    nombre VARCHAR(50) NOT NULL UNIQUE
        CHECK (
            nombre IN (
                'Admin',
                'Medico',
                'Administrativo',
                'Paciente'
            )
        ),

    descripcion TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    is_active BOOLEAN NOT NULL DEFAULT true
);


INSERT INTO roles(nombre,descripcion)
VALUES
    ('Admin','Administración general, gestión de usuarios y restauración de registros'),
    ('Medico','Consulta y gestión de la información clínica autorizada'),
    ('Administrativo','Gestión exclusiva de facturación y datos administrativos'),
    ('Paciente','Consulta de información propia y creación de reportes previos')
ON CONFLICT(nombre) DO NOTHING;


-- =====================================================================
-- 2. USUARIOS
-- Cuentas que pueden autenticarse en el sistema
-- =====================================================================

CREATE TABLE usuarios (
    numero_documento_usuario BIGINT PRIMARY KEY,

    id_rol INTEGER NOT NULL
        REFERENCES roles(id_rol),

    username VARCHAR(50) NOT NULL UNIQUE,

    password_hash TEXT NOT NULL,

    nombres VARCHAR(100) NOT NULL,

    apellidos VARCHAR(100) NOT NULL,

    email VARCHAR(150) UNIQUE,

    -- Se almacena como texto porque un teléfono no es una magnitud
    -- numérica y puede incluir +, prefijos, espacios o ceros iniciales.
    telefono VARCHAR(30),

    estado BOOLEAN NOT NULL DEFAULT true,

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario)
);


-- =====================================================================
-- 3. AUDITORÍA
-- Conserva trazabilidad de las operaciones
-- =====================================================================

CREATE TABLE auditoria_cambios (
    id_auditoria BIGSERIAL PRIMARY KEY,

    tabla_afectada VARCHAR(80) NOT NULL,

    registro_id VARCHAR(100) NOT NULL,

    accion VARCHAR(30) NOT NULL
        CHECK (
            accion IN (
                'CREAR',
                'EDITAR',
                'ELIMINAR',
                'RESTAURAR',
                'DISPENSAR',
                'ANULAR',
                'FINALIZAR'
            )
        ),

    datos_anteriores JSONB,

    datos_nuevos JSONB,

    realizado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- =====================================================================
-- 4. PACIENTES
-- Mapea posteriormente a FHIR Patient
-- =====================================================================

CREATE TABLE pacientes (
    numero_documento_paciente BIGINT PRIMARY KEY,

    -- Puede ser NULL porque un paciente puede existir sin cuenta digital.
    id_usuario BIGINT UNIQUE
        REFERENCES usuarios(numero_documento_usuario),

    tipo_documento VARCHAR(20) NOT NULL,

    nombres VARCHAR(100) NOT NULL,

    apellidos VARCHAR(100) NOT NULL,

    fecha_nacimiento DATE,

    -- Equivalente conceptual a Patient.gender de FHIR.
    -- Se utilizan los valores estandarizados.
    genero_fhir VARCHAR(20)
        CHECK (
            genero_fhir IN (
                'male',
                'female',
                'other',
                'unknown'
            )
        ),

    telefono VARCHAR(30),

    direccion VARCHAR(200),

    municipio_residencia VARCHAR(100),

    zona_residencia VARCHAR(20)
        CHECK (
            zona_residencia IN (
                'urbana',
                'rural_dispersa'
            )
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario)
);


-- =====================================================================
-- 5. ANTECEDENTES
-- Información previa de salud del paciente
-- =====================================================================

CREATE TABLE antecedentes (
    id_antecedente SERIAL PRIMARY KEY,

    id_paciente BIGINT NOT NULL
        REFERENCES pacientes(numero_documento_paciente),

    tipo VARCHAR(50) NOT NULL,

    codigo VARCHAR(50),

    descripcion TEXT NOT NULL,

    fecha_registro TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Permite saber quién creó el registro.
    -- Después la API podrá restringir edición/eliminación al autor.
    registrado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario)
);


-- =====================================================================
-- 6. REPORTES PREVIOS
-- Información capturada antes de la llegada al hospital
-- =====================================================================

CREATE TABLE reportes_previos (
    id_reporte SERIAL PRIMARY KEY,

    id_paciente BIGINT NOT NULL
        REFERENCES pacientes(numero_documento_paciente),

    fecha_hora_reporte TIMESTAMPTZ NOT NULL DEFAULT now(),

    sintoma_principal TEXT NOT NULL,

    inicio_sintomas TIMESTAMPTZ,

    evolucion TEXT,

    signos_alarma_presentes BOOLEAN NOT NULL DEFAULT false,

    descripcion_signos_alarma TEXT,

    ubicacion_aproximada VARCHAR(200),

    municipio_origen VARCHAR(100),

    distancia_aproximada_km DECIMAL(10,2)
        CHECK (
            distancia_aproximada_km IS NULL
            OR distancia_aproximada_km >= 0
        ),

    tiempo_desplazamiento_min INTEGER
        CHECK (
            tiempo_desplazamiento_min IS NULL
            OR tiempo_desplazamiento_min >= 0
        ),

    orientacion_inicial TEXT,

    registrado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    CONSTRAINT chk_reporte_signos_alarma
        CHECK (
            signos_alarma_presentes = false
            OR descripcion_signos_alarma IS NOT NULL
        )
);


-- =====================================================================
-- 7. ENCUENTROS
-- Episodio de atención
-- Mapea posteriormente a FHIR Encounter
-- =====================================================================

CREATE TABLE encuentros (
    id_encuentro SERIAL PRIMARY KEY,

    id_paciente BIGINT NOT NULL
        REFERENCES pacientes(numero_documento_paciente),

    fecha_hora_ingreso TIMESTAMPTZ NOT NULL DEFAULT now(),

    fecha_hora_fin TIMESTAMPTZ,

    tipo_encuentro VARCHAR(50) NOT NULL DEFAULT 'urgencias',

    servicio VARCHAR(50) NOT NULL DEFAULT 'URGENCIAS',

    estado VARCHAR(30) NOT NULL DEFAULT 'en_triage'
        CHECK (
            estado IN (
                'en_triage',
                'en_atencion',
                'en_observacion',
                'finalizado'
            )
        ),

    motivo_consulta TEXT NOT NULL,

    observaciones_generales TEXT,

    nivel_triage SMALLINT
        CHECK (
            nivel_triage IS NULL
            OR nivel_triage BETWEEN 1 AND 5
        ),

    fecha_hora_triage TIMESTAMPTZ,

    dolor_escala INTEGER
        CHECK (
            dolor_escala IS NULL
            OR dolor_escala BETWEEN 0 AND 10
        ),

    observaciones_triage TEXT,

    -- Profesional que realizó el triage.
    -- En Triage I puede quedar NULL inicialmente por atención inmediata.
    clasificado_por BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    clasificacion_automatica BOOLEAN NOT NULL DEFAULT false,

    -- Profesional responsable del episodio clínico.
    medico_responsable BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- Usuario que creó el encuentro.
    creado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- Permite validar conjuntamente paciente + encuentro.
    CONSTRAINT uq_encuentro_paciente
        UNIQUE(id_encuentro,id_paciente),

    CONSTRAINT chk_fechas_encuentro
        CHECK (
            fecha_hora_fin IS NULL
            OR fecha_hora_fin >= fecha_hora_ingreso
        )
);


-- =====================================================================
-- 8. OBSERVACIONES
-- Signos vitales y otras mediciones
-- Mapea posteriormente a FHIR Observation
-- =====================================================================

CREATE TABLE observaciones (
    id_observacion SERIAL PRIMARY KEY,

    id_encuentro INTEGER NOT NULL
        REFERENCES encuentros(id_encuentro),

    tipo_observacion VARCHAR(100) NOT NULL,

    codigo_loinc VARCHAR(30),

    nombre VARCHAR(150) NOT NULL,

    valor_numerico DECIMAL(12,4),

    valor_texto TEXT,

    unidad VARCHAR(30),

    fecha_hora_observacion TIMESTAMPTZ NOT NULL DEFAULT now(),

    registrado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- Una observación debe tener un valor numérico O textual,
    -- pero no ambos simultáneamente.
    CONSTRAINT chk_valor_observacion
        CHECK (
            (
                valor_numerico IS NOT NULL
                AND valor_texto IS NULL
            )
            OR
            (
                valor_numerico IS NULL
                AND valor_texto IS NOT NULL
            )
        )
);


-- =====================================================================
-- 9. DIAGNÓSTICOS
-- Diagnósticos generados durante un encuentro
-- Mapea posteriormente a FHIR Condition
-- =====================================================================

CREATE TABLE diagnosticos (
    id_diagnostico SERIAL PRIMARY KEY,

    id_encuentro INTEGER NOT NULL
        REFERENCES encuentros(id_encuentro),

    codigo_cie10 VARCHAR(30),

    descripcion VARCHAR(250) NOT NULL,

    tipo VARCHAR(30) NOT NULL DEFAULT 'principal'
        CHECK (
            tipo IN (
                'principal',
                'secundario'
            )
        ),

    estado_clinico VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (
            estado_clinico IN (
                'active',
                'recurrence',
                'relapse',
                'inactive',
                'remission',
                'resolved'
            )
        ),

    fecha_diagnostico TIMESTAMPTZ NOT NULL DEFAULT now(),

    registrado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario)
);


-- =====================================================================
-- 10. NOTAS CLÍNICAS
-- Evoluciones, valoraciones y notas realizadas durante el encuentro
-- =====================================================================

CREATE TABLE notas_clinicas (
    id_nota SERIAL PRIMARY KEY,

    id_encuentro INTEGER NOT NULL
        REFERENCES encuentros(id_encuentro),

    tipo_nota VARCHAR(50) NOT NULL
        CHECK (
            tipo_nota IN (
                'evolucion',
                'valoracion',
                'nota_clinica'
            )
        ),

    contenido TEXT NOT NULL,

    fecha_hora TIMESTAMPTZ NOT NULL DEFAULT now(),

    registrado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario)
);


-- =====================================================================
-- 11. EXÁMENES
-- Exámenes solicitados durante un encuentro clínico
-- Preparado para interoperabilidad mediante FHIR
-- ServiceRequest / DiagnosticReport
-- =====================================================================

CREATE TABLE examenes (
    id_examen SERIAL PRIMARY KEY,

    id_encuentro INTEGER NOT NULL
        REFERENCES encuentros(id_encuentro),

    codigo_loinc VARCHAR(30),

    nombre VARCHAR(150) NOT NULL,

    categoria VARCHAR(100),

    estado VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (
            estado IN (
                'draft',
                'active',
                'on-hold',
                'revoked',
                'completed',
                'entered-in-error',
                'unknown'
            )
        ),

    resultado TEXT,

    conclusion TEXT,

    fecha_solicitud TIMESTAMPTZ NOT NULL DEFAULT now(),

    fecha_resultado TIMESTAMPTZ,

    solicitado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    registrado_resultado_por BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    CONSTRAINT uq_examen_encuentro
        UNIQUE(id_examen,id_encuentro),

    CONSTRAINT chk_fecha_resultado_examen
        CHECK (
            fecha_resultado IS NULL
            OR fecha_resultado >= fecha_solicitud
        )
);


-- =====================================================================
-- 12. MEDICAMENTOS
-- Catálogo de medicamentos
-- Mapea posteriormente a FHIR Medication
-- =====================================================================

CREATE TABLE medicamentos (
    codigo_cum VARCHAR(50) PRIMARY KEY,

    nombre VARCHAR(150) NOT NULL,

    principio_activo VARCHAR(150),

    concentracion VARCHAR(100),

    forma_farmaceutica VARCHAR(100),

    registro_sanitario VARCHAR(100),

    estado_cum VARCHAR(30),

    precio_unitario DECIMAL(12,2) NOT NULL
        CHECK (
            precio_unitario >= 0
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false
);


-- =====================================================================
-- 13. PRESCRIPCIONES
-- Orden de medicamento generada durante un encuentro
-- Mapea posteriormente a FHIR MedicationRequest
-- =====================================================================

CREATE TABLE prescripciones (
    id_prescripcion SERIAL PRIMARY KEY,

    id_encuentro INTEGER NOT NULL
        REFERENCES encuentros(id_encuentro),

    codigo_cum VARCHAR(50) NOT NULL
        REFERENCES medicamentos(codigo_cum),

    dosis VARCHAR(100),

    frecuencia VARCHAR(100),

    via_administracion VARCHAR(50),

    cantidad INTEGER NOT NULL
        CHECK (
            cantidad > 0
        ),

    prescrito_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    fecha_prescripcion TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Estado operativo utilizado por el sistema.
    -- La transformación FHIR correspondiente se realizará en FastAPI.
    estado VARCHAR(30) NOT NULL DEFAULT 'activa'
        CHECK (
            estado IN (
                'activa',
                'dispensada',
                'anulada'
            )
        ),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- Permite que factura_detalle compruebe que una prescripción
    -- pertenece exactamente al mismo encuentro de la factura.
    CONSTRAINT uq_prescripcion_encuentro
        UNIQUE(id_prescripcion,id_encuentro)
);


-- =====================================================================
-- 14. FACTURAS
-- La factura pertenece explícitamente al paciente y al encuentro.
-- La FK compuesta impide que ambos IDs correspondan a personas distintas.
-- =====================================================================

CREATE TABLE facturas (
    id_factura SERIAL PRIMARY KEY,

    id_paciente BIGINT NOT NULL,

    id_encuentro INTEGER NOT NULL,

    numero_factura VARCHAR(50) NOT NULL UNIQUE,

    fecha_emision TIMESTAMPTZ NOT NULL DEFAULT now(),

    concepto TEXT,

    total DECIMAL(12,2) NOT NULL DEFAULT 0
        CHECK (
            total >= 0
        ),

    estado VARCHAR(30) NOT NULL DEFAULT 'pendiente'
        CHECK (
            estado IN (
                'pendiente',
                'pagada',
                'anulada'
            )
        ),

    creado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- Esta relación garantiza que el paciente de la factura
    -- sea exactamente el paciente propietario del encuentro.
    CONSTRAINT fk_factura_encuentro_paciente
        FOREIGN KEY(id_encuentro,id_paciente)
        REFERENCES encuentros(id_encuentro,id_paciente),

    -- Necesario para relacionar factura_detalle con el mismo encuentro.
    CONSTRAINT uq_factura_encuentro
        UNIQUE(id_factura,id_encuentro)
);


-- =====================================================================
-- 15. FACTURA DETALLE
-- Cada línea queda asociada a la misma factura y encuentro.
-- Opcionalmente puede provenir de una prescripción o un examen.
-- =====================================================================

CREATE TABLE factura_detalle (
    id_detalle SERIAL PRIMARY KEY,

    id_factura INTEGER NOT NULL,

    id_encuentro INTEGER NOT NULL,

    id_prescripcion INTEGER,

    id_examen INTEGER,

    concepto VARCHAR(200) NOT NULL,

    cantidad INTEGER NOT NULL DEFAULT 1
        CHECK (
            cantidad > 0
        ),

    valor_unitario DECIMAL(12,2) NOT NULL
        CHECK (
            valor_unitario >= 0
        ),

    valor_total DECIMAL(12,2) NOT NULL
        CHECK (
            valor_total >= 0
        ),

    creado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,

    deleted_at TIMESTAMPTZ,

    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    -- La línea debe pertenecer al mismo encuentro de la factura.
    CONSTRAINT fk_detalle_factura_encuentro
        FOREIGN KEY(id_factura,id_encuentro)
        REFERENCES facturas(id_factura,id_encuentro),

    -- Si el detalle corresponde a una prescripción,
    -- esta debe pertenecer al mismo encuentro.
    CONSTRAINT fk_detalle_prescripcion_encuentro
        FOREIGN KEY(id_prescripcion,id_encuentro)
        REFERENCES prescripciones(id_prescripcion,id_encuentro),

    -- Si el detalle corresponde a un examen,
    -- este también debe pertenecer al mismo encuentro.
    CONSTRAINT fk_detalle_examen_encuentro
        FOREIGN KEY(id_examen,id_encuentro)
        REFERENCES examenes(id_examen,id_encuentro),

    -- Una línea puede representar una prescripción, un examen
    -- o un servicio adicional, pero no prescripción y examen a la vez.
    CONSTRAINT chk_origen_detalle
        CHECK (
            NOT (
                id_prescripcion IS NOT NULL
                AND id_examen IS NOT NULL
            )
        )
);


-- =====================================================================
-- ÍNDICES
-- =====================================================================

-- USUARIOS
CREATE INDEX idx_usuarios_id_rol
    ON usuarios(id_rol);


-- PACIENTES
CREATE INDEX idx_pacientes_id_usuario
    ON pacientes(id_usuario);


-- ANTECEDENTES
CREATE INDEX idx_antecedentes_id_paciente
    ON antecedentes(id_paciente);

CREATE INDEX idx_antecedentes_registrado_por
    ON antecedentes(registrado_por);


-- REPORTES PREVIOS
CREATE INDEX idx_reportes_previos_paciente
    ON reportes_previos(id_paciente);

CREATE INDEX idx_reportes_previos_registrado_por
    ON reportes_previos(registrado_por);


-- ENCUENTROS
CREATE INDEX idx_encuentros_id_paciente
    ON encuentros(id_paciente);

CREATE INDEX idx_encuentros_medico_responsable
    ON encuentros(medico_responsable);

CREATE INDEX idx_encuentros_creado_por
    ON encuentros(creado_por);

CREATE INDEX idx_encuentros_clasificado_por
    ON encuentros(clasificado_por);


-- Evita dos encuentros activos simultáneos para el mismo paciente.
CREATE UNIQUE INDEX uq_encuentro_activo_paciente
    ON encuentros(id_paciente)
    WHERE is_deleted=false
      AND estado<>'finalizado';


-- OBSERVACIONES
CREATE INDEX idx_observaciones_id_encuentro
    ON observaciones(id_encuentro);

CREATE INDEX idx_observaciones_registrado_por
    ON observaciones(registrado_por);

CREATE INDEX idx_observaciones_codigo_loinc
    ON observaciones(codigo_loinc);


-- DIAGNÓSTICOS
CREATE INDEX idx_diagnosticos_encuentro
    ON diagnosticos(id_encuentro);

CREATE INDEX idx_diagnosticos_registrado_por
    ON diagnosticos(registrado_por);

CREATE INDEX idx_diagnosticos_cie10
    ON diagnosticos(codigo_cie10);


-- NOTAS CLÍNICAS
CREATE INDEX idx_notas_clinicas_encuentro
    ON notas_clinicas(id_encuentro);

CREATE INDEX idx_notas_clinicas_registrado_por
    ON notas_clinicas(registrado_por);


-- EXÁMENES
CREATE INDEX idx_examenes_encuentro
    ON examenes(id_encuentro);

CREATE INDEX idx_examenes_solicitado_por
    ON examenes(solicitado_por);

CREATE INDEX idx_examenes_codigo_loinc
    ON examenes(codigo_loinc);


-- PRESCRIPCIONES
CREATE INDEX idx_prescripciones_encuentro
    ON prescripciones(id_encuentro);

CREATE INDEX idx_prescripciones_medicamento
    ON prescripciones(codigo_cum);

CREATE INDEX idx_prescripciones_prescrito_por
    ON prescripciones(prescrito_por);


-- Evita dos prescripciones activas del mismo medicamento
-- para el mismo encuentro.
CREATE UNIQUE INDEX uq_prescripcion_activa_medicamento
    ON prescripciones(id_encuentro,codigo_cum)
    WHERE is_deleted=false
      AND estado='activa';


-- FACTURAS
CREATE INDEX idx_facturas_id_paciente
    ON facturas(id_paciente);

CREATE INDEX idx_facturas_id_encuentro
    ON facturas(id_encuentro);

CREATE INDEX idx_facturas_creado_por
    ON facturas(creado_por);


-- Un encuentro solamente puede tener una factura activa.
CREATE UNIQUE INDEX uq_factura_activa_encuentro
    ON facturas(id_encuentro)
    WHERE is_deleted=false
      AND estado<>'anulada';


-- FACTURA DETALLE
CREATE INDEX idx_factura_detalle_id_factura
    ON factura_detalle(id_factura);

CREATE INDEX idx_factura_detalle_encuentro
    ON factura_detalle(id_encuentro);

CREATE INDEX idx_factura_detalle_prescripcion
    ON factura_detalle(id_prescripcion);

CREATE INDEX idx_factura_detalle_examen
    ON factura_detalle(id_examen);


-- AUDITORÍA
CREATE INDEX idx_auditoria_registro
    ON auditoria_cambios(tabla_afectada,registro_id);

CREATE INDEX idx_auditoria_usuario
    ON auditoria_cambios(realizado_por);

CREATE INDEX idx_auditoria_fecha
    ON auditoria_cambios(fecha_hora);