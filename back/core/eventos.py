# Bus de eventos en memoria + bandeja persistente.
# publicar() es la ÚNICA puerta para notificar: guarda en BD (R18) y empuja en vivo (R17).
# Funciona con una sola réplica de la API (un worker de uvicorn).

import asyncio
import logging
import threading
from datetime import datetime

from psycopg2.extras import Json, RealDictCursor

log = logging.getLogger("eventos")

_conexiones: dict[int, set[asyncio.Queue]] = {}
_lock = threading.Lock()
_loop: asyncio.AbstractEventLoop | None = None


def configurar_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Se llama una vez al arrancar la API para poder empujar eventos desde hilos."""
    global _loop
    _loop = loop


# ---------- Conexiones SSE ----------

def registrar_conexion(usuario_id: int) -> asyncio.Queue:
    cola: asyncio.Queue = asyncio.Queue(maxsize=200)
    with _lock:
        _conexiones.setdefault(usuario_id, set()).add(cola)
    return cola


def cerrar_conexion(usuario_id: int, cola: asyncio.Queue) -> None:
    with _lock:
        colas = _conexiones.get(usuario_id)
        if colas:
            colas.discard(cola)
            if not colas:
                _conexiones.pop(usuario_id, None)


def _encolar(cola: asyncio.Queue, evento: dict) -> None:
    try:
        cola.put_nowait(evento)
    except asyncio.QueueFull:
        log.warning("Cola SSE llena, evento descartado (queda en la bandeja)")


def emitir(usuario_id: int, evento: dict) -> None:
    """Empuja un evento a todas las pestañas abiertas del usuario."""
    if _loop is None:
        return
    with _lock:
        colas = list(_conexiones.get(usuario_id, ()))
    for cola in colas:
        _loop.call_soon_threadsafe(_encolar, cola, evento)


# ---------- Serialización común (canal y bandeja usan el mismo formato) ----------

def serializar_notificacion(fila: dict) -> dict:
    fecha = fila["fecha"]
    evento = {
        "id": fila["id"],
        "tipo": fila["tipo"],
        "mensaje": fila["mensaje"],
        "fecha": fecha.isoformat() if isinstance(fecha, datetime) else fecha,
        "leida": fila["leida"],
        "paciente_id": fila.get("paciente_id"),
    }
    # Los datos del hecho (remision_id, reporte_id, usuario_bloqueado...) van al nivel superior.
    for clave, valor in (fila.get("datos") or {}).items():
        evento.setdefault(clave, valor)
    return evento


# ---------- API pública ----------

def usuarios_por_rol(db, *roles: str) -> list[int]:
    """Documentos de los usuarios activos que tienen alguno de los roles dados."""
    cur = db.cursor()
    try:
        cur.execute("""
            SELECT u.numero_documento_usuario
            FROM usuarios u
            JOIN roles r ON r.id_rol = u.id_rol
            WHERE r.nombre = ANY(%s)
              AND u.estado = TRUE
              AND u.is_deleted = FALSE;
        """, (list(roles),))
        return [fila[0] for fila in cur.fetchall()]
    finally:
        cur.close()


def publicar(
    db,
    destinatarios,
    tipo: str,
    mensaje: str,
    paciente_id: int | None = None,
    datos: dict | None = None,
) -> list[dict]:
    """
    Guarda una notificación por destinatario y la empuja por el canal en vivo.

    IMPORTANTE: llamar DESPUÉS del commit de la operación de negocio,
    porque esta función hace su propio commit.
    Nunca lanza excepción: si falla, lo registra en el log y la operación
    de negocio (remitir, aprobar, bloquear) no se cae por culpa de la notificación.
    """
    ids = sorted({int(d) for d in (destinatarios or []) if d is not None})
    if not ids:
        return []

    cur = db.cursor(cursor_factory=RealDictCursor)
    pendientes_de_emitir: list[tuple[int, dict]] = []

    try:
        for uid in ids:
            cur.execute("""
                INSERT INTO notificaciones(
                    numero_documento_usuario, tipo, mensaje, paciente_id, datos
                )
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id_notificacion AS id, tipo, mensaje, paciente_id,
                          datos, leida, fecha;
            """, (uid, tipo, mensaje, paciente_id, Json(datos or {})))
            pendientes_de_emitir.append((uid, serializar_notificacion(cur.fetchone())))
        db.commit()
    except Exception:
        db.rollback()
        log.exception("No se pudo publicar el evento %s", tipo)
        return []
    finally:
        cur.close()

    for uid, evento in pendientes_de_emitir:
        emitir(uid, evento)

    return [evento for _, evento in pendientes_de_emitir]