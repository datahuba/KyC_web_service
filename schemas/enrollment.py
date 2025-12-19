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
    
    SISTEMA DE DOBLE DESCUENTO:
    ---------------------------
    1. Descuento del Curso (AUTOMÁTICO):
       - Se aplica automáticamente desde Course.descuento_id
       - No necesitas enviarlo, el sistema lo obtiene del curso
    
    2. Descuento del Estudiante (OPCIONAL):
       - Debes enviarlo en descuento_id O descuento_personalizado
       - Se aplica DESPUÉS del descuento del curso (acumulativo)
    
    Ejemplo de cálculo:
    - Precio base: 3000 Bs
    - Descuento curso (10%): 3000 - 300 = 2700 Bs
    - Descuento estudiante (5%): 2700 - 135 = 2565 Bs FINAL
    
    El sistema calculará automáticamente:
    - costo_total (desde Course según es_estudiante_interno)
    - costo_matricula (desde Course)
    - cantidad_cuotas (desde Course)
    - descuento_curso_aplicado (desde Course.descuento_id - AUTOMÁTICO)
    - descuento_personalizado (desde descuento_id o porcentaje manual)
    - total_a_pagar (aplicando AMBOS descuentos en cascada)
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
    
    descuento_id: Optional[PyObjectId] = Field(
        None,
        description="ID del descuento PERSONALIZADO del estudiante (opcional, nivel 2)"
    )
    
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Porcentaje de descuento manual (solo si no se usa descuento_id, nivel 2)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "descuento_id": "507f1f77bcf86cd799439088"
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
    descuento_curso_id: Optional[PyObjectId] = None
    descuento_curso_aplicado: float
    
    descuento_estudiante_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float]
    
    # Totales
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    
    # Estado
    fecha_inscripcion: datetime
    estado: EstadoInscripcion
    
    # Nota Final
    nota_final: Optional[float] = None
    
    # Información de Siguiente Pago (Calculado)
    siguiente_pago: Optional[dict] = Field(
        None,
        description="Detalles sugeridos para el próximo pago (concepto, monto, cuota)"
    )
    
    # Información de Progreso de Cuotas (Calculado)
    cuotas_pagadas_info: Optional[dict] = Field(
        None,
        description="Progreso de pago de cuotas (cuotas_pagadas, cuotas_totales, porcentaje)"
    )
    
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
                "total_pagado": 1000.0,
                "saldo_pendiente": 1565.0,
                "fecha_inscripcion": "2024-12-11T10:00:00",
                "estado": "activo",
                "nota_final": 85.5,
                "siguiente_pago": {
                    "concepto": "Cuota 3",
                    "numero_cuota": 3,
                    "monto_sugerido": 413.0
                },
                "cuotas_pagadas_info": {
                    "cuotas_pagadas": 2,
                    "cuotas_totales": 5,
                    "porcentaje": 40.0
                },
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
    
    descuento_id: Optional[PyObjectId] = Field(
        None,
        description="Actualizar descuento de estudiante (reemplaza snapshot)"
    )
    
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Actualizar porcentaje manual"
    )
    
    estado: Optional[EstadoInscripcion] = Field(
        None,
        description="Cambiar estado de la inscripción"
    )
    
    nota_final: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Nota final del estudiante (0-100)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "descuento_personalizado": 10.0,
                "estado": "activo",
                "nota_final": 85.5
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
