-- R31: el modo de clave fija registra CLAVE_ACEPTADA y CLAVE_RECHAZADA en
-- oauth_eventos. La restricción original (015) solo admitía los eventos del
-- flujo con token, y la inserción fallaba (HTTP 500). Se amplía la lista.
BEGIN;

DO $$
DECLARE c text;
BEGIN
    FOR c IN
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'public.oauth_eventos'::regclass
          AND contype = 'c'
          AND pg_get_constraintdef(oid) ILIKE '%evento%'
    LOOP
        EXECUTE format('ALTER TABLE public.oauth_eventos DROP CONSTRAINT %I', c);
    END LOOP;
END $$;

ALTER TABLE public.oauth_eventos
    ADD CONSTRAINT oauth_eventos_evento_check CHECK (evento IN (
        'TOKEN_EMITIDO','CREDENCIAL_INVALIDA','CLIENTE_BLOQUEADO',
        'SCOPE_INVALIDO','TOKEN_RECHAZADO','SCOPE_DENEGADO','NONCE_REPETIDO',
        'CLAVE_ACEPTADA','CLAVE_RECHAZADA'
    ));

COMMIT;
