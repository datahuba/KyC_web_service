"""
Modelo de Solicitud de Cuenta (Account Request)
===============================================

Representa una solicitud pública de creación de cuenta de estudiante.
El flujo es: el interesado envía el formulario (público) -> se notifica al CPD
-> el CPD revisa y APRUEBA (se crea el Student) o RECHAZA.

Colección MongoDB: account_requests
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field, EmailStr
from .base import MongoBaseModel, PyObjectId


class AccountRequest(MongoBaseModel):
    nombre: str = Field(..., min_length=3, max_length=200, description="Nombre completo del solicitante")
    email: EmailStr = Field(..., description="Correo electrónico de contacto")
    carnet: str = Field(..., min_length=4, max_length=20, description="Carnet de identidad")
    celular: Optional[str] = Field(None, description="Número de celular de contacto")
    registro: Optional[str] = Field(None, description="Registro académico (si lo tiene)")
    mensaje: Optional[str] = Field(None, description="Mensaje o programa de interés del solicitante")

    estado: str = Field(default="pendiente", description="pendiente | aprobado | rechazado")
    motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazada")
    revisado_por: Optional[str] = Field(None, description="Username del CPD que revisó la solicitud")
    fecha_revision: Optional[datetime] = Field(None, description="Fecha de aprobación/rechazo")
    estudiante_id: Optional[PyObjectId] = Field(None, description="ID del Student creado al aprobar")

    class Settings:
        name = "account_requests"
        indexes = [
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            "email",
            "carnet",
        ]
