"""
Schemas Package
===============

Este paquete contiene todos los schemas Pydantic para la API.

¿Qué son los schemas?
--------------------
Los schemas definen la estructura de datos para las peticiones y respuestas
de la API. Son diferentes de los modelos de base de datos.

Diferencia entre models/ y schemas/:
-----------------------------------
- models/: Cómo se almacenan los datos en MongoDB (estructura de BD)
- schemas/: Cómo se envían/reciben los datos en la API (contratos de API)

Organización:
------------
Cada entidad tiene mínimo 3 schemas:
1. *Create: Para crear nuevos registros (POST)
2. *Response: Para mostrar datos (GET, respuestas)
3. *Update: Para actualizar registros (PATCH/PUT)

Algunos tienen schemas adicionales:
4. *WithDetails: Para respuestas enriquecidas con información relacionada
"""

# Student schemas
from .student import (
    StudentCreate,
    StudentResponse,
    StudentUpdateSelf,
    StudentUpdateAdmin,
    ChangePassword
)

# Course schemas
from .course import (
    CourseCreate,
    CourseResponse,
    CourseUpdate
)

# Enrollment schemas
from .enrollment import (
    EnrollmentCreate,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithDetails
)

# Payment schemas
from .payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentUpdate,
    PaymentWithDetails,
    PaymentApproval,
    PaymentRejection
)

# Discount schemas
from .discount import (
    DiscountCreate,
    DiscountResponse,
    DiscountUpdate
)

# User schemas
from .user import (
    UserCreate,
    UserResponse,
    UserUpdate
)

__all__ = [
    # Student
    "StudentCreate",
    "StudentResponse",
    "StudentUpdateSelf",
    "StudentUpdateAdmin",
    "ChangePassword",
    # Course
    "CourseCreate",
    "CourseResponse",
    "CourseUpdate",
    # Enrollment
    "EnrollmentCreate",
    "EnrollmentResponse",
    "EnrollmentUpdate",
    "EnrollmentWithDetails",
    # Payment
    "PaymentCreate",
    "PaymentResponse",
    "PaymentUpdate",
    "PaymentWithDetails",
    "PaymentApproval",
    "PaymentRejection",
    # Discount
    "DiscountCreate",
    "DiscountResponse",
    "DiscountUpdate",
    # User
    "UserCreate",
    "UserResponse",
    "UserUpdate",
]
