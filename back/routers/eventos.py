# R17: canal en tiempo real por SSE.  R18: bandeja persistente de notificaciones.

import asyncio
import json

import psycopg2
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from psycopg2.extras import RealDictCursor

from auth.service import usuario_actual, usuario_desde_token
from core.config import PG_CONNECTION_STRING
from core.database import get_db
from core.eventos import cerrar_conexion, registrar_conexion, serializar_notificacion

router = APIRouter(tags=["Tiempo real y notificaciones"])

INTERVALO_PING = 15  # segundos; mantiene viva la conexión a través de Nginx y Cloudflare


def _validar_token_sse(token: str) -> dict:
    # Conexión corta: no se deja una conexión a Postgres abierta durante todo el stream.
    conn = psycopg2.connect(PG_CONNECTION_STRING)
    try:
        return usuario_desde_token(token, conn)
    finally:
        conn.close()


@router.get("/eventos/stream")
async def stream_eventos(
    request: Request,
    token: str | None = Query(None, description="JWT; EventSource no envía cabeceras"),
    authorization: str | None = Header(None),
):
    if not token and authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1]
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token requerido")

    usuario = await run_in_threadpool(_validar_token_sse, token)
    uid = int(usuario["numero_documento_usuario"])

    async def generador():
        cola = registrar_conexion(uid)
        try:
            # El comentario inicial obliga a enviar las cabeceras de inmediato.
            yield "retry: 3000\n: conectado\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    evento = await asyncio.wait_for(cola.get(), timeout=INTERVALO_PING)
                    datos = json.dumps(evento, ensure_ascii=False, default=str)
                    yield f"id: {evento['id']}\ndata: {datos}\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            cerrar_conexion(uid, cola)

    return StreamingResponse(
        generador(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # refuerzo: le dice a Nginx que no bufferice
            "Connection": "keep-alive",
        },
    )


# ---------- Bandeja (R18) ----------

@router.get("/notificaciones")
def listar_notificaciones(
    solo_no_leidas: bool = False,
    limite: int = Query(50, ge=1, le=200),
    db=Depends(get_db),
    usuario=Depends(usuario_actual),
):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        cur.execute("""
            SELECT id_notificacion AS id, tipo, mensaje, paciente_id, datos, leida, fecha
            FROM notificaciones
            WHERE numero_documento_usuario = %s
              AND (%s = FALSE OR leida = FALSE)
            ORDER BY fecha DESC
            LIMIT %s;
        """, (usuario["numero_documento_usuario"], solo_no_leidas, limite))
        return [serializar_notificacion(f) for f in cur.fetchall()]
    finally:
        cur.close()


@router.patch("/notificaciones/leer-todas")
def leer_todas(db=Depends(get_db), usuario=Depends(usuario_actual)):
    cur = db.cursor()
    try:
        cur.execute("""
            UPDATE notificaciones SET leida = TRUE, leida_at = now()
            WHERE numero_documento_usuario = %s AND leida = FALSE;
        """, (usuario["numero_documento_usuario"],))
        n = cur.rowcount
        db.commit()
        return {"marcadas": n}
    finally:
        cur.close()


@router.patch("/notificaciones/{id_notificacion}/leer")
def leer_notificacion(
    id_notificacion: int,
    db=Depends(get_db),
    usuario=Depends(usuario_actual),
):
    cur = db.cursor(cursor_factory=RealDictCursor)
    try:
        # El filtro por dueño hace que una notificación ajena sea indistinguible de una inexistente.
        cur.execute("""
            UPDATE notificaciones SET leida = TRUE, leida_at = now()
            WHERE id_notificacion = %s AND numero_documento_usuario = %s
            RETURNING id_notificacion AS id, tipo, mensaje, paciente_id, datos, leida, fecha;
        """, (id_notificacion, usuario["numero_documento_usuario"]))
        fila = cur.fetchone()
        if not fila:
            db.rollback()
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Notificación no encontrada")
        db.commit()
        return serializar_notificacion(fila)
    finally:
        cur.close()

@router.get("/pendientes")
def trabajo_pendiente(db=Depends(get_db), usuario=Depends(usuario_actual)):
    """
    Contadores del usuario autenticado. Suben cuando nace el trabajo y bajan
    cuando se resuelve, porque se calculan desde el estado real de cada tabla.
    """
    uid = usuario["numero_documento_usuario"]
    rol = usuario["rol"]

    contadores = {
        "reportes_por_revisar": 0,   # R10: se conecta cuando exista la tabla de reportes IA
        "remisiones_recibidas": 0,
        "alertas_activas": 0,        # R20: se conecta cuando exista la tabla de alertas
        "notificaciones_no_leidas": 0,
    }

    cur = db.cursor()
    try:
        # Una remisión cuenta mientras está 'pendiente'. Al aceptarla o rechazarla, baja.
        if rol == "Especialista":
            cur.execute("""
                SELECT count(*) FROM remisiones
                WHERE especialista_destino = %s
                  AND estado = 'pendiente'
                  AND is_deleted = FALSE;
            """, (uid,))
            contadores["remisiones_recibidas"] = cur.fetchone()[0]

        cur.execute("""
            SELECT count(*) FROM notificaciones
            WHERE numero_documento_usuario = %s AND leida = FALSE;
        """, (uid,))
        contadores["notificaciones_no_leidas"] = cur.fetchone()[0]

        return contadores
    finally:
        cur.close()