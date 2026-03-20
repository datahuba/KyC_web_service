"""
Modelo de Submission (Entrega de Estudiante)
=============================================

Entrega de un estudiante para una tarea o examen.
Puede contener texto, archivo en Cloudinary, o ambos.
Índice único: (assignment_id, student_id) — una entrega por estudiante.
"""

from datetime import datetime
from typing import Optional
from pydantic import Field
from beanie import PydanticObjectId

from .base import MongoBaseModel
from .enums import SubmissionStatus


class Submission(MongoBaseModel):
    assignment_id: PydanticObjectId = Field(...)
    classroom_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)

    # Contenido de la entrega
    text_content: Optional[str] = Field(None, max_length=5000)
    file_url: Optional[str] = None
    public_id: Optional[str] = None          # Cloudinary public_id
    resource_type: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None

    # Control de intentos (máximo 3)
    attempt_count: int = Field(default=0, ge=0)

    # Estado y calificación
    status: SubmissionStatus = Field(default=SubmissionStatus.PENDING)
    score: Optional[float] = Field(None, ge=0)
    feedback: Optional[str] = Field(None, max_length=2000)
    graded_by: Optional[PydanticObjectId] = None
    submitted_at: Optional[datetime] = None
    graded_at: Optional[datetime] = None

    class Settings:
        name = "submissions"
