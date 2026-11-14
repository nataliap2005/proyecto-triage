-- 010: autorización explícita de encuentros para el corpus RAG.
-- No aprueba registros existentes ni cambia el flujo del frontend.
-- Ejecutar desde back/: python scripts/ejecutar_migracion.py 010_aprobacion_rag.sql
ALTER TABLE public.encuentros
    ADD COLUMN IF NOT EXISTS aprobado_rag BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.encuentros.aprobado_rag IS
    'Autorización específica para indexación RAG; no equivale a aprobar ML ni a finalizar un encuentro.';

CREATE INDEX IF NOT EXISTS idx_encuentros_rag_aprobados
    ON public.encuentros (id_paciente, id_encuentro)
    WHERE aprobado_rag IS TRUE AND is_deleted IS FALSE;
