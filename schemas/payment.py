"""
Schemas de Pago (Payment)
=========================

Define los schemas Pydantic para operaciones CRUD de pagos.
"""

from datetime import datetime
from typing import Optional, Dict
from pydantic import BaseModel, Field
from models.enums import EstadoPago
from models.base import PyObjectId


class PaymentCreate(BaseModel):
    """
    Schema para crear un nuevo pago
    Uso: POST /payments/
    """
    
    inscripcion_id: PyObjectId = Field(
        ...,
        description="ID de la inscripción a la que pertenece este pago"
    )

    # 1. ISSUE-P-CANALES: Canal de pago dinámico
    metodo_pago: str = Field(
        default="Transferencia",
        description="Puede ser: Transferencia, Depósito o Caja"
    )

    # El número de transacción ya no es obligatorio si el método es Caja
    numero_transaccion: Optional[str] = Field(
        None,
        description="Número de transacción bancaria (Nulo si fue en Caja)"
    )

    remitente: Optional[str] = Field(
        None,
        description="Nombre de la persona que figura en el voucher o pagó en caja"
    )

    banco: Optional[str] = Field(
        None,
        description="Nombre del banco (Nulo si fue en Caja)"
    )
    
    monto_comprobante: float = Field(
        ...,
        gt=0,
        description="Monto real del pago (en bolivianos)"
    )
    
    fecha_comprobante: Optional[str] = Field(
        None,
        description="Fecha del comprobante (YYYY-MM-DD)"
    )
    
    cuenta_destino: Optional[str] = Field(
        None,
        description="Número de cuenta institucional o código de Caja"
    )

    concepto: Optional[str] = Field(
        None,
        description="Concepto (Matrícula, Módulo)"
    )
    
    numero_cuota: Optional[int] = Field(
        None,
        description="Número de cuota"
    )
    
    cantidad_pago: Optional[float] = Field(
        None,
        description="Monto del pago (igual al monto_comprobante)"
    )

    # F-SYNC-PAGOS-MODULOS (2026-08-04, Kevin): sincronizar el endpoint de pagos
    # con la logica del modal de carga inicial. Si viene este dict, el backend
    # aplica los pagos directo a los modulos (en vez de prorratear en cascada
    # con get_next_pending_payment). Llave = indice del modulo (0-based string),
    # valor = monto a aplicar a ese modulo.
    # Ej: {"0": 294, "1": 294} = paga modulo 1 y 2 completos.
    pagos_modulos: Optional[Dict[str, float]] = Field(
        default=None,
        description="Dict {modulo_index_str: monto_pagado}. Si viene, se aplica directo a los modulos en vez de prorratear."
    )

    # F-SYNC-PAGOS-MODULOS (2026-08-04, Kevin): detalle desglosado por modulo.
    # Ej: "Módulo 1: Bs 294, Módulo 2: Bs 294". Se genera automaticamente si
    # el caller envio pagos_modulos.
    detalle: Optional[str] = Field(
        default=None,
        description="Detalle desglosado del pago. Ej: 'Módulo 1: Bs 294, Módulo 2: Bs 294'."
    )

    comprobante_url: Optional[str] = Field(
        None,
        description="URL del comprobante/voucher. Nulo si el pago fue en Caja."
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "inscripcion_id": "507f1f77bcf86cd799439013",
                "metodo_pago": "Caja",
                "monto_comprobante": 1000.0
            }
        }
    }


class PaymentResponse(BaseModel):
    """
    Schema para mostrar información de un pago
    Uso: GET /payments/{id}, respuestas de POST/PUT/PATCH
    """
    
    id: PyObjectId = Field(..., alias="_id")
    
    inscripcion_id: PyObjectId
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    nombre_estudiante: Optional[str] = None
    fecha: str
    moneda: str = "Bs"
    monto: float
    concepto: str
    # F-COBRANZA-039 (2026-07-22): faltaba este campo en el schema, por lo que el
    # endpoint /payments/{id} y los listados NO retornaban el detalle de la glosa.
    # Bug detectado al regenerar glosas de los 6 pagos con descuento (F-038): los
    # detalles regenerados NO aparecian en el modal de detalle del pago. Fix:
    # agregar el campo al schema PaymentResponse.
    detalle: Optional[str] = None
    total_cuotas: Optional[int] = None
    
    # ISSUE-P-CANALES
    metodo_pago: str
    numero_transaccion: Optional[str] = None
    remitente: Optional[str] = None
    banco: Optional[str] = None
    monto_comprobante: Optional[float] = None
    fecha_comprobante: Optional[datetime] = None
    cuenta_destino: Optional[str] = None
    
    estado: str
    comprobante_url: Optional[str] = None
    
    numero_cuota: Optional[int] = None
    cantidad_pago: float
    estado_pago: EstadoPago
    
    fecha_subida: datetime
    fecha_verificacion: Optional[datetime] = None
    verificado_por: Optional[str] = None
    motivo_rechazo: Optional[str] = None
    motivo_reversion: Optional[str] = None
    
    created_at: datetime
    updated_at: datetime

    en_ventana_reversion: bool = False  # ISSUE-P-REVERSION
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class PaymentUpdate(BaseModel):
    estado_pago: Optional[EstadoPago] = None
    motivo_rechazo: Optional[str] = None
    motivo_reversion: Optional[str] = None


class PaymentApproval(BaseModel):
    admin_username: str


class PaymentRejection(BaseModel):
    motivo: str = Field(..., min_length=1)


class PaymentReversion(BaseModel):
    """
    Schema específico para ANULAR un pago que ya había sido aprobado
    Uso: PUT /payments/{id}/anular
    """
    motivo: str = Field(
        ..., 
        min_length=10, 
        description="Justificación legal de la anulación (Ej: Cheque sin fondos o error bancario)"
    )


class PaymentWithDetails(PaymentResponse):
    estudiante_nombre: Optional[str] = None
    estudiante_email: Optional[str] = None
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None
    enrollment_total_a_pagar: Optional[float] = None
    enrollment_total_pagado: Optional[float] = None
    enrollment_saldo_pendiente: Optional[float] = None
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }
