"""
Modelo de Pago
=============

Representa un pago individual realizado por un estudiante.
Colección MongoDB: payments
"""

from datetime import datetime
from typing import Optional
from pydantic import Field
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoPago


class Payment(MongoBaseModel):
    """Modelo de Pago - Registra cada transacción de pago"""
    
    inscripcion_id: PyObjectId = Field(..., description="ID de la inscripción")
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    
    numero_transaccion: str = Field(..., description="Número de transacción bancaria")
    concepto: str = Field(..., min_length=1, description="Concepto del pago")
    cantidad_pago: float = Field(..., gt=0, description="Monto del pago")
    descuento_aplicado: Optional[float] = Field(None, ge=0)
    
    imagen_voucher_url: Optional[str] = Field(None, description="URL del voucher")
    estado_pago: EstadoPago = Field(default=EstadoPago.PENDIENTE)
    fecha_subida: datetime = Field(default_factory=datetime.utcnow)
    fecha_pagada: Optional[datetime] = Field(None)
    
    numero_cuota: Optional[int] = Field(None, ge=1, description="Número de cuota")
    
    def aprobar_pago(self):
        self.estado_pago = EstadoPago.PAGADO
        self.fecha_pagada = datetime.utcnow()
        self.updated_at = datetime.utcnow()
    
    def rechazar_pago(self):
        self.estado_pago = EstadoPago.RECHAZADO
        self.updated_at = datetime.utcnow()
