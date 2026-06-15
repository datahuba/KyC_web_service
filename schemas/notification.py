"""
Schemas de Notificaciones
=========================
"""

from datetime import datetime
from pydantic import BaseModel, Field
from models.base import PyObjectId


class NotificationResponse(BaseModel):
    id: PyObjectId = Field(..., alias="_id")
    destinatario_id: PyObjectId
    tipo_destinatario: str
    titulo: str
    mensaje: str
    tipo_alerta: str
    leido: bool
    created_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class NotificationUnreadCount(BaseModel):
    unread_count: int