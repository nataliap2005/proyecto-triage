# R27: cifrado de campos sensibles con AES-256-GCM.
#
# El teléfono y la dirección se guardan cifrados en PostgreSQL. La llave vive en
# la variable de entorno CIFRADO_LLAVE_K1 (32 bytes en base64), nunca en el
# repositorio ni en la base.
#
# Formato guardado:  v1.k1.<nonce>.<cifrado>
#   v1      versión del formato
#   k1      identificador de la llave (permite rotarla: k2, k3...)
#   nonce   12 bytes aleatorios, distintos en cada cifrado (base64 url)
#   cifrado texto cifrado + etiqueta de autenticación de GCM (base64 url)
#
# El "contexto" (el nombre del campo: "telefono" o "direccion") se pasa como dato
# asociado (AAD): no se cifra, pero queda atado al resultado. Un teléfono cifrado
# copiado a la columna de dirección no descifra.
#
# Quién llama a qué:
#   - Al GUARDAR: las rutas llaman a cifrar() o cifrar_campos() antes del INSERT/UPDATE.
#   - Al LEER: core/database.py descifra en un solo punto (la conexión), así que
#     ninguna ruta tiene que acordarse de descifrar.
#   - Al AUDITAR: routers/common.py vuelve a cifrar antes de escribir la auditoría.

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VERSION = "v1"
LLAVE_ACTIVA = "k1"
PREFIJO = VERSION + "."
BYTES_NONCE = 12
BYTES_LLAVE = 32

# Columnas que se guardan cifradas (pacientes.telefono, pacientes.direccion, usuarios.telefono).
CAMPOS_CIFRADOS = ("telefono", "direccion")


class ErrorCifrado(Exception):
    """La llave falta o es inválida, o el valor guardado fue alterado."""


def _b64(datos: bytes) -> str:
    return base64.urlsafe_b64encode(datos).decode("ascii").rstrip("=")


def _desde_b64(texto: str) -> bytes:
    return base64.urlsafe_b64decode(texto + "=" * (-len(texto) % 4))


def _llave(kid: str) -> bytes:
    # Se lee en el momento de uso para no romper el arranque de quien aún no la tenga.
    valor = os.getenv(f"CIFRADO_LLAVE_{kid.upper()}", "")
    if not valor:
        raise ErrorCifrado(f"Falta la variable de entorno CIFRADO_LLAVE_{kid.upper()}")
    try:
        llave = _desde_b64(valor.strip())
    except Exception as error:
        raise ErrorCifrado("La llave de cifrado no es base64 válido") from error
    if len(llave) != BYTES_LLAVE:
        raise ErrorCifrado("La llave de cifrado debe tener 32 bytes (AES-256)")
    return llave


def esta_cifrado(valor) -> bool:
    return isinstance(valor, str) and valor.startswith(PREFIJO) and valor.count(".") == 3


def cifrar(valor, contexto: str):
    """Devuelve el valor cifrado. None y cadena vacía se devuelven igual."""
    if valor is None or valor == "":
        return valor
    if esta_cifrado(valor):
        return valor  # ya estaba cifrado: no se cifra dos veces
    nonce = os.urandom(BYTES_NONCE)
    cifrado = AESGCM(_llave(LLAVE_ACTIVA)).encrypt(
        nonce, str(valor).encode("utf-8"), contexto.encode("utf-8"))
    return f"{VERSION}.{LLAVE_ACTIVA}.{_b64(nonce)}.{_b64(cifrado)}"


def descifrar(valor, contexto: str):
    """Devuelve el texto original. Un valor sin cifrar (dato antiguo) se devuelve igual."""
    if not esta_cifrado(valor):
        return valor
    _, kid, nonce_b64, cifrado_b64 = valor.split(".")
    try:
        claro = AESGCM(_llave(kid)).decrypt(
            _desde_b64(nonce_b64), _desde_b64(cifrado_b64), contexto.encode("utf-8"))
    except InvalidTag as error:
        raise ErrorCifrado("El valor cifrado fue alterado o no corresponde a este registro") from error
    return claro.decode("utf-8")


def cifrar_campos(datos: dict) -> dict:
    """Copia del diccionario con los campos sensibles cifrados (para INSERT/UPDATE y auditoría)."""
    copia = dict(datos)
    for campo in CAMPOS_CIFRADOS:
        if copia.get(campo):
            copia[campo] = cifrar(copia[campo], campo)
    return copia


def descifrar_fila(fila):
    """Descifra en la misma fila (dict) los campos sensibles que vengan cifrados.

    Si falta la llave o el valor fue alterado, deja el texto cifrado tal cual:
    la lectura no se cae, pero el dato no se revela.
    """
    if not isinstance(fila, dict):
        return fila
    for campo in CAMPOS_CIFRADOS:
        valor = fila.get(campo)
        if esta_cifrado(valor):
            try:
                fila[campo] = descifrar(valor, campo)
            except ErrorCifrado:
                pass
    return fila


def generar_llave() -> str:
    """Llave nueva para el pass.env:  python -c "from core.cifrado import generar_llave; print(generar_llave())" """
    return _b64(os.urandom(BYTES_LLAVE))
