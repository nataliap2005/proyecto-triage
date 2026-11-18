-- R27: cifrado de campos sensibles (AES-256-GCM).
--
-- El teléfono y la dirección se cifran en la API antes de guardarse. El texto
-- cifrado es más largo que el original (una dirección de 200 caracteres ocupa
-- unos 333), así que las columnas pasan de VARCHAR corto a TEXT.
--
-- Esta migración solo cambia el tipo de las columnas: no cifra nada y no rompe
-- el código anterior. Los datos que ya existen se cifran después, con
--     python scripts/cifrar_datos_existentes_r27.py
-- La llave no está en la base: vive en la variable de entorno CIFRADO_LLAVE_K1.
BEGIN;

ALTER TABLE public.pacientes ALTER COLUMN telefono  TYPE TEXT;
ALTER TABLE public.pacientes ALTER COLUMN direccion TYPE TEXT;
ALTER TABLE public.usuarios  ALTER COLUMN telefono  TYPE TEXT;

COMMENT ON COLUMN public.pacientes.telefono  IS 'R27: cifrado con AES-256-GCM (formato v1.k1.nonce.cifrado)';
COMMENT ON COLUMN public.pacientes.direccion IS 'R27: cifrado con AES-256-GCM (formato v1.k1.nonce.cifrado)';
COMMENT ON COLUMN public.usuarios.telefono   IS 'R27: cifrado con AES-256-GCM (formato v1.k1.nonce.cifrado)';

COMMIT;
