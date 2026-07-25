"""
Modelos de Base de Datos para Sistema de Pagos de Cursos de Posgrado
=====================================================================

Este paquete contiene todos los modelos de datos usando Pydantic para validación
y MongoDB como base de datos.

Estructura:
-----------
- base.py: Modelo base y utilidades compartidas
- enums.py: Enumeraciones utilizadas en los modelos
- student.py: Modelo de Estudiante
- course.py: Modelo de Curso
- enrollment.py: Modelo de Inscripción
- payment.py: Modelo de Pago
- discount.py: Modelo de Descuento
- title.py: Modelo de Título/Certificado
- user.py: Modelo de Usuario
"""

from .base import MongoBaseModel, PyObjectId
from .enums import (
    TipoCurso,
    Modalidad,
    EstadoInscripcion,
    TipoPago,
    EstadoPago,
    TipoTitulo,
    EstadoRequisito,  # Nuevo
    UserRole
)
from .student import Student
from .course import Course
from .enrollment import Enrollment
from .payment import Payment
from .payment_config import PaymentConfig
from .discount import Discount
from .title import Title
from .user import User
from .requisito import Requisito, RequisitoTemplate  # Nuevo
from .error_log import ErrorLog  # F-044 (2026-07-22)

__all__ = [
    # Base
    "MongoBaseModel",
    "PyObjectId",

    # Enums
    "TipoCurso",
    "Modalidad",
    "EstadoInscripcion",
    "TipoPago",
    "EstadoPago",
    "TipoTitulo",
    "EstadoRequisito",  # Nuevo
    "UserRole",

    # Models
    "Student",
    "Course",
    "Enrollment",
    "Payment",
    "PaymentConfig",
    "Discount",
    "Title",
    "User",
    "ErrorLog",  # F-044

    # Embedded Models
    "Requisito",          # Nuevo
    "RequisitoTemplate",  # Nuevo
]
