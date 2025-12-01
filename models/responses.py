"""
Modelos de Respuesta (DTOs)
===========================

Define modelos para respuestas de API (sin datos sensibles).
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from .enrollment import Enrollment
from .payment import Payment


class StudentResponse(BaseModel):
    """Respuesta de estudiante (sin contraseña)"""
    id: str
    registro: str
    nombre: str
    extension: str
    foto_url: Optional[str]
    celular: str
    carrera: str
    email: str
    fecha_registro: datetime
    activo: bool


class EnrollmentWithDetails(Enrollment):
    """Inscripción con detalles del estudiante y curso"""
    estudiante_nombre: Optional[str] = None
    curso_nombre: Optional[str] = None


class PaymentWithDetails(Payment):
    """Pago con detalles del estudiante y curso"""
    estudiante_nombre: Optional[str] = None
    curso_nombre: Optional[str] = None
