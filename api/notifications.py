"""
Router de Notificaciones
========================
"""

import asyncio
import json
import logging
from typing import List, Any, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Query
from beanie import PydanticObjectId
from sse_starlette.sse import EventSourceResponse
from models.user import User
from models.student import Student
from models.notification import Notification
from schemas.notification import NotificationResponse, NotificationUnreadCount
from services import notification_service
from services.sse_ticket_service import sse_ticket_service
from api.dependencies import get_current_user

router = APIRouter()
_sse_logger = logging.getLogger("kyc.sse")


async def _resolve_user_from_ticket(ticket: str) -> Union[User, Student]:
    """
    El browser EventSource no permite enviar headers custom, así que no
    puede mandar el JWT por Authorization. En vez de pasar el JWT por la
    query string (queda expuesto en historial, logs de Nginx y Referer),
    el cliente primero pide un ticket de un solo uso autenticado
    normalmente (POST /notifications/stream-ticket) y lo usa acá. El
    ticket se consume al primer uso y expira a los 30s.
    """
    from core.config import settings
    if settings.DEVELOPMENT_MODE:
        # En dev, devolver admin mock (igual que get_current_user)
        from models.enums import UserRole
        return User(
            id=PydanticObjectId("000000000000000000000001"),
            username="dev_admin",
            password="mock_password",
            email="dev@example.com",
            rol=UserRole.SUPERADMIN,
            activo=True
        )

    resolved = await sse_ticket_service.consume(ticket)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Ticket inválido, expirado o ya utilizado")
    user_id, user_type = resolved

    if user_type == "student":
        user = await Student.get(PydanticObjectId(user_id))
    else:
        user = await User.get(PydanticObjectId(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado")
    return user


@router.get(
    "/",
    response_model=List[NotificationResponse],
    summary="Listar Notificaciones del Usuario Autenticado"
)
async def read_my_notifications(
    limit: int = 50,
    only_unread: bool = False,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Listar alertas cronológicas del usuario o estudiante autenticado"""
    return await notification_service.get_user_notifications(
        destinatario_id=current_user.id,
        limit=limit,
        only_unread=only_unread
    )


@router.get(
    "/unread-count",
    response_model=NotificationUnreadCount,
    summary="Obtener Conteo de No Leídas"
)
async def read_unread_count(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Retorna la cantidad exacta de alertas pendientes"""
    count = await notification_service.get_unread_count(destinatario_id=current_user.id)
    return {"unread_count": count}


@router.patch(
    "/{id}/read",
    response_model=NotificationResponse,
    summary="Marcar Notificación como Leída"
)
async def read_notification(
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Marcar una alerta específica como leída validando privilegios de acceso"""
    notification = await notification_service.mark_as_read(
        notification_id=id,
        destinatario_id=current_user.id
    )
    if not notification:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Notificación no encontrada o no autorizada"
        )
    return notification


@router.post(
    "/read-all",
    summary="Marcar Todas como Leídas"
)
async def read_all_notifications(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Marcar todas las alertas pendientes en lote como leídas"""
    modified_count = await notification_service.mark_all_as_read(destinatario_id=current_user.id)
    return {
        "message": "Operación exitosa",
        "modified_count": modified_count
    }


@router.post(
    "/stream-ticket",
    summary="Emitir ticket de un solo uso para abrir el stream SSE",
)
async def issue_stream_ticket(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Requiere sesión normal (header Authorization). Devuelve un ticket de
    un solo uso, válido 30s, para abrir `/notifications/stream?ticket=...`
    sin exponer el JWT en la URL.
    """
    user_type = "student" if isinstance(current_user, Student) else "user"
    ticket = await sse_ticket_service.issue(str(current_user.id), user_type)
    return {"ticket": ticket}


# TECH-003: Server-Sent Events para push de notificaciones en tiempo real.
# Reemplaza el polling cada 45s del frontend. El cliente pide un ticket vía
# POST /stream-ticket y abre `EventSource('/api/v1/notifications/stream?ticket=...')`,
# recibiendo eventos `notification` con JSON payload cada vez que se crea una
# nueva notificación para este usuario.
@router.get(
    "/stream",
    summary="Stream SSE de notificaciones en tiempo real",
    response_class=EventSourceResponse,
)
async def stream_notifications(
    request: Request,
    ticket: Optional[str] = Query(default=None, description="Ticket de un solo uso obtenido de POST /notifications/stream-ticket")
):
    """Stream persistente SSE. Heartbeat cada 30s para mantener viva la
    conexión a través de proxies intermedios. Se desconecta automáticamente
    cuando el cliente cierra la pestaña.

    F-FIX-SSE-BUS-MULTIWORKER (2026-08-22, encontrado en la auditoria
    completa): antes esto leía de un "bus" de asyncio.Queue en memoria de
    proceso (`services/sse_bus.py`). Con `uvicorn --workers 4`, si la
    request que crea la notificación caía en un worker distinto al de
    esta conexión (lo más probable, 3 de cada 4 veces), el mensaje se
    perdía sin ningún error visible. Ahora se abre un MongoDB Change
    Stream directo sobre la colección `notifications`, filtrado por
    `destinatario_id` — todos los workers observan la MISMA colección en
    Atlas, así que funciona sin importar en qué worker se creó la
    notificación. Verificado en vivo contra Atlas real: insertar un
    Notification en un proceso separado dispara el `next()` del change
    stream abierto en otro."""

    current_user = await _resolve_user_from_ticket(ticket) if ticket else None
    if current_user is None:
        raise HTTPException(status_code=401, detail="Se requiere un ticket de autenticación válido")

    user_id = current_user.id
    _sse_logger.info(f"[sse] user={user_id} conectado (change stream)")

    async def event_generator():
        collection = Notification.get_motor_collection()
        pipeline = [
            {"$match": {"operationType": "insert", "fullDocument.destinatario_id": user_id}}
        ]
        try:
            # Enviar evento inicial de "conectado" con el unread_count actual
            unread = await notification_service.get_unread_count(destinatario_id=user_id)
            yield {
                "event": "connected",
                "data": json.dumps({"unread_count": unread}),
            }
            last_heartbeat = asyncio.get_event_loop().time()
            async with collection.watch(pipeline=pipeline, full_document="updateLookup") as stream:
                while True:
                    now = asyncio.get_event_loop().time()
                    if now - last_heartbeat > 30:
                        yield {"event": "heartbeat", "data": "{}"}
                        last_heartbeat = now

                    if await request.is_disconnected():
                        break

                    try:
                        change = await asyncio.wait_for(stream.next(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue

                    doc = change.get("fullDocument")
                    if not doc:
                        continue
                    notif_dict = {
                        "id": str(doc.get("_id")),
                        "titulo": doc.get("titulo"),
                        "mensaje": doc.get("mensaje"),
                        "tipo_alerta": doc.get("tipo_alerta"),
                        "ruta": doc.get("ruta"),
                        "referencia_tipo": doc.get("referencia_tipo"),
                        "referencia_id": str(doc["referencia_id"]) if doc.get("referencia_id") else None,
                        "leido": doc.get("leido", False),
                        "created_at": doc.get("created_at").isoformat() if doc.get("created_at") else None,
                    }
                    yield {
                        "event": "notification",
                        "data": json.dumps(notif_dict, default=str),
                    }
        except asyncio.CancelledError:
            # Cliente desconectó abruptamente
            pass
        finally:
            _sse_logger.info(f"[sse] user={user_id} desconectado")

    return EventSourceResponse(event_generator())