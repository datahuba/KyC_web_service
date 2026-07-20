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
from schemas.notification import NotificationResponse, NotificationUnreadCount
from services import notification_service
from services.sse_bus import sse_bus
from core.security import decode_access_token
from api.dependencies import get_current_user

router = APIRouter()
_sse_logger = logging.getLogger("kyc.sse")


async def _resolve_user_from_query(token: str) -> Union[User, Student]:
    """
    TECH-003: el browser EventSource no permite enviar headers custom, así
    que pasamos el JWT via query string. Esta función valida el token y
    devuelve el User/Student asociado. Replica la lógica de get_current_user
    pero acepta token por query.
    """
    from core.config import settings
    if settings.DEVELOPMENT_MODE:
        from core.config import settings as _s
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

    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado")
    if payload.get("purpose") in ("password_reset", "email_verification"):
        raise HTTPException(status_code=401, detail="Token de un solo uso, no válido para streaming")
    user_id = payload.get("sub")
    user_type = payload.get("user_type")
    if not user_id or not user_type:
        raise HTTPException(status_code=401, detail="Token inválido")

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


# TECH-003: Server-Sent Events para push de notificaciones en tiempo real.
# Reemplaza el polling cada 45s del frontend. El cliente abre
# `EventSource('/api/v1/notifications/stream')` y recibe eventos
# `notification` con JSON payload cada vez que se crea una nueva
# notificación para este usuario.
@router.get(
    "/stream",
    summary="Stream SSE de notificaciones en tiempo real",
    response_class=EventSourceResponse,
)
async def stream_notifications(
    request: Request,
    token: Optional[str] = Query(default=None, description="JWT para autenticar el stream SSE (alternativa al header Authorization porque EventSource no soporta headers custom)")
):
    """Stream persistente SSE. Heartbeat cada 30s para mantener viva la
    conexión a través de proxies intermedios. Se desconecta automáticamente
    cuando el cliente cierra la pestaña."""

    # TECH-003: resolver user desde query token (EventSource no soporta headers)
    current_user = await _resolve_user_from_query(token) if token else None
    if current_user is None:
        raise HTTPException(status_code=401, detail="Se requiere token de autenticación")

    user_id = current_user.id
    queue = await sse_bus.subscribe(user_id)
    _sse_logger.info(f"[sse] user={user_id} subscribed (bus={sse_bus.stats()})")

    async def event_generator():
        try:
            # Enviar evento inicial de "conectado" con el unread_count actual
            unread = await notification_service.get_unread_count(destinatario_id=user_id)
            yield {
                "event": "connected",
                "data": json.dumps({"unread_count": unread}),
            }
            last_heartbeat = asyncio.get_event_loop().time()
            while True:
                # Heartbeat cada 30s para mantener viva la conexión
                now = asyncio.get_event_loop().time()
                if now - last_heartbeat > 30:
                    yield {"event": "heartbeat", "data": "{}"}
                    last_heartbeat = now

                # Si el cliente se desconecta, salir
                if await request.is_disconnected():
                    break

                # Esperar un mensaje con timeout corto para chequear disconnect
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {
                        "event": "notification",
                        "data": json.dumps(data, default=str),
                    }
                except asyncio.TimeoutError:
                    # No había mensaje, seguir el loop para chequear disconnect
                    continue
        except asyncio.CancelledError:
            # Cliente desconectó abruptamente
            pass
        finally:
            await sse_bus.unsubscribe(user_id, queue)
            _sse_logger.info(f"[sse] user={user_id} unsubscribed (bus={sse_bus.stats()})")

    return EventSourceResponse(event_generator())