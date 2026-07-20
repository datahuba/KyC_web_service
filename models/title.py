"""
Modelo de Título
===============

Representa un título o certificado de un estudiante.
Este modelo es EMBEBIDO en Student (no tiene colección propia).
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from .enums import EstadoTitulo


class Title(BaseModel):
    """
    Modelo de Título/Certificado (Embebido en Student)
    
    Este modelo NO hereda de MongoBaseModel porque está embebido
    en el documento Student. No tiene ID propio ni colección separada.
    """
    # Datos del título
    titulo: Optional[str] = Field(None, description="Nombre del título (ej: Licenciatura en Ingeniería)")
    numero_titulo: Optional[str] = Field(None, description="Número del título")
    año_expedicion: Optional[str] = Field(None, description="Año de expedición")
    universidad: Optional[str] = Field(None, description="Universidad que emitió el título")
    titulo_url: Optional[str] = Field(None, description="URL del PDF del título en Cloudinary")
    
    # Campos de validación
    estado: EstadoTitulo = Field(default=EstadoTitulo.SIN_TITULO, description="Estado de validación del título")
    verificado_por: Optional[str] = Field(None, description="Username del admin que verificó")
    fecha_verificacion: Optional[datetime] = Field(None, description="Fecha de verificación/rechazo")
    motivo_rechazo: Optional[str] = Field(None, description="Razón del rechazo (si aplica)")
    
    class Config:
        json_schema_extra = {
            "example": {
                "titulo": "Licenciatura en Ingeniería de Sistemas",
                "numero_titulo": "123456",
                "año_expedicion": "2020",
                "universidad": "Universidad Mayor de San Andrés",
                "titulo_url": "https://res.cloudinary.com/.../titulo.pdf",
                "estado": "verificado",
                "verificado_por": "admin",
                "fecha_verificacion": "2024-12-08T17:00:00"
            }
        }
