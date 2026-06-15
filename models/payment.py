"""
Modelo de Pago
=============

Representa un pago individual realizado por un estudiante.
Colección MongoDB: payments
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoPago


class Payment(MongoBaseModel):
    """
    Modelo de Pago - Registra cada transacción individual
    
    Cada pago representa:
    - Un comprobante subido por el estudiante (o registrado en Caja)
    - Una verificación del admin (aprobar/rechazar)
    - Un concepto específico (matrícula, cuota 1, cuota 2, etc.)
    """
    
    # ========================================================================
    # REFERENCIAS
    # ========================================================================
    
    inscripcion_id: PyObjectId = Field(
        ...,
        description="ID de la inscripción a la que pertenece este pago"
    )
    
    estudiante_id: PyObjectId = Field(
        ...,
        description="ID del estudiante (redundante pero útil para queries)"
    )
    
    curso_id: PyObjectId = Field(
        ...,
        description="ID del curso (redundante pero útil para queries)"
    )
    
    # ========================================================================
    # TIPO DE PAGO
    # ========================================================================
    
    concepto: str = Field(
        ...,
        min_length=1,
        description="Concepto del pago: 'Matrícula', 'Módulo', etc."
    )
    
    numero_cuota: Optional[int] = Field(
        None,
        ge=1,
        description="Número de cuota (si aplica): 1, 2, 3..."
    )
    
    # ========================================================================
    # DATOS DE LA TRANSACCIÓN FINANCIERA (ISSUE-P-CANALES)
    # ========================================================================
    
    metodo_pago: str = Field(
        default="Transferencia", 
        description="Puede ser: 'Transferencia', 'Caja', 'Depósito'"
    )
    
    numero_transaccion: Optional[str] = Field(
        None,
        description="Número de transacción bancaria (Nulo si fue en Caja física)"
    )
    
    cantidad_pago: float = Field(
        ...,
        gt=0,
        description="Monto del pago en Bs (El valor REAL pagado/prorrateable)"
    )
    
    descuento_aplicado: Optional[float] = Field(
        None,
        ge=0,
        description="Descuento aplicado en este pago específico (si aplica)"
    )
    
    remitente: Optional[str] = Field(None, description="Persona que figura en el voucher o que pagó en caja")
    banco: Optional[str] = Field(None, description="Banco origen (Nulo si fue Caja)")
    monto_comprobante: Optional[float] = None
    fecha_comprobante: Optional[datetime] = None 
    cuenta_destino: Optional[str] = Field(None, description="Cuenta institucional receptora o nombre de Caja")
    
    # ========================================================================
    # COMPROBANTE Y ESTADO
    # ========================================================================
    
    comprobante_url: Optional[str] = Field(
        None,
        description="URL del comprobante/voucher en la nube (Nulo si pagó en Caja física)"
    )
    
    estado_pago: EstadoPago = Field(
        default=EstadoPago.PENDIENTE,
        description="Estado: PENDIENTE, APROBADO, RECHAZADO, ANULADO"
    )
    
    # ========================================================================
    # TIMESTAMPS Y AUDITORÍA
    # ========================================================================
    
    fecha_subida: datetime = Field(
        default_factory=datetime.utcnow,
        description="Cuándo se registró el comprobante en el sistema"
    )
    
    fecha_verificacion: Optional[datetime] = Field(
        None,
        description="Cuándo el admin verificó o anuló el pago"
    )
    
    verificado_por: Optional[str] = Field(
        None,
        description="Username del admin que verificó/rechazó/anuló"
    )
    
    motivo_rechazo: Optional[str] = Field(
        None,
        description="Razón del rechazo (si estado_pago = RECHAZADO)"
    )
    
    motivo_reversion: Optional[str] = Field(
        None,
        description="Razón de la anulación (si estado_pago = ANULADO, e.j: Cheque sin fondos)"
    )
    
    # ========================================================================
    # MÉTODOS
    # ========================================================================
    
    def aprobar_pago(self, admin_username: str):
        self.estado_pago = EstadoPago.APROBADO
        self.fecha_verificacion = datetime.utcnow()
        self.verificado_por = admin_username
        self.motivo_rechazo = None
        self.motivo_reversion = None
        self.updated_at = datetime.utcnow()
    
    def rechazar_pago(self, admin_username: str, motivo: str):
        self.estado_pago = EstadoPago.RECHAZADO
        self.fecha_verificacion = datetime.utcnow()
        self.verificado_por = admin_username
        self.motivo_rechazo = motivo
        self.updated_at = datetime.utcnow()

    def anular_pago(self, admin_username: str, motivo: str):
        """
        Anula un pago que YA ESTABA APROBADO (Rollback financiero)
        """
        self.estado_pago = EstadoPago.ANULADO  # Requerirá agregar ANULADO al enum EstadoPago
        self.fecha_verificacion = datetime.utcnow()
        self.verificado_por = admin_username
        self.motivo_reversion = motivo
        self.updated_at = datetime.utcnow()
    
    class Settings:
        name = "payments"
        indexes = [
            "inscripcion_id",
            "estudiante_id",
            "curso_id",
            "numero_transaccion",
            "concepto",
            "metodo_pago",
            [("estado_pago", pymongo.ASCENDING), ("fecha_subida", pymongo.DESCENDING)],
            [("fecha_subida", pymongo.DESCENDING)]
        ]
        