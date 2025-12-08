"""
Modelo de Inscripción
====================

Representa la inscripción de un estudiante a un curso específico.
Colección MongoDB: enrollments
"""

from datetime import datetime
from typing import Optional, List
from pydantic import Field, validator
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoInscripcion, TipoPago, TipoEstudiante


class Enrollment(MongoBaseModel):
    """Modelo de Inscripción - Vincula estudiante con curso"""
    
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    
    fecha_inscripcion: datetime = Field(default_factory=datetime.utcnow)
    estado: EstadoInscripcion = Field(default=EstadoInscripcion.ACTIVO)
    es_estudiante_interno: TipoEstudiante = Field(..., description="Tipo al momento de inscripción")
    formulario_inscripcion_url: Optional[str] = Field(None, description="URL del PDF de inscripción")
    
    # Documentos de pago y requisitos específicos de esta inscripción
    comprobante_matricula_url: Optional[str] = Field(None, description="URL del Comprobante de Pago de la Matrícula")
    comprobante_modulo_url: Optional[str] = Field(None, description="URL del Comprobante de Pago del módulo")
    requisitos_url: Optional[List[str]] = Field(default_factory=list, description="URLs de requisitos de inscripción (fotocopias simples)")
    
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    total_a_pagar: float = Field(..., gt=0)
    total_pagado: float = Field(default=0.0, ge=0)
    saldo_pendiente: float = Field(..., ge=0)
    tipo_pago: TipoPago = Field(...)
    
    @validator('saldo_pendiente')
    def validar_saldo(cls, v, values):
        if 'total_a_pagar' in values and 'total_pagado' in values:
            esperado = values['total_a_pagar'] - values['total_pagado']
            if abs(v - esperado) > 0.01:
                raise ValueError(f"Saldo inválido: {v} vs esperado {esperado:.2f}")
        return v
    
    def actualizar_saldo(self, monto_pago: float):
        self.total_pagado += monto_pago
        self.saldo_pendiente = max(0, self.total_a_pagar - self.total_pagado)
        self.updated_at = datetime.utcnow()

    class Settings:
        name = "enrollments"
