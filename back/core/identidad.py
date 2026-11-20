# R27: documento de identidad cifrado.
#
# Problema: el documento era la llave primaria de pacientes y usuarios, y todas
# las tablas lo usaban para unirse. Guardarlo cifrado en el mismo sitio rompería
# esas uniones, porque AES-GCM da un resultado distinto cada vez.
#
# Solución (seudónimo interno + bóveda):
#   1. En la base, cada persona se identifica con un NÚMERO INTERNO de 16 dígitos
#      calculado con HMAC-SHA256 a partir del documento y de una subllave secreta.
#      - El mismo documento da siempre el mismo número: usuario y paciente de una
#        misma persona siguen coincidiendo, y las uniones entre tablas no cambian.
#      - Sin la llave no se puede volver del número al documento.
#   2. El documento real se guarda cifrado con AES-256-GCM en la tabla
#      `identidades` (id_interno -> documento_cifrado). Es la única copia.
#   3. En la frontera de la API (core/identidad_middleware.py) el documento que
#      llega se traduce al número interno, y el número interno que sale se traduce
#      de vuelta al documento. Las pantallas, el tester y los otros equipos siguen
#      viendo el documento de siempre.
#
# Rango del número interno: [10^15, 9*10^15). Tiene 16 dígitos (ningún documento
# colombiano los tiene, así que nunca se confunden) y es menor que 2^53, así que
# el navegador lo puede manejar sin perder precisión.
#
# La subllave sale de CIFRADO_LLAVE_K1. Si algún día se rota la llave de cifrado,
# k1 debe conservarse: los números internos dependen de ella.

import hashlib
import hmac
import re
import threading
import time

import psycopg2

from core.cifrado import _llave, cifrar, descifrar
from core.config import PG_CONNECTION_STRING

INTERNO_MIN = 10**15
INTERNO_MAX = 9 * 10**15          # exclusivo; menor que 2^53 = 9 007 199 254 740 992
CONTEXTO = "documento"            # dato asociado (AAD) del cifrado del documento
_ETIQUETA_SUBLLAVE = b"R27-identidad-interna-v1"

# Un número de 16 dígitos suelto (no pegado a letras, guiones, base64 ni a un punto
# decimal anterior). Así no se tocan hashes, tokens, valores cifrados ni decimales.
PATRON_INTERNO = re.compile(r"(?<![0-9A-Za-z_\-+/=.])([1-8]\d{15})(?![0-9A-Za-z_\-+/=])")

_cache: dict[int, int] = {}        # id_interno -> documento real
_lock = threading.Lock()
_activa: bool | None = None
_activa_revisada = 0.0


def _subllave() -> bytes:
    return hmac.new(_llave("k1"), _ETIQUETA_SUBLLAVE, hashlib.sha256).digest()


def es_interno(valor) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool) and INTERNO_MIN <= valor < INTERNO_MAX


def interno(documento):
    """Documento real -> número interno. None queda None. Un número interno se devuelve igual."""
    if documento is None or documento == "":
        return documento
    numero = int(documento)
    if es_interno(numero):
        return numero
    firma = hmac.new(_subllave(), str(numero).encode("ascii"), hashlib.sha256).digest()
    return INTERNO_MIN + int.from_bytes(firma[:8], "big") % (INTERNO_MAX - INTERNO_MIN)


def _conexion():
    return psycopg2.connect(PG_CONNECTION_STRING)


def registrar(documento, cur=None) -> int:
    """Guarda el documento cifrado en la bóveda (si no estaba) y devuelve su número interno."""
    numero = int(documento)
    if es_interno(numero):
        return numero
    id_interno = interno(numero)
    if id_interno in _cache:
        return id_interno
    sql = """INSERT INTO identidades(id_interno, documento_cifrado)
             VALUES (%s, %s) ON CONFLICT (id_interno) DO NOTHING;"""
    valores = (id_interno, cifrar(str(numero), CONTEXTO))
    if cur is not None:
        cur.execute(sql, valores)
    else:
        conn = _conexion()
        try:
            with conn.cursor() as c:
                c.execute(sql, valores)
            conn.commit()
        finally:
            conn.close()
    with _lock:
        _cache[id_interno] = numero
    return id_interno


def _cargar(ids) -> None:
    faltan = [i for i in set(ids) if i not in _cache]
    if not faltan:
        return
    conn = _conexion()
    try:
        with conn.cursor() as c:
            c.execute("SELECT id_interno, documento_cifrado FROM identidades WHERE id_interno = ANY(%s);",
                      (faltan,))
            filas = c.fetchall()
    finally:
        conn.close()
    with _lock:
        for id_interno, cifrado in filas:
            _cache[int(id_interno)] = int(descifrar(cifrado, CONTEXTO))


def real(valor):
    """Número interno -> documento real. Cualquier otro valor se devuelve igual."""
    if isinstance(valor, str) and len(valor) == 16 and valor.isdigit():
        return str(real(int(valor)))
    if not es_interno(valor):
        return valor
    if valor not in _cache:
        _cargar([valor])
    return _cache.get(valor, valor)


def traducir_texto(texto: str) -> str:
    """Reemplaza en un texto (JSON, evento, mensaje) cada número interno por el documento."""
    if not texto:
        return texto
    candidatos = {int(m) for m in PATRON_INTERNO.findall(texto)}
    candidatos = {c for c in candidatos if es_interno(c)}
    if not candidatos:
        return texto
    _cargar(candidatos)
    return PATRON_INTERNO.sub(
        lambda m: str(_cache.get(int(m.group(1)), m.group(1))), texto)


def activa() -> bool:
    """La traducción se enciende sola cuando la base ya fue migrada (bóveda con datos).

    Así el código se puede fusionar antes de migrar sin romper nada: mientras la
    tabla `identidades` no exista o esté vacía, la API funciona como antes.
    """
    global _activa, _activa_revisada
    if _activa:
        return True
    ahora = time.monotonic()
    if _activa is not None and ahora - _activa_revisada < 30:
        return False
    try:
        conn = _conexion()
        try:
            with conn.cursor() as c:
                c.execute("SELECT to_regclass('public.identidades') IS NOT NULL;")
                existe = c.fetchone()[0]
                hay = False
                if existe:
                    c.execute("SELECT EXISTS (SELECT 1 FROM identidades);")
                    hay = c.fetchone()[0]
        finally:
            conn.close()
        _activa = bool(hay)
    except Exception:
        _activa = False
    _activa_revisada = ahora
    return _activa
