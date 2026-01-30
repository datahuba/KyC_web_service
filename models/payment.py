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
    """
    Modelo de Pago - Registra cada transacción individual
    
    Cada pago representa:
    - Un comprobante subido por el estudiante
    - Una verificación del admin (aprobar/rechazar)
    - Un concepto específico (matrícula, cuota 1, cuota 2, etc.)
    
    ¿Por qué un modelo separado?
    ---------------------------
    - Trazabilidad completa (historial de cada transacción)
    - Permite rechazar pagos incorrectos
    - Auditoría clara (quién aprobó, cuándo, qué voucher)
    - Puede haber múltiples intentos (si se rechaza el primero)
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
        description="Concepto del pago: 'MATRICULA', 'CUOTA', etc."
    )
    
    numero_cuota: Optional[int] = Field(
        None,
        ge=1,
        description="Número de cuota (si aplica): 1, 2, 3..."
    )
    
    # ========================================================================
    # DATOS DE LA TRANSACCIÓN
    # ========================================================================
    
    numero_transaccion: str = Field(
        ...,
        description="Número de transacción bancaria del comprobante"
    )

    # DATOS DECLARADOS DEL COMPROBANTE (INPUT DEL ESTUDIANTE)
    
    remitente: str = Field(
        ...,
        description="Nombre del remitente que figura en el comprobante"
    )

    fecha_comprobante: datetime = Field(
        ...,
        description="Fecha que figura en el comprobante"
    )

    monto_comprobante: float = Field(
        ...,
        gt=0,
        description="Monto que figura en el comprobante"
    )

    banco: str = Field(
        ...,
        description="Banco emisor del comprobante"
    )

    glosa: Optional[str] = Field(
        None,
        description="Glosa o descripción del comprobante"
    )

    cuenta_destino: str = Field(
        ...,
        description="Cuenta destino del pago"
    )

    
    cantidad_pago: float = Field(
        ...,
        gt=0,
        description="Monto del pago en Bs"
    )
    
    descuento_aplicado: Optional[float] = Field(
        None,
        ge=0,
        description="Descuento aplicado en este pago específico (si aplica)"
    )
    
    # ========================================================================
    # COMPROBANTE Y ESTADO
    # ========================================================================
    
    comprobante_url: str = Field(
        ...,
        description="URL del comprobante/voucher de pago (PDF en Cloudinary)"
    )
    
    estado_pago: EstadoPago = Field(
        default=EstadoPago.PENDIENTE,
        description="Estado: PENDIENTE, APROBADO, RECHAZADO"
    )
    
    # ========================================================================
    # TIMESTAMPS Y AUDITORÍA
    # ========================================================================
    
    fecha_subida: datetime = Field(
        default_factory=datetime.utcnow,
        description="Cuándo el estudiante subió el comprobante"
    )
    
    fecha_verificacion: Optional[datetime] = Field(
        None,
        description="Cuándo el admin verificó el pago"
    )
    
    verificado_por: Optional[str] = Field(
        None,
        description="Username del admin que verificó/rechazó"
    )
    
    motivo_rechazo: Optional[str] = Field(
        None,
        description="Razón del rechazo (si estado_pago = RECHAZADO)"
    )
    
    # ========================================================================
    # MÉTODOS
    # ========================================================================
    
    def aprobar_pago(self, admin_username: str):
        """
        Aprueba el pago
        
        Args:
            admin_username: Username del admin que aprueba
        """
        self.estado_pago = EstadoPago.APROBADO
        self.fecha_verificacion = datetime.utcnow()
        self.verificado_por = admin_username
        self.motivo_rechazo = None
        self.updated_at = datetime.utcnow()
    
    def rechazar_pago(self, admin_username: str, motivo: str):
        """
        Rechaza el pago
        
        Args:
            admin_username: Username del admin que rechaza
            motivo: Razón del rechazo
        """
        self.estado_pago = EstadoPago.RECHAZADO
        self.fecha_verificacion = datetime.utcnow()
        self.verificado_por = admin_username
        self.motivo_rechazo = motivo
        self.updated_at = datetime.utcnow()
    
    class Settings:
        name = "payments"
