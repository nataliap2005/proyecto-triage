# Evidencias R27 · Cifrado de campos sensibles

**Requisito:** el documento de identidad, el teléfono y la dirección se guardan cifrados con AES-GCM en PostgreSQL; la llave vive en una variable de entorno, nunca en el repositorio.

**Responsable:** Sarah Gómez. **Código:** PR #8 (`7c1acc4`) y commit `3027003` (teléfono y dirección).

## Qué se hizo

| Dato | Cómo queda en PostgreSQL |
|---|---|
| Teléfono y dirección | Cifrados con AES-256-GCM en su misma columna, formato `v1.k1.<nonce>.<cifrado>`, nonce aleatorio por valor y el nombre del campo como dato asociado |
| Documento de identidad | Ninguna tabla lo guarda en claro. Cada persona se identifica con un número interno de 16 dígitos (HMAC-SHA256 del documento con una subllave de `CIFRADO_LLAVE_K1`) y el documento real queda solo en la tabla `identidades`, cifrado con AES-256-GCM |

La API traduce documento ↔ número interno en su frontera (`back/core/identidad_middleware.py`): pantallas, tester y socio siguen viendo el documento normal.

## Archivos

| Archivo | Qué muestra |
|---|---|
| `REGISTRO_R27.txt` | Salida completa de los scripts sobre la base compartida: conteo, aplicación y verificación de teléfono/dirección; migración del documento (258 documentos, 56 llaves foráneas recreadas); verificación; comprobación con la API y resumen final con 0 datos en claro |
| `R27_auth_me_documento_normal_200.png` | Tras migrar, la API sigue mostrando el documento normal |
| `R27_cadena_R28_integra_tras_migrar_200.png` | La cadena de auditoría de R28 sigue íntegra después de migrar (360 eslabones) |

## Cómo comprobarlo

Desde `back/`:

```
python -m pytest tests/test_cifrado_r27.py tests/test_identidad_r27.py -q
python scripts/cifrar_datos_existentes_r27.py --verificar
python scripts/migrar_documentos_r27.py --verificar
python scripts/evidencia_r27.py --documento <documento de un paciente>
```

`evidencia_r27.py` muestra el mismo paciente como está guardado (número interno y valores `v1.k1.`) y como lo descifra la API. Sirve para la demostración: crear un paciente en la app y luego correr el script con su documento.

## Riesgo residual (ver `docs/STRIDE.md`, fila I3)

- Los registros de auditoría anteriores a R27 conservan documentos y teléfonos en claro: reescribirlos rompería la cadena de R28.
- HAPI FHIR y las facturas antiguas de MongoDB están fuera de PostgreSQL.
- Los nombres de usuario de prueba contienen el documento (`admin.<documento>`).
- El número interno es determinista: deja ver que dos filas son de la misma persona, pero sin la llave no permite volver al documento.
