"""R31: alta, rotación y baja de credenciales de una institución socio.

Desde la carpeta back/:
    python scripts/gestionar_cliente_institucional.py crear   socio-uao "Institución socia" bundle:write,task:write
    python scripts/gestionar_cliente_institucional.py rotar   socio-uao
    python scripts/gestionar_cliente_institucional.py desactivar socio-uao
    python scripts/gestionar_cliente_institucional.py listar

- El client_secret se muestra UNA sola vez al crear o rotar. En la base solo queda su hash.
- Entréguelo al otro equipo por un canal privado (no por el grupo de la clase, no por el repositorio).
- Al rotar, el secreto anterior deja de funcionar de inmediato: coordine el cambio con el socio.
"""
import secrets
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg2

from auth.institucional import SCOPES_VALIDOS
from core.config import PG_CONNECTION_STRING
from core.security import hash_password


def _nuevo_secreto() -> str:
    return secrets.token_urlsafe(32)


def _mostrar_secreto(client_id: str, secreto: str) -> None:
    print("\n" + "=" * 64)
    print(f"  client_id:     {client_id}")
    print(f"  client_secret: {secreto}")
    print("=" * 64)
    print("Guárdelo AHORA en un lugar privado: no se vuelve a mostrar.")
    print("Nunca lo suba a Git ni lo pegue en un chat público.\n")


def crear(cur, client_id: str, nombre: str, scopes: list) -> None:
    invalidos = [s for s in scopes if s not in SCOPES_VALIDOS]
    if invalidos:
        sys.exit(f"Scopes no válidos: {invalidos}. Permitidos: {', '.join(SCOPES_VALIDOS)}")
    secreto = _nuevo_secreto()
    cur.execute(
        """
        INSERT INTO clientes_institucionales(client_id, nombre, secret_hash, scopes)
        VALUES (%s, %s, %s, %s);
        """,
        (client_id, nombre, hash_password(secreto), scopes),
    )
    print(f"Institución creada: {client_id} ({nombre}) con permisos: {', '.join(scopes)}")
    _mostrar_secreto(client_id, secreto)


def rotar(cur, client_id: str) -> None:
    secreto = _nuevo_secreto()
    cur.execute(
        """
        UPDATE clientes_institucionales
        SET secret_hash = %s, secreto_rotado_at = now(),
            intentos_fallidos = 0, bloqueado_hasta = NULL
        WHERE client_id = %s;
        """,
        (hash_password(secreto), client_id),
    )
    if cur.rowcount != 1:
        sys.exit(f"No existe la institución '{client_id}'")
    print(f"Secreto rotado para {client_id}. El anterior ya no funciona.")
    _mostrar_secreto(client_id, secreto)


def desactivar(cur, client_id: str) -> None:
    cur.execute("UPDATE clientes_institucionales SET activo = FALSE WHERE client_id = %s;", (client_id,))
    if cur.rowcount != 1:
        sys.exit(f"No existe la institución '{client_id}'")
    print(f"Institución desactivada: {client_id}. Sus tokens vigentes dejan de servir de inmediato.")


def listar(cur) -> None:
    cur.execute(
        """
        SELECT client_id, nombre, scopes, activo, creado_at, secreto_rotado_at, bloqueado_hasta
        FROM clientes_institucionales ORDER BY creado_at;
        """
    )
    filas = cur.fetchall()
    if not filas:
        print("No hay instituciones registradas.")
    for c in filas:
        print(f"- {c[0]} | {c[1]} | permisos: {', '.join(c[2])} | activo: {c[3]} | "
              f"creado: {c[4]:%Y-%m-%d %H:%M} | rotado: {c[5] or '-'} | bloqueado hasta: {c[6] or '-'}")


def main() -> None:
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    orden = args[0]
    with psycopg2.connect(PG_CONNECTION_STRING) as conn, conn.cursor() as cur:
        if orden == "crear" and len(args) == 4:
            crear(cur, args[1], args[2], [s.strip() for s in args[3].split(",") if s.strip()])
        elif orden == "rotar" and len(args) == 2:
            rotar(cur, args[1])
        elif orden == "desactivar" and len(args) == 2:
            desactivar(cur, args[1])
        elif orden == "listar" and len(args) == 1:
            listar(cur)
        else:
            sys.exit(__doc__)


if __name__ == "__main__":
    main()
    