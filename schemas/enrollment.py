"""
Schemas de Inscripción (Enrollment)
===================================

Define los schemas Pydantic para operaciones CRUD de inscripciones.

Schemas incluidos:
-----------------
1. EnrollmentCreate: Para crear nuevas inscripciones
2. EnrollmentResponse: Para mostrar inscripciones
3. EnrollmentUpdate: Para actualizar inscripciones
4. EnrollmentWithDetails: Para mostrar con datos de Student y Course
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from models.enums import EstadoInscripcion, TipoEstudiante
from models.base import PyObjectId


class EnrollmentCreate(BaseModel):
    """
    Schema para crear una nueva inscripción
    
    Uso: POST /enrollments/
    
    El sistema calculará automáticamente:
    - costo_total (desde Course según es_estudiante_interno)
    - costo_matricula (desde Course)
    - cantidad_cuotas (desde Course)
    - descuento_curso_aplicado (desde Course.descuento_curso)
    - total_a_pagar (aplicando descuentos)
    - saldo_pendiente (= total_a_pagar al inicio)
    """
    
    estudiante_id: PyObjectId = Field(
        ...,
        description="ID del estudiante a inscribir"
    )
    
    curso_id: PyObjectId = Field(
        ...,
        description="ID del curso"
    )
    
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Descuento adicional personalizado (%) dado por el admin"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "descuento_personalizado": 5.0
            }
        }


class EnrollmentResponse(BaseModel):
    """
    Schema para mostrar información de una inscripción
    
    Uso: GET /enrollments/{id}, respuestas de POST/PUT/PATCH
    """
    
    id: PyObjectId = Field(..., alias="_id")
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    # Snapshot de precios
    es_estudiante_interno: TipoEstudiante
    costo_total: float
    costo_matricula: float
    cantidad_cuotas: int
    
    # Descuentos
    descuento_curso_aplicado: float
    descuento_personalizado: Optional[float]
    
    # Totales
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    
    # Estado
    fecha_inscripcion: datetime
    estado: EstadoInscripcion
    
    created_at: datetime
    updated_at: datetime
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "es_estudiante_interno": "interno",
                "costo_total": 3000.0,
                "costo_matricula": 500.0,
                "cantidad_cuotas": 5,
                "descuento_curso_aplicado": 10.0,
                "descuento_personalizado": 5.0,
                "total_a_pagar": 2565.0,
                "total_pagado": 0.0,
                "saldo_pendiente": 2565.0,
                "fecha_inscripcion": "2024-12-11T10:00:00",
                "estado": "pendiente_pago",
                "created_at": "2024-12-11T10:00:00",
                "updated_at": "2024-12-11T10:00:00"
            }
        }
    }


class EnrollmentUpdate(BaseModel):
    """
    Schema para actualizar una inscripción existente
    
    Uso: PATCH /enrollments/{id}
    
    Nota: Los campos financieros (total_pagado, saldo_pendiente)
    se actualizan automáticamente cuando se aprueba un pago.
    """
    
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Actualizar descuento personalizado"
    )
    
    estado: Optional[EstadoInscripcion] = Field(
        None,
        description="Cambiar estado de la inscripción"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "descuento_personalizado": 10.0,
                "estado": "activo"
            }
        }


class EnrollmentWithDetails(EnrollmentResponse):
    """
    Schema para mostrar inscripción con detalles de Student y Course
    
    Uso: GET /enrollments/{id}?include_details=true
    
    Incluye datos calculados adicionales:
    - nombre del estudiante
    - nombre del curso
    - monto de cada cuota
    - porcentaje de avance en pagos
    """
    
    # Datos del estudiante (expandidos)
    estudiante_nombre: Optional[str] = None
    estudiante_email: Optional[str] = None
    
    # Datos del curso (expandidos)
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None
    
    # Calculados
    monto_cuota: Optional[float] = Field(
        None,
        description="Monto de cada cuota (calculado)"
    )
    
    porcentaje_pagado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Porcentaje pagado del total"
    )
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "estudiante_nombre": "Juan Pérez",
                "estudiante_email": "juan@email.com",
                "curso_id": "507f1f77bcf86cd799439012",
                "curso_nombre": "Diplomado en Ciencia de Datos",
                "curso_codigo": "DIPL-2024-001",
                "es_estudiante_interno": "interno",
                "costo_total": 3000.0,
                "costo_matricula": 500.0,
                "cantidad_cuotas": 5,
                "descuento_curso_aplicado": 10.0,
                "descuento_personalizado": 5.0,
                "total_a_pagar": 2565.0,
                "total_pagado": 1000.0,
                "saldo_pendiente": 1565.0,
                "monto_cuota": 413.0,
                "porcentaje_pagado": 38.99,
                "fecha_inscripcion": "2024-12-11T10:00:00",
                "estado": "activo",
                "created_at": "2024-12-11T10:00:00",
                "updated_at": "2024-12-11T10:00:00"
            }
        }
    }
