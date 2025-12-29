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
    
    concepto: Optional[str] = Field(
        None,
        description="Concepto del pago (Opcional, se calcula automáticamente)"
    )
    
    numero_cuota: Optional[int] = Field(
        None,
        ge=1,
        description="Número de cuota (Opcional, se calcula automáticamente)"
    )
    
    numero_transaccion: str = Field(
        ...,
        description="Número de transacción bancaria del comprobante"
    )
    
    cantidad_pago: Optional[float] = Field(
        None,
        gt=0,
        description="Monto del pago (Opcional, se calcula automáticamente)"
    )
    
    comprobante_url: str = Field(
        ...,
        description="URL del comprobante/voucher (PDF en Cloudinary)"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "numero_transaccion": "BNB-2024-001234"
            }
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
    
    # ========================================================================
    # DATOS LEGIBLES (como en el reporte Excel)
    # ========================================================================
    
    # Información del estudiante
    nombre_estudiante: Optional[str] = Field(
        None,
        description="Nombre completo del estudiante"
    )
    
    # Información del pago
    fecha: str = Field(
        ...,
        description="Fecha de subida formateada (YYYY-MM-DD HH:MM:SS)"
    )
    
    moneda: str = Field(
        default="Bs",
        description="Moneda del pago (siempre Bolivianos)"
    )
    
    monto: float = Field(
        ...,
        description="Monto del pago en bolivianos"
    )
    
    concepto: str = Field(
        ...,
        description="Concepto del pago (Matrícula, Cuota 1, etc.)"
    )
    
    total_cuotas: Optional[int] = Field(
        None,
        description="Total de cuotas del curso (ej: 12)"
    )
    
    numero_transaccion: str = Field(
        ...,
        description="Número de transacción bancaria"
    )
    
    estado: str = Field(
        ...,
        description="Estado del pago (pendiente/aprobado/rechazado)"
    )
    
    comprobante_url: str = Field(
        ...,
        description="URL del comprobante/voucher (PDF en Cloudinary)"
    )
    
    # ========================================================================
    # CAMPOS TÉCNICOS ADICIONALES
    # ========================================================================
    
    numero_cuota: Optional[int] = Field(
        None,
        description="Número de cuota (si aplica)"
    )
    
    cantidad_pago: float = Field(
        ...,
        description="Monto del pago (mismo que 'monto', para compatibilidad)"
    )
    
    # Comprobante y estado
    
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
                "nombre_estudiante": "María Fernanda López García",
                "fecha": "2024-12-15 14:30:00",
                "moneda": "Bs",
                "monto": 600.0,
                "concepto": "Matrícula",
                "numero_transaccion": "BNB-2024-001234",
                "estado": "pendiente",
                "progreso": "0/12",
                "numero_cuota": None,
                "cantidad_pago": 600.0,
                "comprobante_url": "https://res.cloudinary.com/kyc/voucher_2024_001234.pdf",
                "estado_pago": "pendiente",
                "fecha_subida": "2024-12-15T14:30:00",
                "fecha_verificacion": None,
                "verificado_por": None,
                "motivo_rechazo": None,
                "created_at": "2024-12-15T14:30:00",
                "updated_at": "2024-12-15T14:30:00"
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
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "estado_pago": "aprobado"
            }
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
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "admin_username": "admin.sistemas"
            }
        }
    }


class PaymentRejection(BaseModel):
    """
    Schema específico para rechazar un pago
    
    Uso: PUT /payments/{id}/rechazar
    """
    
    motivo: str = Field(
        ...,
        min_length=1,
        description="Razón del rechazo"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "motivo": "El comprobante está borroso, no se puede leer el número de transacción. Por favor suba una imagen más clara."
            }
        }
    }


class PaymentWithDetails(PaymentResponse):
    """
    Schema para mostrar pago con detalles de Student, Course y Enrollment
    
    Uso: GET /payments/{id}?include_details=True
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
                "estudiante_nombre": "María Fernanda López García",
                "estudiante_email": "maria.lopez@estudiante.edu.bo",
                "curso_id": "507f1f77bcf86cd799439012",
                "curso_nombre": "Diplomado en Sistemas de Gestión de Calidad",
                "curso_codigo": "DIP-SGC-2024",
                "concepto": "Cuota 1",
                "numero_cuota": 1,
                "numero_transaccion": "BNB-2024-002567",
                "cantidad_pago": 478.5,
                "comprobante_url": "https://res.cloudinary.com/kyc/voucher_2024_002567.pdf",
                "estado_pago": "aprobado",
                "fecha_subida": "2024-12-16T10:00:00",
                "fecha_verificacion": "2024-12-16T11:30:00",
                "verificado_por": "admin.sistemas",
                "motivo_rechazo": None,
                "enrollment_total_a_pagar": 2992.5,
                "enrollment_total_pagado": 1078.5,
                "enrollment_saldo_pendiente": 1914.0,
                "created_at": "2024-12-16T10:00:00",
                "updated_at": "2024-12-16T11:30:00"
            }
        }
    }
