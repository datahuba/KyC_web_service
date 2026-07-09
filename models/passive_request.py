"""
Modelo de Solicitud de Estado Pasivo (Passive Request)
=======================================================

Representa una solicitud formal para pausar (congelar/abandono temporal) una
inscripción. El flujo es: Encargado de Curso, CPD/Admin o el propio Estudiante
solicitan el pasivo con un motivo y respaldo documental (opcional) -> se
notifica a CPD -> CPD APRUEBA (la inscripción pasa a SUSPENDIDO) o RECHAZA.

No es una baja ni cancelación: el curso, módulos y pagos históricos se
conservan intactos. La inscripción puede reactivarse más adelante.

Colección MongoDB: passive_requests
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class PassiveRequest(MongoBaseModel):
    enrollment_id: PyObjectId = Field(
        ..., description="ID de la inscripción sobre la que se solicita el pasivo"
    )
    solicitante_id: PyObjectId = Field(
        ..., description="ID de quien solicita (User o Student)"
    )
    solicitante_tipo: str = Field(
        ..., description="Tipo de solicitante: 'user' o 'student'"
    )
    motivo: str = Field(
        ..., min_length=3, max_length=500,
        description="Motivo de la solicitud (ej. licencia médica, dificultad económica, etc.)"
    )
    respaldo_url: Optional[str] = Field(
        None, description="URL del documento de respaldo (PDF/imagen), opcional"
    )

    estado: str = Field(
        default="pendiente", description="pendiente | aprobado | rechazado"
    )
    motivo_rechazo: Optional[str] = Field(None, description="Motivo si fue rechazada")
    revisado_por: Optional[str] = Field(None, description="Username del CPD que revisó la solicitud")
    fecha_revision: Optional[datetime] = Field(None, description="Fecha de aprobación/rechazo")

    class Settings:
        name = "passive_requests"
        # AUDITORÍA (MEDIO): use_revision protege contra pisadas de la MISMA
        # solicitud (aprobar/rechazar simultáneo), igual que en Payment.
        use_revision = True
        indexes = [
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            "enrollment_id",
            # AUDITORÍA (MEDIO #10): índice único PARCIAL (solo mientras
            # estado='pendiente') -- evita que dos solicitudes casi
            # simultáneas para la misma inscripción pasen ambas el check
            # "existente" (find-then-insert no atómico). No bloquea el
            # historial normal de solicitudes pasadas ya aprobadas/rechazadas.
            pymongo.IndexModel(
                [("enrollment_id", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={"estado": "pendiente"},
                name="uniq_pendiente_por_enrollment"
            ),
        ]
