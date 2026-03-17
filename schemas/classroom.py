"""
Schemas de Classroom
====================

Contratos de request/response para el módulo Classroom.
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional
from datetime import datetime
from beanie import PydanticObjectId

from models.enums import AssignmentType, SubmissionStatus


# ─────────────────────────────────────────────
# CLASSROOM
# ─────────────────────────────────────────────

class ClassroomCreate(BaseModel):
    nombre: str = Field(..., min_length=1, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=1000)
    course_id: Optional[PydanticObjectId] = None
    teacher_user_id: Optional[PydanticObjectId] = None

    @field_validator("course_id", mode="before")
    @classmethod
    def normalize_empty_course_id(cls, value):
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
        return value


class ClassroomUpdate(BaseModel):
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    descripcion: Optional[str] = None
    activo: Optional[bool] = None
    teacher_user_id: Optional[PydanticObjectId] = None


class ClassroomResponse(BaseModel):
    id: str
    nombre: str
    descripcion: Optional[str] = None
    course_id: Optional[str] = None
    course_nombre: Optional[str] = None
    teacher_user_id: Optional[str] = None
    teacher_name: Optional[str] = None
    activo: bool = True
    created_at: Optional[str] = None

    @classmethod
    def from_doc(cls, doc, teacher_name: str = "") -> "ClassroomResponse":
        return cls(
            id=str(doc.id),
            nombre=doc.nombre,
            descripcion=doc.descripcion,
            course_id=str(doc.course_id) if doc.course_id else None,
            teacher_user_id=str(doc.teacher_user_id),
            teacher_name=teacher_name,
            activo=doc.activo,
            created_at=doc.created_at.isoformat() if doc.created_at else None,
        )


class EnrollStudentRequest(BaseModel):
    student_id: str


class ClassroomStudentResponse(BaseModel):
    id: str
    registro: str
    nombre: Optional[str] = None
    email: Optional[str] = None
    activo: bool = True

    @classmethod
    def from_doc(cls, doc) -> "ClassroomStudentResponse":
        return cls(
            id=str(doc.id),
            registro=doc.registro,
            nombre=doc.nombre,
            email=doc.email,
            activo=doc.activo,
        )


# ─────────────────────────────────────────────
# MATERIAL
# ─────────────────────────────────────────────

class ClassroomMaterialResponse(BaseModel):
    id: str
    classroom_id: str
    title: str
    file_url: str
    public_id: Optional[str] = None
    resource_type: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: Optional[str] = None
    created_at: Optional[str] = None
    active: bool = True

    @classmethod
    def from_doc(cls, doc) -> "ClassroomMaterialResponse":
        return cls(
            id=str(doc.id),
            classroom_id=str(doc.classroom_id),
            title=doc.title,
            file_url=doc.file_url,
            public_id=doc.public_id,
            resource_type=doc.resource_type,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            uploaded_by=str(doc.uploaded_by),
            created_at=doc.created_at.isoformat() if doc.created_at else None,
            active=doc.active,
        )


# ─────────────────────────────────────────────
# ASSIGNMENT
# ─────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = Field(None, max_length=2000)
    type: AssignmentType
    due_at: Optional[datetime] = None
    max_score: float = Field(default=100.0, ge=0)


class AssignmentUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    due_at: Optional[datetime] = None
    max_score: Optional[float] = Field(None, ge=0)
    active: Optional[bool] = None


class AssignmentResponse(BaseModel):
    id: str
    classroom_id: str
    title: str
    description: Optional[str] = None
    type: AssignmentType
    due_at: Optional[str] = None
    max_score: float = 100.0
    created_by: Optional[str] = None
    created_at: Optional[str] = None

    @classmethod
    def from_doc(cls, doc) -> "AssignmentResponse":
        return cls(
            id=str(doc.id),
            classroom_id=str(doc.classroom_id),
            title=doc.title,
            description=doc.description,
            type=doc.type,
            due_at=doc.due_at.isoformat() if doc.due_at else None,
            max_score=doc.max_score,
            created_by=str(doc.created_by),
            created_at=doc.created_at.isoformat() if doc.created_at else None,
        )


# ─────────────────────────────────────────────
# SUBMISSION
# ─────────────────────────────────────────────

class SubmissionResponse(BaseModel):
    id: str
    assignment_id: str
    classroom_id: str
    student_id: str
    text_content: Optional[str] = None
    file_url: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    status: SubmissionStatus
    score: Optional[float] = None
    max_score: Optional[float] = None
    feedback: Optional[str] = None
    submitted_at: Optional[str] = None
    graded_at: Optional[str] = None

    @classmethod
    def from_doc(cls, doc, max_score: float = 100.0) -> "SubmissionResponse":
        return cls(
            id=str(doc.id),
            assignment_id=str(doc.assignment_id),
            classroom_id=str(doc.classroom_id),
            student_id=str(doc.student_id),
            text_content=doc.text_content,
            file_url=doc.file_url,
            mime_type=doc.mime_type,
            size_bytes=doc.size_bytes,
            status=doc.status,
            score=doc.score,
            max_score=max_score,
            feedback=doc.feedback,
            submitted_at=doc.submitted_at.isoformat() if doc.submitted_at else None,
            graded_at=doc.graded_at.isoformat() if doc.graded_at else None,
        )


class GradeRequest(BaseModel):
    score: float = Field(..., ge=0)
    feedback: Optional[str] = Field(None, max_length=2000)


# ─────────────────────────────────────────────
# GRADE (resumen por actividad)
# ─────────────────────────────────────────────

class GradeResponse(BaseModel):
    assignment_id: str
    assignment_title: str
    assignment_type: AssignmentType
    due_at: Optional[str] = None
    status: SubmissionStatus = SubmissionStatus.PENDING
    score: Optional[float] = None
    max_score: float = 100.0
    feedback: Optional[str] = None
    submitted_at: Optional[str] = None
    graded_at: Optional[str] = None
