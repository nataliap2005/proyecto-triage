import psycopg2
from psycopg2.extensions import connection as ConexionBase
from psycopg2.extras import RealDictCursor

from core.cifrado import descifrar_fila
from core.config import PG_CONNECTION_STRING


class CursorDescifrado(RealDictCursor):
    """R27: igual que RealDictCursor, pero entrega teléfono y dirección ya descifrados."""

    def fetchone(self):
        return descifrar_fila(super().fetchone())

    def fetchmany(self, size=None):
        filas = super().fetchmany() if size is None else super().fetchmany(size)
        return [descifrar_fila(f) for f in filas]

    def fetchall(self):
        return [descifrar_fila(f) for f in super().fetchall()]

    def __iter__(self):
        for fila in super().__iter__():
            yield descifrar_fila(fila)


class ConexionCifrada(ConexionBase):
    """R27: toda consulta hecha con RealDictCursor pasa por CursorDescifrado.

    Es el único punto de descifrado de la API: las rutas siguen pidiendo
    db.cursor(cursor_factory=RealDictCursor) como siempre.
    """

    def cursor(self, *args, **kwargs):
        if kwargs.get("cursor_factory") is RealDictCursor:
            kwargs["cursor_factory"] = CursorDescifrado
        return super().cursor(*args, **kwargs)


def get_db():
    conn=psycopg2.connect(PG_CONNECTION_STRING,connection_factory=ConexionCifrada)
    try:
        yield conn
    finally:
        conn.close()
