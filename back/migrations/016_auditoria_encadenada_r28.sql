-- R28: auditoría encadenada con hashes (tamper-evident).
--
-- Cada fila de auditoria_cambios guarda el hash SHA-256 de la fila anterior
-- (hash_anterior) y el suyo propio (hash_registro), que cubre TODOS sus campos
-- más el hash anterior. Si alguien edita, borra o reordena una fila, la cadena
-- deja de cuadrar a partir de ese punto y la función de verificación lo señala.
--
-- Se hace con un TRIGGER para que cubra, sin tocar código Python, todos los
-- lugares que escriben auditoría (routers/common.py, alertas, fhir_suscripcion,
-- RAG, agente, R30, scripts). Es una migración ADITIVA: solo agrega columnas
-- nullable, funciones y un trigger; el código existente sigue funcionando igual.
--
-- Límite conocido: quien sea dueño de la base de datos puede desactivar el
-- trigger o borrar las últimas filas sin dejar rastro en la cadena. Por eso la
-- verificación devuelve el hash de la cabeza, para anclarlo fuera de la base.
BEGIN;

ALTER TABLE public.auditoria_cambios
    ADD COLUMN IF NOT EXISTS cadena_seq     BIGINT,
    ADD COLUMN IF NOT EXISTS hash_anterior  TEXT,
    ADD COLUMN IF NOT EXISTS hash_registro  TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS uq_auditoria_cadena_seq
    ON public.auditoria_cambios(cadena_seq) WHERE cadena_seq IS NOT NULL;

