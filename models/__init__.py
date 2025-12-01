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
    TipoEstudiante,
    UserRole
)
from .student import Student
from .course import Course
from .enrollment import Enrollment
from .payment import Payment
from .discount import Discount
from .title import Title
from .user import User

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
    "TipoEstudiante",
    "UserRole",
    
    # Models
    "Student",
    "Course",
    "Enrollment",
    "Payment",
    "Discount",
    "Title",
    "User",
]
