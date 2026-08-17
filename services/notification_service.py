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
    referencia_id: Optional[PydanticObjectId] = None,
    evento: Optional[str] = None
) -> Notification:
    """
    Crear y registrar una notificación in-app.

    `ruta` habilita el deep-linking: al hacer click en la campana, el frontend
    navega a esa ruta (ej. '/app/payments'). `referencia_tipo`/`referencia_id`
    permiten resaltar/abrir la entidad concreta (pago, inscripción, etc.).

    TECH-003: después de insertar, publica en el SSE bus para notificar en
    tiempo real a los clientes conectados (elimina el polling cada 45s del
    frontend).
    """
    notification = Notification(
        destinatario_id=destinatario_id,
        tipo_destinatario=tipo_destinatario,
        titulo=titulo,
        mensaje=mensaje,
        tipo_alerta=tipo_alerta,
        ruta=ruta,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        evento=evento
    )
    await notification.insert()

    # TECH-003: push en tiempo real via SSE. No bloquea: si nadie está
    # conectado, se ignora. Si la queue está llena, descarta.
    try:
        from services.sse_bus import sse_bus
        # Serializar a dict para que el JSON sea estable
        notif_dict = {
            "id": str(notification.id),
            "titulo": notification.titulo,
            "mensaje": notification.mensaje,
            "tipo_alerta": notification.tipo_alerta,
            "ruta": notification.ruta,
            "referencia_tipo": notification.referencia_tipo,
            "referencia_id": str(notification.referencia_id) if notification.referencia_id else None,
            "leido": notification.leido,
            "created_at": notification.created_at.isoformat() if notification.created_at else None,
        }
        await sse_bus.publish(destinatario_id, notif_dict)
    except Exception as e:
        # No fallar la creación de la notificación por un error en el bus
        import logging
        logging.getLogger("kyc.sse").warning(f"[sse] publish failed: {e}")

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