-- Hash de una fila. Se listan los campos explícitamente (y no la fila entera)
-- para que agregar columnas en el futuro no cambie el hash de lo ya firmado.
-- Se serializa como arreglo JSON: sin ambigüedad entre campos.
CREATE OR REPLACE FUNCTION public.auditoria_hash_fila(
    p_anterior TEXT,
    p_id BIGINT, p_tabla TEXT, p_registro TEXT, p_accion TEXT,
    p_datos_ant JSONB, p_datos_nue JSONB,
    p_realizado_por BIGINT, p_fecha TIMESTAMPTZ, p_origen TEXT
) RETURNS TEXT
LANGUAGE sql IMMUTABLE AS $$
    SELECT encode(sha256(convert_to(
        p_anterior || '|' || jsonb_build_array(
            p_id, p_tabla, p_registro, p_accion,
            p_datos_ant, p_datos_nue, p_realizado_por,
            to_char(p_fecha AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US'),
            p_origen
        )::text,
        'UTF8')), 'hex');
$$;

-- Al insertar: toma el candado de la cadena, lee el último eslabón y firma la fila.
-- El candado (por transacción) serializa a los escritores: la cadena nunca se bifurca.
CREATE OR REPLACE FUNCTION public.auditoria_encadenar()
RETURNS TRIGGER
LANGUAGE plpgsql AS $$
DECLARE
    v_seq  BIGINT;
    v_prev TEXT;
BEGIN
    PERFORM pg_advisory_xact_lock(28028);
    SELECT cadena_seq, hash_registro INTO v_seq, v_prev
    FROM public.auditoria_cambios
    WHERE cadena_seq IS NOT NULL
    ORDER BY cadena_seq DESC
    LIMIT 1;

    NEW.cadena_seq    := COALESCE(v_seq, 0) + 1;
    NEW.hash_anterior := COALESCE(v_prev, repeat('0', 64));
    NEW.hash_registro := public.auditoria_hash_fila(
        NEW.hash_anterior, NEW.id_auditoria, NEW.tabla_afectada, NEW.registro_id,
        NEW.accion, NEW.datos_anteriores, NEW.datos_nuevos, NEW.realizado_por,
        NEW.fecha_hora, NEW.origen);
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_auditoria_encadenar ON public.auditoria_cambios;
CREATE TRIGGER trg_auditoria_encadenar
    BEFORE INSERT ON public.auditoria_cambios
    FOR EACH ROW EXECUTE FUNCTION public.auditoria_encadenar();

-- Encadena las filas que ya existían (en el orden de su id). Idempotente: solo
-- toca las que aún no tienen eslabón, y continúa desde el último existente.
DO $$
DECLARE
    f      RECORD;
    v_seq  BIGINT;
    v_prev TEXT;
BEGIN
    PERFORM pg_advisory_xact_lock(28028);
    SELECT cadena_seq, hash_registro INTO v_seq, v_prev
    FROM public.auditoria_cambios
    WHERE cadena_seq IS NOT NULL
    ORDER BY cadena_seq DESC LIMIT 1;
    v_seq  := COALESCE(v_seq, 0);
    v_prev := COALESCE(v_prev, repeat('0', 64));

    FOR f IN
        SELECT * FROM public.auditoria_cambios
        WHERE cadena_seq IS NULL
        ORDER BY id_auditoria
    LOOP
        v_seq := v_seq + 1;
        UPDATE public.auditoria_cambios SET
            cadena_seq    = v_seq,
            hash_anterior = v_prev,
            hash_registro = public.auditoria_hash_fila(
                v_prev, f.id_auditoria, f.tabla_afectada, f.registro_id, f.accion,
                f.datos_anteriores, f.datos_nuevos, f.realizado_por, f.fecha_hora, f.origen)
        WHERE id_auditoria = f.id_auditoria
        RETURNING hash_registro INTO v_prev;
    END LOOP;
END;
$$;

-- Verificación: recorre la cadena y devuelve el primer eslabón que no cuadra.
--   ok            true si TODO cuadra
--   total         filas encadenadas
--   sin_encadenar filas que quedaron sin eslabón (se insertaron esquivando el trigger)
--   primer_roto   cadena_seq del primer problema (NULL si ok)
--   id_roto       id_auditoria de esa fila
--   motivo        qué falló: CONTENIDO_ALTERADO | ENLACE_ROTO | SECUENCIA_CON_HUECO
--   hash_cabeza   hash del último eslabón (para anclarlo fuera de la base)
CREATE OR REPLACE FUNCTION public.auditoria_verificar_cadena()
RETURNS TABLE(ok BOOLEAN, total BIGINT, sin_encadenar BIGINT,
              primer_roto BIGINT, id_roto BIGINT, motivo TEXT, hash_cabeza TEXT)
LANGUAGE sql STABLE AS $$
    WITH eslabones AS (
        SELECT a.cadena_seq, a.id_auditoria, a.hash_anterior, a.hash_registro,
               lag(a.cadena_seq)    OVER w AS seq_previa,
               lag(a.hash_registro) OVER w AS hash_previo,
               public.auditoria_hash_fila(
                   a.hash_anterior, a.id_auditoria, a.tabla_afectada, a.registro_id,
                   a.accion, a.datos_anteriores, a.datos_nuevos, a.realizado_por,
                   a.fecha_hora, a.origen) AS recalculado
        FROM public.auditoria_cambios a
        WHERE a.cadena_seq IS NOT NULL
        WINDOW w AS (ORDER BY a.cadena_seq)
    ),
    problemas AS (
        SELECT cadena_seq, id_auditoria,
               CASE
                   WHEN recalculado IS DISTINCT FROM hash_registro THEN 'CONTENIDO_ALTERADO'
                   WHEN cadena_seq <> COALESCE(seq_previa, 0) + 1   THEN 'SECUENCIA_CON_HUECO'
                   WHEN hash_anterior IS DISTINCT FROM COALESCE(hash_previo, repeat('0', 64))
                                                                    THEN 'ENLACE_ROTO'
               END AS motivo
        FROM eslabones
    ),
    primero AS (
        SELECT cadena_seq, id_auditoria, motivo FROM problemas
        WHERE motivo IS NOT NULL ORDER BY cadena_seq LIMIT 1
    )
    SELECT
        (SELECT count(*) FROM primero) = 0
            AND (SELECT count(*) FROM public.auditoria_cambios WHERE cadena_seq IS NULL) = 0,
        (SELECT count(*) FROM eslabones),
        (SELECT count(*) FROM public.auditoria_cambios WHERE cadena_seq IS NULL),
        (SELECT cadena_seq FROM primero),
        (SELECT id_auditoria FROM primero),
        (SELECT motivo FROM primero),
        (SELECT hash_registro FROM eslabones ORDER BY cadena_seq DESC LIMIT 1);
$$;

COMMIT;