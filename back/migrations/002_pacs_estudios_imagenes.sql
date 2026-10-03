-- Migración para incorporar el almacenamiento relacional de estudios de imagen.
-- Esta tabla conecta cada estudio PACS con su paciente, encuentro y examen,
-- mientras Orthanc conserva los archivos DICOM y la base de datos almacena
-- únicamente los metadatos, identificadores y relaciones clínicas necesarias.
BEGIN;

CREATE TABLE IF NOT EXISTS estudios_imagenes (
    id_estudio BIGSERIAL PRIMARY KEY,

    id_paciente BIGINT NOT NULL,
    id_encuentro INTEGER NOT NULL,
    id_examen INTEGER NOT NULL,

    orthanc_study_id VARCHAR(100) NOT NULL UNIQUE,
    study_instance_uid VARCHAR(128) NOT NULL UNIQUE,

    modalidad VARCHAR(20),
    descripcion VARCHAR(250),
    fecha_estudio TIMESTAMPTZ,

    creado_por BIGINT NOT NULL
        REFERENCES usuarios(numero_documento_usuario),

    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,

    is_deleted BOOLEAN NOT NULL DEFAULT false,
    deleted_at TIMESTAMPTZ,
    deleted_by BIGINT
        REFERENCES usuarios(numero_documento_usuario),

    CONSTRAINT fk_estudio_encuentro_paciente
        FOREIGN KEY(id_encuentro,id_paciente)
        REFERENCES encuentros(id_encuentro,id_paciente),

    CONSTRAINT fk_estudio_examen_encuentro
        FOREIGN KEY(id_examen,id_encuentro)
        REFERENCES examenes(id_examen,id_encuentro)
);

CREATE INDEX IF NOT EXISTS idx_estudios_imagenes_paciente
    ON estudios_imagenes(id_paciente);

CREATE INDEX IF NOT EXISTS idx_estudios_imagenes_encuentro
    ON estudios_imagenes(id_encuentro);

CREATE INDEX IF NOT EXISTS idx_estudios_imagenes_examen
    ON estudios_imagenes(id_examen);

CREATE INDEX IF NOT EXISTS idx_estudios_imagenes_fecha
    ON estudios_imagenes(fecha_estudio);

COMMIT;
