"""
Schemas de Pago (Payment)
=========================

Define los schemas Pydantic para operaciones CRUD de pagos.

Schemas incluidos:
-----------------
1. PaymentCreate: Para crear nuevos pagos
2. PaymentResponse: Para mostrar pagos
3. PaymentUpdate: Para actualizar pagos (admin)
4. PaymentWithDetails: Para mostrar con datos de Student, Course y Enrollment
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from models.enums import EstadoPago
from models.base import PyObjectId


class PaymentCreate(BaseModel):
    """
    Schema para crear un nuevo pago
    
    Uso: POST /payments/
    
    El estudiante sube un comprobante de pago especificando:
    - A qué inscripción corresponde
    - Qué concepto (MATRICULA, CUOTA)
    - Número de transacción bancaria
    - Monto pagado
    - URL del comprobante
    """
    
    inscripcion_id: PyObjectId = Field(
        ...,
        description="ID de la inscripción a la que pertenece este pago"
    )
    
    concepto: str = Field(
        ...,
        min_length=1,
        description="Concepto del pago: 'MATRICULA', 'CUOTA', etc."
    )
    
    numero_cuota: Optional[int] = Field(
        None,
        ge=1,
        description="Número de cuota (1, 2, 3...) si concepto es CUOTA"
    )
    
    numero_transaccion: str = Field(
        ...,
        description="Número de transacción bancaria del comprobante"
    )
    
    cantidad_pago: float = Field(
        ...,
        gt=0,
        description="Monto del pago en Bs"
    )
    
    comprobante_url: str = Field(
        ...,
        description="URL del comprobante/voucher (PDF en Cloudinary)"
    )
    
    descuento_aplicado: Optional[float] = Field(
        None,
        ge=0,
        description="Descuento aplicado en este pago (si aplica)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "concepto": "MATRICULA",
                "numero_cuota": None,
                "numero_transaccion": "TRX-123456789",
                "cantidad_pago": 500.0,
                "comprobante_url": "https://res.cloudinary.com/voucher_123.pdf",
                "descuento_aplicado": None
            }
        }


class PaymentResponse(BaseModel):
    """
    Schema para mostrar información de un pago
    
    Uso: GET /payments/{id}, respuestas de POST/PUT/PATCH
    """
    
    id: PyObjectId = Field(..., alias="_id")
    
    # Referencias
    inscripcion_id: PyObjectId
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    # Tipo de pago
    concepto: str
    numero_cuota: Optional[int]
    
    # Datos de transacción
    numero_transaccion: str
    cantidad_pago: float
    descuento_aplicado: Optional[float]
    
    # Comprobante y estado
    comprobante_url: str
    estado_pago: EstadoPago
    
    # Auditoría
    fecha_subida: datetime
    fecha_verificacion: Optional[datetime]
    verificado_por: Optional[str]
    motivo_rechazo: Optional[str]
    
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
                "concepto": "MATRICULA",
                "numero_cuota": None,
                "numero_transaccion": "TRX-123456789",
                "cantidad_pago": 500.0,
                "descuento_aplicado": None,
                "comprobante_url": "https://res.cloudinary.com/voucher_123.pdf",
                "estado_pago": "pendiente",
                "fecha_subida": "2024-12-11T11:00:00",
                "fecha_verificacion": None,
                "verificado_por": None,
                "motivo_rechazo": None,
                "created_at": "2024-12-11T11:00:00",
                "updated_at": "2024-12-11T11:00:00"
            }
        }
    }


class PaymentUpdate(BaseModel):
    """
    Schema para actualizar un pago (solo admin)
    
    Uso: PATCH /payments/{id}
    
    Típicamente usado para:
    - Aprobar pago
    - Rechazar pago con motivo
    """
    
    estado_pago: Optional[EstadoPago] = Field(
        None,
        description="Cambiar estado del pago"
    )
    
    motivo_rechazo: Optional[str] = Field(
        None,
        description="Motivo de rechazo (si se rechaza)"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "estado_pago": "aprobado",
                "motivo_rechazo": None
            }
        }


class PaymentApproval(BaseModel):
    """
    Schema específico para aprobar un pago
    
    Uso: PUT /payments/{id}/aprobar
    """
    
    admin_username: str = Field(
        ...,
        description="Username del admin que aprueba"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "admin_username": "admin1"
            }
        }


class PaymentRejection(BaseModel):
    """
    Schema específico para rechazar un pago
    
    Uso: PUT /payments/{id}/rechazar
    """
    
    admin_username: str = Field(
        ...,
        description="Username del admin que rechaza"
    )
    
    motivo: str = Field(
        ...,
        min_length=1,
        description="Razón del rechazo"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "admin_username": "admin1",
                "motivo": "El voucher está ilegible, por favor suba uno de mejor calidad"
            }
        }


class PaymentWithDetails(PaymentResponse):
    """
    Schema para mostrar pago con detalles de Student, Course y Enrollment
    
    Uso: GET /payments/{id}?include_details=true
    """
    
    # Datos del estudiante
    estudiante_nombre: Optional[str] = None
    estudiante_email: Optional[str] = None
    
    # Datos del curso
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None
    
    # Datos de inscripción
    enrollment_total_a_pagar: Optional[float] = None
    enrollment_total_pagado: Optional[float] = None
    enrollment_saldo_pendiente: Optional[float] = None
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439014",
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "estudiante_id": "507f1f77bcf86cd799439011",
                "estudiante_nombre": "Juan Pérez",
                "estudiante_email": "juan@email.com",
                "curso_id": "507f1f77bcf86cd799439012",
                "curso_nombre": "Diplomado en Ciencia de Datos",
                "curso_codigo": "DIPL-2024-001",
                "concepto": "MATRICULA",
                "numero_cuota": None,
                "numero_transaccion": "TRX-123456789",
                "cantidad_pago": 500.0,
                "descuento_aplicado": None,
                "comprobante_url": "https://res.cloudinary.com/voucher_123.pdf",
                "estado_pago": "aprobado",
                "fecha_subida": "2024-12-11T11:00:00",
                "fecha_verificacion": "2024-12-11T12:00:00",
                "verificado_por": "admin1",
                "motivo_rechazo": None,
                "enrollment_total_a_pagar": 2565.0,
                "enrollment_total_pagado": 500.0,
                "enrollment_saldo_pendiente": 2065.0,
                "created_at": "2024-12-11T11:00:00",
                "updated_at": "2024-12-11T12:00:00"
            }
        }
    }
