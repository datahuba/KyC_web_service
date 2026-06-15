"""
Servicio de Notificaciones
==========================
"""

from typing import List, Optional
from beanie import PydanticObjectId
from models.notification import Notification


async def create_notification(
    destinatario_id: PydanticObjectId,
    tipo_destinatario: str,
    titulo: str,
    mensaje: str,
    tipo_alerta: str = "info"
) -> Notification:
    """Crear y registrar una notificación in-app"""
    notification = Notification(
        destinatario_id=destinatario_id,
        tipo_destinatario=tipo_destinatario,
        titulo=titulo,
        mensaje=mensaje,
        tipo_alerta=tipo_alerta
    )
    await notification.insert()
    return notification


async def get_user_notifications(
    destinatario_id: PydanticObjectId,
    limit: int = 50,
    only_unread: bool = False
) -> List[Notification]:
    """Obtener la lista de notificaciones de un usuario o alumno"""
    query = Notification.find(Notification.destinatario_id == destinatario_id)
    if only_unread:
        query = query.find(Notification.leido == False)
    
    return await query.sort("-created_at").limit(limit).to_list()


async def get_unread_count(destinatario_id: PydanticObjectId) -> int:
    """Obtener conteo neto de notificaciones no leídas"""
    return await Notification.find(
        Notification.destinatario_id == destinatario_id,
        Notification.leido == False
    ).count()


async def mark_as_read(
    notification_id: PydanticObjectId, 
    destinatario_id: PydanticObjectId
) -> Optional[Notification]:
    """Marcar alerta individual como leída verificando seguridad"""
    notification = await Notification.get(notification_id)
    if notification and notification.destinatario_id == destinatario_id:
        notification.leido = True
        await notification.save()
        return notification
    return None


async def mark_all_as_read(destinatario_id: PydanticObjectId) -> int:
    """Marcar todas las alertas pendientes del destinatario en lote"""
    result = await Notification.find(
        Notification.destinatario_id == destinatario_id,
        Notification.leido == False
    ).update({"$set": {"leido": True}})
    return result.modified_count if result else 0