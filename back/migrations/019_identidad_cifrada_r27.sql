-- =====================================================================
-- 019 · R27: bóveda del documento de identidad cifrado
--
-- El documento deja de usarse como identificador en las tablas. En su lugar
-- cada persona tiene un número interno de 16 dígitos (HMAC del documento, ver
-- back/core/identidad.py) y el documento real queda SOLO aquí, cifrado con
-- AES-256-GCM (formato v1.k1.<nonce>.<cifrado>, dato asociado "documento").
--
-- Esta tabla la crea también scripts/migrar_documentos_r27.py, que es el que
-- cambia los documentos por números internos en todas las tablas (necesita la
-- llave, por eso no puede hacerse en SQL puro). Idempotente.
-- =====================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS public.identidades (
    id_interno         BIGINT PRIMARY KEY
        CHECK (id_interno >= 1000000000000000 AND id_interno < 9000000000000000),
    documento_cifrado  TEXT NOT NULL CHECK (documento_cifrado LIKE 'v1.%'),
    creado_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.identidades IS
    'R27: documento de identidad cifrado (AES-256-GCM). id_interno = HMAC del documento.';

COMMIT;
