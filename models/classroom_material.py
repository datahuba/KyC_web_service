"""
Modelo de Material de Classroom
================================

Archivos (PDF, Word, PPT, XLSX, imágenes) subidos por el docente.
El archivo físico vive en Cloudinary; este modelo guarda la metadata.
"""

from typing import Optional
from pydantic import Field
from beanie import PydanticObjectId

from .base import MongoBaseModel


class ClassroomMaterial(MongoBaseModel):
    """Metadata de un material subido a un classroom."""

    classroom_id: PydanticObjectId = Field(...)
    title: str = Field(..., min_length=1, max_length=200)

    # Cloudinary
    file_url: str = Field(..., description="URL segura de Cloudinary")
    public_id: str = Field(..., description="public_id de Cloudinary para borrar")
    resource_type: str = Field(default="raw", description="'raw' o 'image'")
    mime_type: str = Field(...)
    size_bytes: int = Field(..., ge=0)

    uploaded_by: PydanticObjectId = Field(..., description="ID del User que subió")
    active: bool = Field(default=True)

    class Settings:
        name = "classroom_materials"
