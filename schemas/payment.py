"""
Schemas de Pago
===============

Define los schemas Pydantic para operaciones CRUD de pagos.

Schemas incluidos:
-----------------
1. PaymentCreate: Para registrar un nuevo pago
2. PaymentResponse: Para mostrar pago
3. PaymentUpdate: Para actualizar pago
4. PaymentWithDetails: Para mostrar pago con detalles enriquecidos
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from models.enums import EstadoPago
from models.base import PyObjectId


class PaymentCreate(BaseModel):
    """
    Schema para registrar un nuevo pago
    
    Uso: POST /payments/
    
    ¿Qué incluye?
    ------------
    - IDs de inscripción, estudiante y curso
    - Información del pago (número transacción, concepto, cantidad)
    - Voucher (imagen del comprobante)
    - Número de cuota (si aplica)
    
    ¿Qué NO incluye?
    ---------------
    - estado_pago: Por defecto es PENDIENTE
    - fecha_subida: Se asigna al momento de creación
    - fecha_pagada: Se asigna cuando se aprueba el pago
    """
    
    inscripcion_id: PyObjectId = Field(..., description="ID de la inscripción")
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    
    numero_transaccion: str = Field(
        ...,
        description="Número de transacción bancaria"
    )
    concepto: str = Field(
        ...,
        min_length=1,
        description="Concepto del pago (ej: 'Matrícula', 'Cuota 1/5')"
    )
    cantidad_pago: float = Field(
        ...,
        gt=0,
        description="Monto del pago"
    )
    descuento_aplicado: Optional[float] = Field(
        None,
        ge=0,
        description="Descuento aplicado en este pago específico"
    )
    imagen_voucher_url: Optional[str] = Field(
        None,
        description="URL de la imagen del voucher/comprobante"
    )
    numero_cuota: Optional[int] = Field(
        None,
        ge=1,
        description="Número de cuota (si es pago de cuota)"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "numero_transaccion": "TRX-2024-001234",
                "concepto": "Matrícula - Diplomado en Ciencia de Datos",
                "cantidad_pago": 500.0,
                "descuento_aplicado": 0.0,
                "imagen_voucher_url": "https://storage.example.com/vouchers/voucher_001.jpg",
                "numero_cuota": None
            }
        }


class PaymentResponse(BaseModel):
    """
    Schema para mostrar información de un pago
    
    Uso: GET /payments/{id}, respuestas de POST/PUT/PATCH
    
    Incluye todos los campos del pago.
    """
    
    id: PyObjectId = Field(..., alias="_id")
    inscripcion_id: PyObjectId
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    numero_transaccion: str
    concepto: str
    cantidad_pago: float
    descuento_aplicado: Optional[float]
    
    imagen_voucher_url: Optional[str]
    estado_pago: EstadoPago
    fecha_subida: datetime
    fecha_pagada: Optional[datetime]
    
    numero_cuota: Optional[int]
    
    created_at: datetime
    updated_at: datetime
    
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439014",
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "numero_transaccion": "TRX-2024-001234",
                "concepto": "Matrícula - Diplomado en Ciencia de Datos",
                "cantidad_pago": 500.0,
                "descuento_aplicado": 0.0,
                "imagen_voucher_url": "https://storage.example.com/vouchers/voucher_001.jpg",
                "estado_pago": "pendiente",
                "fecha_subida": "2024-02-01T11:00:00",
                "fecha_pagada": None,
                "numero_cuota": None,
                "created_at": "2024-02-01T11:00:00",
                "updated_at": "2024-02-01T11:00:00"
            }
        }
    }


class PaymentUpdate(BaseModel):
    """
    Schema para actualizar un pago existente
    
    Uso: PATCH /payments/{id}
    
    Permite actualizar estado, voucher, y otros campos.
    Comúnmente usado para aprobar/rechazar pagos.
    """
    
    numero_transaccion: Optional[str] = None
    concepto: Optional[str] = Field(None, min_length=1)
    cantidad_pago: Optional[float] = Field(None, gt=0)
    descuento_aplicado: Optional[float] = Field(None, ge=0)
    imagen_voucher_url: Optional[str] = None
    estado_pago: Optional[EstadoPago] = None
    fecha_pagada: Optional[datetime] = None
    numero_cuota: Optional[int] = Field(None, ge=1)
    
    class Config:
        schema_extra = {
            "example": {
                "estado_pago": "aceptado",
                "fecha_pagada": "2024-02-02T09:00:00"
            }
        }


class PaymentWithDetails(PaymentResponse):
    """
    Schema enriquecido de pago con detalles del estudiante y curso
    
    Uso: GET /payments/ (listados), reportes financieros
    
    ¿Por qué este schema?
    --------------------
    Facilita la generación de reportes financieros sin hacer múltiples
    llamadas a la API. Especialmente útil para:
    - Listados de pagos pendientes de aprobación
    - Reportes de ingresos por curso
    - Historial de pagos de un estudiante
    
    ¿Qué agrega?
    -----------
    - estudiante_nombre: Nombre del estudiante que pagó
    - estudiante_registro: Registro del estudiante
    - curso_nombre: Nombre del curso
    - curso_codigo: Código del curso
    - saldo_restante: Cuánto falta por pagar en la inscripción
    """
    
    # Detalles del estudiante
    estudiante_nombre: Optional[str] = Field(
        None,
        description="Nombre completo del estudiante"
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
    
    # Información financiera adicional
    saldo_restante: Optional[float] = Field(
        None,
        description="Saldo pendiente de la inscripción después de este pago"
    )
    
    class Config:
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439014",
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012",
                "numero_transaccion": "TRX-2024-001234",
                "concepto": "Matrícula - Diplomado en Ciencia de Datos",
                "cantidad_pago": 500.0,
                "descuento_aplicado": 0.0,
                "imagen_voucher_url": "https://storage.example.com/vouchers/voucher_001.jpg",
                "estado_pago": "aceptado",
                "fecha_subida": "2024-02-01T11:00:00",
                "fecha_pagada": "2024-02-02T09:00:00",
                "numero_cuota": None,
                "created_at": "2024-02-01T11:00:00",
                "updated_at": "2024-02-02T09:00:00",
                # Campos adicionales
                "estudiante_nombre": "Juan Pérez García",
                "estudiante_registro": "EST-2024-001",
                "curso_nombre": "Diplomado en Ciencia de Datos",
                "curso_codigo": "DIPL-2024-001",
                "saldo_restante": 2350.0
            }
        }
