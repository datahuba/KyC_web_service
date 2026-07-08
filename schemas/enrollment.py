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
    # Campos académicos (ISSUE P)
    nota: Optional[float] = None
    estado_academico: Optional[str] = "Cursando"
    # ISSUE-P-RECALCULO-NOTA
    costo_sin_beca_personal: Optional[float] = None
    # ISSUE-Q-NOTA-BORRADOR
    nota_borrador: Optional[float] = None
    estado_validacion_nota: Optional[str] = "sin_borrador"

class ModuloNotaUpdate(BaseModel):
    """Schema para actualizar la calificación de un submódulo (docente -> borrador; CPD/Admin -> oficial directa)"""
    nota: float = Field(..., ge=0, le=100, description="Calificación del módulo (0-100)")

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

    # ISSUE-P-PRECIO-UNICO
    cargo_adicional_monto: Optional[float] = None
    cargo_adicional_concepto: Optional[str] = None
    
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
    matricula_exenta: Optional[bool] = False  # ISSUE-M-EXENCION
    matricula_exenta_otorgada_por: Optional[str] = None  # ISSUE-M-EXENCION
    matricula_exenta_fecha: Optional[datetime] = None  # ISSUE-M-EXENCION
    nota_minima_beca: Optional[float] = None  # ISSUE-P-RECALCULO-NOTA
    beca_respaldo_url: Optional[str] = None  # ISSUE-P-BECA-RESPALDO
    # ISSUE-P-CONGELADO
    motivo_suspension: Optional[str] = None
    fecha_congelamiento: Optional[datetime] = None
    tasa_congelamiento_pagada: Optional[bool] = False
    fecha_abandono: Optional[datetime] = None
    multa_reincorporacion_pendiente: Optional[bool] = False

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
    # AUDITORÍA (BAJO #18): nota_final se eliminó de este schema. Es un campo
    # 100% CALCULADO (promedio de las notas de módulos, ver
    # actualizar_nota_modulo en enrollment_service.py) -- el endpoint nunca
    # lo procesaba aunque el schema lo aceptara, dando la falsa impresión de
    # que se podía editar directamente. Para cambiar la nota de un módulo,
    # usar PATCH /enrollments/{id}/modulos/{index}/nota.

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
    