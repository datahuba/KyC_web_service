"""
Modelos de Classroom
====================

Classroom: aula virtual asociada a un curso.
ClassroomStudent: relación muchos-a-muchos classroom ↔ student.
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from beanie import PydanticObjectId

from .base import MongoBaseModel, PyObjectId


class Classroom(MongoBaseModel):
    """Aula virtual. Un User (admin) actúa como docente."""

    course_id: Optional[PydanticObjectId] = Field(
        None, description="Curso al que pertenece (opcional)"
    )
    teacher_user_id: PydanticObjectId = Field(
        ..., description="ID del User que es docente"
    )
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=1000)
    activo: bool = Field(default=True)

    class Settings:
        name = "classrooms"
        indexes = [
            "teacher_user_id",
            "course_id"
        ]


class ClassroomStudent(MongoBaseModel):
    """Inscripción de un Student en un Classroom."""

    classroom_id: PydanticObjectId = Field(...)
    student_id: PydanticObjectId = Field(...)
    enrolled_at: datetime = Field(default_factory=datetime.utcnow)
    active: bool = Field(default=True)

    class Settings:
        name = "classroom_students"
        indexes = [
            "classroom_id",
            "student_id",
            # Índice único compuesto para impedir la duplicidad de un alumno en un mismo aula
            pymongo.IndexModel([("classroom_id", pymongo.ASCENDING), ("student_id", pymongo.ASCENDING)], unique=True)
        ]
        