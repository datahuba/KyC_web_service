"""
Schemas de Solicitud de Inscripción (Enrollment Request)
==========================================================
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from models.base import PyObjectId


class EnrollmentRequestCreate(BaseModel):
    """Uso: POST /enrollment-requests/ (el estudiante solicita cursar un programa)"""
    curso_id: PyObjectId = Field(..., description="ID del curso al que desea inscribirse")
    mensaje: Optional[str] = Field(None, max_length=500, description="Comentario opcional")

    model_config = {
        "json_schema_extra": {
            "example": {
                "curso_id": "507f1f77bcf86cd799439012",
                "mensaje": "Quisiera confirmar el horario del módulo 1"
            }
        }
    }


class EnrollmentRequestReject(BaseModel):
    """Uso: POST /enrollment-requests/{id}/reject"""
    motivo: str = Field(..., min_length=3, max_length=500, description="Motivo del rechazo")


class EnrollmentRequestResponse(BaseModel):
    """Uso: GET /enrollment-requests/"""
    id: PyObjectId = Field(..., alias="_id")
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    mensaje: Optional[str] = None
    estado: str
    motivo_rechazo: Optional[str] = None
    revisado_por: Optional[str] = None
    fecha_revision: Optional[datetime] = None
    enrollment_id: Optional[PyObjectId] = None
    created_at: datetime
    updated_at: datetime

    # Enriquecido para la vista de CPD (nombre real en vez de solo el ObjectId)
    estudiante_nombre: Optional[str] = None
    estudiante_registro: Optional[str] = None
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }
