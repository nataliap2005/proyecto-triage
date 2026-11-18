BEGIN;

CREATE TABLE IF NOT EXISTS public.clientes_institucionales (
    client_id          VARCHAR(64) PRIMARY KEY
        CHECK (client_id ~ '^[a-z0-9][a-z0-9._-]{2,62}$'),
    nombre             VARCHAR(150) NOT NULL,
    secret_hash        TEXT NOT NULL,
    scopes             TEXT[] NOT NULL
        CHECK (cardinality(scopes) >= 1),
    activo             BOOLEAN NOT NULL DEFAULT TRUE,
    intentos_fallidos  SMALLINT NOT NULL DEFAULT 0 CHECK (intentos_fallidos >= 0),
    bloqueado_hasta    TIMESTAMPTZ,
    creado_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    secreto_rotado_at  TIMESTAMPTZ
);
CREATE TABLE IF NOT EXISTS public.oauth_eventos (
    id_evento   BIGSERIAL PRIMARY KEY,
    client_id   VARCHAR(64),
    evento      VARCHAR(30) NOT NULL
        CHECK (evento IN (
            'TOKEN_EMITIDO','CREDENCIAL_INVALIDA','CLIENTE_BLOQUEADO',
            'SCOPE_INVALIDO','TOKEN_RECHAZADO','SCOPE_DENEGADO','NONCE_REPETIDO'
        )),
    exitoso     BOOLEAN NOT NULL,
    detalle     TEXT,
    fecha_hora  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_oauth_eventos_fecha
    ON public.oauth_eventos(fecha_hora DESC);

CREATE TABLE IF NOT EXISTS public.oauth_nonces (
    client_id  VARCHAR(64) NOT NULL REFERENCES public.clientes_institucionales(client_id),
    nonce      VARCHAR(128) NOT NULL,
    usado_en   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (client_id, nonce)
);
CREATE INDEX IF NOT EXISTS idx_oauth_nonces_usado
    ON public.oauth_nonces(usado_en);

COMMIT;