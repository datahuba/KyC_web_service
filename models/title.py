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
    
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    
    titulo: str = Field(..., min_length=1, description="Nombre del título")
    numero_titulo: str = Field(..., description="Número del título")
    año_expedicion: str = Field(..., description="Año de expedición")
    tipo_titulo: TipoTitulo = Field(...)

    class Settings:
        name = "titles"
    
    
    
