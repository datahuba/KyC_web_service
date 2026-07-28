"""
Modelo de Pago
=============

Representa un pago individual realizado por un estudiante.
Colección MongoDB: payments
"""

from datetime import datetime
from core.timezone_utils import utcnow_naive
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
        description=(
            "Concepto CONTABLE del pago (resumen): 'Matrícula', 'Pago Módulo 1', "
            "'Pago Módulos 1, 2', etc. Lo que importa para agrupación contable."
        )
    )

    # F-COBRANZA-020 (2026-07-22): detalle del pago, separado del concepto.
    # Kevin: "se podria poner como un total que junte a los dos por temas contables
    # y que este desglose sea ya un detalle de justificacion tipo".
    # Ej: si el pago cubre módulo 1 completo + módulo 2 parcial:
    #   - concepto: "Pago Módulo 1"          (para contabilidad)
    #   - detalle:  "Módulo 2 parcial (Bs 6 de Bs 294)"  (justificación)
    detalle: Optional[str] = Field(
        None,
        description=(
            "Desglose detallado del pago: módulos parciales, sobrantes, "
            "fracciones. Para auditoría. Null si no aplica."
        )
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
        self.fecha_verificacion = utcnow_naive()
        self.verificado_por = admin_username
        self.motivo_rechazo = None
        self.motivo_reversion = None
        self.updated_at = utcnow_naive()
    
    def rechazar_pago(self, admin_username: str, motivo: str):
        # F-048 (2026-07-22): antes guardaba en `motivo_rechazo` (campo
        # incorrecto), lo que dejaba el campo `motivo_reversion` (que es el
        # que se muestra en UI/XLSX) en NULL. Caso real: Luis Valdez 288 Bs
        # RECHAZADO mostraba "Motivo Reversión" vacío.
        # Fix: guardar en `motivo_reversion` (consistente con `anular_pago`)
        # y validar que el motivo no esté vacío.
        if not motivo or not motivo.strip():
            raise ValueError(
                "F-048: El motivo de rechazo es OBLIGATORIO. "
                "Debe indicar por qué se rechaza el pago (ej: comprobante ilegible, "
                "monto no coincide, etc.)."
            )
        self.estado_pago = EstadoPago.RECHAZADO
        self.fecha_verificacion = utcnow_naive()
        self.verificado_por = admin_username
        # Unificado: ahora rechaza también usa `motivo_reversion` (mismo campo
        # que `anular_pago`). Se mantiene `motivo_rechazo` por compatibilidad
        # histórica pero queda en None.
        self.motivo_reversion = motivo.strip()
        self.motivo_rechazo = motivo.strip()  # sincronizado para evitar inconsistencias
        self.updated_at = utcnow_naive()

    def anular_pago(self, admin_username: str, motivo: str):
        """
        Anula un pago que YA ESTABA APROBADO (Rollback financiero)
        """
        self.estado_pago = EstadoPago.ANULADO  # Requerirá agregar ANULADO al enum EstadoPago
        self.fecha_verificacion = utcnow_naive()
        self.verificado_por = admin_username
        self.motivo_reversion = motivo
        self.updated_at = utcnow_naive()
    
    class Settings:
        name = "payments"
        # AUDITORÍA (CRÍTICO #2): optimistic locking. Sin esto, dos requests
        # casi simultáneas (aprobar/rechazar el mismo pago PENDIENTE) podían
        # ambas pasar el guard de estado en el service y pisarse una a otra
        # (last-writer-wins), dejando el saldo del estudiante inconsistente.
        # Con use_revision=True, el segundo .save() sobre un documento ya
        # modificado lanza beanie.exceptions.RevisionIdWasChanged.
        use_revision = True
        indexes = [
            "inscripcion_id",
            "estudiante_id",
            "curso_id",
            "concepto",
            "metodo_pago",
            [("estado_pago", pymongo.ASCENDING), ("fecha_subida", pymongo.DESCENDING)],
            [("fecha_subida", pymongo.DESCENDING)],
            # F-082 (2026-07-28): indice UNICO PARCIAL en numero_transaccion
            # para evitar duplicados. Caso real: Medardo Balvino Rojas (CI
            # 2720765) subio el mismo comprobante 2 veces y el sistema permitio
            # ambos. La validacion en payment_service.create_payment se puede
            # saltar por race condition. Este indice es la red de seguridad a
            # nivel de MongoDB. Excluimos RECHAZADO y ANULADO para que
            # Cobranza pueda re-aprobar un pago tras corregir errores, y
            # excluimos None porque Caja no tiene NRO transaccion.
            pymongo.IndexModel(
                [("numero_transaccion", pymongo.ASCENDING)],
                unique=True,
                partialFilterExpression={
                    "numero_transaccion": {"$exists": True, "$type": "string"},
                    "estado_pago": {"$in": ["pendiente", "aprobado"]},
                },
                name="uniq_numero_transaccion_activo"
            ),
        ]
        