"""
Modelo de Solicitud de Inscripción (Enrollment Request)
=========================================================

ISSUE-R-SOLICITUD-INSCRIPCION: El estudiante no puede inscribirse a un curso
directamente (la inscripción real la crea CPD/Encargado de Curso vía
POST /enrollments/, que valida KYC, matrícula y estructura de pago). En su
lugar, el estudiante SOLICITA cursar un programa desde su perfil, y CPD
aprueba (creando la inscripción real) o rechaza con motivo.

Mismo patrón que PassiveRequest/AccountRequest: solicitud -> notificación a
CPD -> aprobación/rechazo.

Colección MongoDB: enrollment_requests
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class EnrollmentRequest(MongoBaseModel):
    estudiante_id: PyObjectId = Field(
        ..., description="ID del estudiante que solicita inscribirse"
    )
    curso_id: PyObjectId = Field(
        ..., description="ID del curso al que solicita inscribirse"
    )
    mensaje: Optional[str] = Field(
        None, max_length=500,
        description="Comentario opcional del estudiante (ej. duda sobre el horario)"
    )

    estado: str = Field(
        default="pendiente", description="pendiente | aprobado | rechazado"
    )
    motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazada")
    revisado_por: Optional[str] = Field(None, description="Username del CPD que revisó la solicitud")
    fecha_revision: Optional[datetime] = Field(None, description="Fecha de aprobación/rechazo")
    enrollment_id: Optional[PyObjectId] = Field(
        None, description="ID de la inscripción creada al aprobar (si fue aprobada)"
    )

    class Settings:
        name = "enrollment_requests"
        # AUDITORÍA (MEDIO): use_revision protege contra pisadas de la MISMA
        # solicitud (aprobar/rechazar simultáneo), igual que en Payment.
        use_revision = True
        indexes = [
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            "estudiante_id",
            "curso_id",
            # AUDITORÍA (MEDIO #10): índice único PARCIAL (solo mientras
            # estado='pendiente') -- ver misma nota en passive_request.py.
            pymongo.IndexModel(
                [("estudiante_id", pymongo.ASCENDING), ("curso_id", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={"estado": "pendiente"},
                name="uniq_pendiente_por_estudiante_curso"
            ),
        ]
