"""
Schemas de Inscripción
======================

Define los schemas Pydantic para operaciones CRUD de inscripciones.

Schemas incluidos:
-----------------
1. EnrollmentCreate: Para inscribir estudiante a curso
2. EnrollmentResponse: Para mostrar inscripción
3. EnrollmentUpdate: Para actualizar inscripción
4. EnrollmentWithDetails: Para mostrar inscripción con detalles enriquecidos
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, validator
from models.enums import EstadoInscripcion, TipoPago, TipoEstudiante
from models.base import PyObjectId


class EnrollmentCreate(BaseModel):
    """
    Schema para crear una nueva inscripción
    
    Uso: POST /enrollments/
    
    ¿Qué incluye?
    ------------
    - IDs del estudiante y curso
    - Tipo de estudiante (para calcular precio)
    - Tipo de pago (contado o cuotas)
    - Descuento personalizado (opcional)
    
    ¿Qué NO incluye?
    ---------------
    - total_a_pagar: Se calcula automáticamente según tipo de estudiante
    - total_pagado: Inicia en 0
    - saldo_pendiente: Se calcula automáticamente
    - fecha_inscripcion: Se asigna al momento de creación
    - estado: Por defecto es ACTIVO
    """
    
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    es_estudiante_interno: TipoEstudiante = Field(
        ...,
        description="Tipo de estudiante al momento de inscripción"
    )
    tipo_pago: TipoPago = Field(..., description="Contado o cuotas")
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Descuento adicional personalizado (porcentaje)"
    )
    formulario_inscripcion_url: Optional[str] = Field(
        None,
        description="URL del PDF de inscripción firmado"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "es_estudiante_interno": "interno",
                "tipo_pago": "cuotas",
                "descuento_personalizado": 5.0,
                "formulario_inscripcion_url": "https://storage.example.com/forms/inscripcion_001.pdf"
            }
        }


class EnrollmentResponse(BaseModel):
    """
    Schema para mostrar información de una inscripción
    
    Uso: GET /enrollments/{id}, respuestas de POST/PUT/PATCH
    
    Incluye todos los campos de la inscripción.
    """
    
    id: PyObjectId = Field(..., alias="_id")
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    fecha_inscripcion: datetime
    estado: EstadoInscripcion
    es_estudiante_interno: TipoEstudiante
    formulario_inscripcion_url: Optional[str]
    
    descuento_personalizado: Optional[float]
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    tipo_pago: TipoPago
    
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
                "fecha_inscripcion": "2024-02-01T10:00:00",
                "estado": "activo",
                "es_estudiante_interno": "interno",
                "formulario_inscripcion_url": "https://storage.example.com/forms/inscripcion_001.pdf",
                "descuento_personalizado": 5.0,
                "total_a_pagar": 2850.0,
                "total_pagado": 500.0,
                "saldo_pendiente": 2350.0,
                "tipo_pago": "cuotas",
                "created_at": "2024-02-01T10:00:00",
                "updated_at": "2024-02-01T10:00:00"
            }
        }
    }


class EnrollmentUpdate(BaseModel):
    """
    Schema para actualizar una inscripción existente
    
    Uso: PATCH /enrollments/{id}
    
    Permite actualizar estado, descuentos, y otros campos.
    Los montos generalmente se actualizan a través de pagos.
    """
    
    estado: Optional[EstadoInscripcion] = None
    formulario_inscripcion_url: Optional[str] = None
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    total_a_pagar: Optional[float] = Field(None, gt=0)
    total_pagado: Optional[float] = Field(None, ge=0)
    saldo_pendiente: Optional[float] = Field(None, ge=0)
    
    @validator('saldo_pendiente')
    def validar_saldo(cls, v, values):
        """Valida que el saldo sea coherente con total y pagado"""
        if 'total_a_pagar' in values and 'total_pagado' in values:
            esperado = values['total_a_pagar'] - values['total_pagado']
            if abs(v - esperado) > 0.01:
                raise ValueError(f"Saldo inválido: {v} vs esperado {esperado:.2f}")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "estado": "completado",
                "total_pagado": 2850.0,
                "saldo_pendiente": 0.0
            }
        }


class EnrollmentWithDetails(EnrollmentResponse):
    """
    Schema enriquecido de inscripción con detalles del estudiante y curso
    
    Uso: GET /enrollments/ (listados), reportes
    
    ¿Por qué este schema?
    --------------------
    Evita hacer múltiples llamadas a la API para obtener información
    contextual. En lugar de:
    
    1. GET /enrollments/{id} → obtener enrollment
    2. GET /students/{estudiante_id} → obtener nombre del estudiante
    3. GET /courses/{curso_id} → obtener nombre del curso
    
    Hacemos:
    1. GET /enrollments/{id}?include_details=true → todo en una llamada
    
    ¿Qué agrega?
    -----------
    - estudiante_nombre: Nombre completo del estudiante
    - estudiante_email: Email del estudiante
    - estudiante_registro: Registro del estudiante
    - curso_nombre: Nombre del programa
    - curso_codigo: Código del curso
    """
    
    # Detalles del estudiante
    estudiante_nombre: Optional[str] = Field(
        None,
        description="Nombre completo del estudiante"
    )
    estudiante_email: Optional[str] = Field(
        None,
        description="Email del estudiante"
    )
    estudiante_registro: Optional[str] = Field(
        None,
        description="Registro del estudiante"
    )
    
    # Detalles del curso
    curso_nombre: Optional[str] = Field(
        None,
        description="Nombre del programa"
    )
    curso_codigo: Optional[str] = Field(
        None,
        description="Código del curso"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "fecha_inscripcion": "2024-02-01T10:00:00",
                "estado": "activo",
                "es_estudiante_interno": "interno",
                "formulario_inscripcion_url": "https://storage.example.com/forms/inscripcion_001.pdf",
                "descuento_personalizado": 5.0,
                "total_a_pagar": 2850.0,
                "total_pagado": 500.0,
                "saldo_pendiente": 2350.0,
                "tipo_pago": "cuotas",
                "created_at": "2024-02-01T10:00:00",
                "updated_at": "2024-02-01T10:00:00",
                # Campos adicionales
                "estudiante_nombre": "Juan Pérez García",
                "estudiante_email": "juan.perez@example.com",
                "estudiante_registro": "EST-2024-001",
                "curso_nombre": "Diplomado en Ciencia de Datos",
                "curso_codigo": "DIPL-2024-001"
            }
        }
