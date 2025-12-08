"""
Modelo de Título
===============

Representa un título o certificado emitido a un estudiante.
Colección MongoDB: titles
"""

from datetime import datetime
from typing import Optional, List
from pydantic import Field
from .base import MongoBaseModel, PyObjectId
from .enums import TipoTitulo


class Title(MongoBaseModel):
    """Modelo de Título/Certificado"""
    titulo: str = Field(..., min_length=1, description="Nombre del título")
    numero_titulo: str = Field(..., description="Número del título")
    año_expedicion: str = Field(..., description="Año de expedición")
    universidad: str = Field(..., description="Universidad que emitió el título")
    titulo_url: Optional[str] = Field(None,description="URL del Título en Provisión Nacional")

    class Settings:
        name = "titles"
    
    
    
