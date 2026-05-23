"""
Schemas de Inscripción (Enrollment)
===================================
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from models.enums import EstadoInscripcion, TipoEstudiante
from models.base import PyObjectId

# NUEVO SCHEMA PARA MÓDULOS DE INSCRIPCIÓN
class ModuloEstadoSchema(BaseModel):
    nombre: str
    costo: float
    estado: str
    monto_pagado: float

class EnrollmentCreate(BaseModel):
    """Schema para crear una nueva inscripción"""
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante a inscribir")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    descuento_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012"
            }
        }
    }

class EnrollmentResponse(BaseModel):
    """Schema para mostrar información de una inscripción"""
    id: PyObjectId = Field(..., alias="_id")
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    # Snapshot de precios y módulos
    es_estudiante_interno: TipoEstudiante
    costo_total: float
    costo_matricula: float
    cantidad_cuotas: int
    modulos: List[ModuloEstadoSchema] = Field(default_factory=list)
    
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
    nota_final: Optional[float] = None
    
    # Información Calculada
    siguiente_pago: Optional[dict] = None
    cuotas_pagadas_info: Optional[dict] = None
    
    created_at: datetime
    updated_at: datetime
    
    matricula_pagada: Optional[bool] = False

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }

class EnrollmentUpdate(BaseModel):
    """Schema para actualizar una inscripción existente"""
    descuento_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    estado: Optional[EstadoInscripcion] = None
    nota_final: Optional[float] = Field(None, ge=0, le=100)

class EnrollmentWithDetails(EnrollmentResponse):
    """Schema para mostrar inscripción con detalles de Student y Course"""
    estudiante_nombre: Optional[str] = None
    estudiante_email: Optional[str] = None
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None
    monto_cuota: Optional[float] = None
    porcentaje_pagado: Optional[float] = None
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }