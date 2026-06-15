"""
Modelo de Notificación
======================

Representa una notificación in-app para un usuario (User o Student).
Colección MongoDB: notifications
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class Notification(MongoBaseModel):
    destinatario_id: PyObjectId = Field(
        ...,
        description="ID del destinatario (User o Student) de la notificación"
    )
    
    tipo_destinatario: str = Field(
        ...,
        description="Tipo de destinatario: 'user' o 'student'"
    )
    
    titulo: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Título de la alerta"
    )
    
    mensaje: str = Field(
        ...,
        min_length=1,
        description="Contenido detallado de la notificación"
    )
    
    tipo_alerta: str = Field(
        default="info",
        description="Nivel de alerta visual: 'info', 'success', 'warning', 'error'"
    )
    
    leido: bool = Field(
        default=False,
        description="¿El destinatario ya marcó la notificación como leída?"
    )
    
    created_at: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora de registro de la alerta"
    )
    
    class Settings:
        name = "notifications"
        indexes = [
            # Índice compuesto optimizado para consultas de alertas pendientes ordenadas por fecha
            [("destinatario_id", pymongo.ASCENDING), ("leido", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            # Índice simple para reportes cronológicos generales
            [("created_at", pymongo.DESCENDING)]
        ]