"""
Modelo de Assignment (Tarea / Examen)
======================================

Una actividad evaluable creada por el docente dentro de un Classroom.
type=TASK → tarea; type=EXAM → examen.
"""

from datetime import datetime
from typing import Optional
from pydantic import Field
from beanie import PydanticObjectId

from .base import MongoBaseModel
from .enums import AssignmentType


class Assignment(MongoBaseModel):
    classroom_id: PydanticObjectId = Field(...)
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    type: AssignmentType = Field(...)
    due_at: Optional[datetime] = Field(None, description="Fecha límite de entrega")
    max_score: float = Field(default=100.0, ge=0)
    created_by: PydanticObjectId = Field(..., description="ID del User docente")
    active: bool = Field(default=True)

    class Settings:
        name = "assignments"
