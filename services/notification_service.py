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
    tipo_alerta: str = "info",
    ruta: Optional[str] = None,
    referencia_tipo: Optional[str] = None,
    referencia_id: Optional[PydanticObjectId] = None
) -> Notification:
    """
    Crear y registrar una notificación in-app.

    `ruta` habilita el deep-linking: al hacer click en la campana, el frontend
    navega a esa ruta (ej. '/app/payments'). `referencia_tipo`/`referencia_id`
    permiten resaltar/abrir la entidad concreta (pago, inscripción, etc.).
    """
    notification = Notification(
        destinatario_id=destinatario_id,
        tipo_destinatario=tipo_destinatario,
        titulo=titulo,
        mensaje=mensaje,
        tipo_alerta=tipo_alerta,
        ruta=ruta,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id
    )
    await notification.insert()
    return notification


async def get_user_notifications(
    destinatario_id: PydanticObjectId,
    limit: int = 50,
    only_unread: bool = False
) -> List[Notification]:
    """
    Obtener la lista de notificaciones de un usuario o alumno.
    Utiliza sintaxis de diccionario nativa de MongoDB para evitar el bug de atributos de Pydantic v2.
    """
    query_dict = {"destinatario_id": destinatario_id}
    if only_unread:
        query_dict["leido"] = False
        
    return await Notification.find(query_dict).sort("-created_at").limit(limit).to_list()


async def get_unread_count(destinatario_id: PydanticObjectId) -> int:
    """Obtener conteo neto de notificaciones no leídas de manera robusta y sin colisión de atributos"""
    query_dict = {
        "destinatario_id": destinatario_id,
        "leido": False
    }
    return await Notification.find(query_dict).count()


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
    """Marcar todas las alertas pendientes del destinatario en lote de manera segura"""
    query_dict = {
        "destinatario_id": destinatario_id,
        "leido": False
    }
    result = await Notification.find(query_dict).update({"$set": {"leido": True}})
    return result.modified_count if result else 0