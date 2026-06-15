"""
Router de Notificaciones
========================
"""

from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException, status
from beanie import PydanticObjectId
from models.user import User
from models.student import Student
from schemas.notification import NotificationResponse, NotificationUnreadCount
from services import notification_service
from api.dependencies import get_current_user

router = APIRouter()


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