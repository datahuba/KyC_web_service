"""
Modelo de Configuración de Pagos
=================================

Representa la configuración global de pagos del sistema.
Solo puede existir UN registro en la base de datos (singleton).

Colección MongoDB: payment_config
"""

from datetime import datetime
from core.timezone_utils import utcnow_naive
from typing import Optional
from pydantic import Field
from .base import MongoBaseModel


class PaymentConfig(MongoBaseModel):
    """
    Modelo de Configuración de Pagos - Configuración única del sistema
    
    Este modelo almacena:
    - QR de pago (imagen)
    - Número de cuenta bancaria
    
    SINGLETON: Solo puede existir un registro activo a la vez.
    
    Permisos:
    ---------
    - CREATE/UPDATE/DELETE: Solo ADMIN/SUPERADMIN
    - READ: Cualquier usuario autenticado (incluidos estudiantes)
    
    Flujo típico:
    -------------
    1. Admin crea la configuración inicial
    2. Estudiantes consultan el QR y número de cuenta al pagar
    3. Admin puede actualizar la información cuando cambie
    """
    
    # ========================================================================
    # DATOS DE PAGO
    # ========================================================================
    
    numero_cuenta: str = Field(
        ...,
        min_length=1,
        description="Número de cuenta bancaria donde se deben realizar los pagos"
    )
    
    banco: Optional[str] = Field(
        None,
        description="Nombre del banco (opcional)"
    )
    
    titular: Optional[str] = Field(
        None,
        description="Nombre del titular de la cuenta (opcional)"
    )
    
    tipo_cuenta: Optional[str] = Field(
        None,
        description="Tipo de cuenta: Ahorro, Corriente, etc. (opcional)"
    )
    
    # ========================================================================
    # QR DE PAGO
    # ========================================================================
    
    qr_url: str = Field(
        ...,
        description="URL del QR de pago (imagen en Cloudinary)"
    )
    
    # ========================================================================
    # METADATOS
    # ========================================================================
    
    is_active: bool = Field(
        default=True,
        description="Indica si esta configuración está activa (solo una puede estar activa)"
    )
    
    notas: Optional[str] = Field(
        None,
        description="Notas adicionales sobre la configuración de pago"
    )
    
    # ========================================================================
    # AUDITORÍA
    # ========================================================================
    
    creado_por: Optional[str] = Field(
        None,
        description="Username del admin que creó esta configuración"
    )
    
    actualizado_por: Optional[str] = Field(
        None,
        description="Username del admin que actualizó por última vez"
    )
    
    # ========================================================================
    # MÉTODOS
    # ========================================================================
    
    def actualizar_cuenta(
        self,
        numero_cuenta: str,
        admin_username: str,
        banco: Optional[str] = None,
        titular: Optional[str] = None,
        tipo_cuenta: Optional[str] = None
    ):
        """
        Actualiza la información de la cuenta bancaria
        
        Args:
            numero_cuenta: Nuevo número de cuenta
            admin_username: Username del admin que actualiza
            banco: Nombre del banco (opcional)
            titular: Titular de la cuenta (opcional)
            tipo_cuenta: Tipo de cuenta (opcional)
        """
        self.numero_cuenta = numero_cuenta
        if banco is not None:
            self.banco = banco
        if titular is not None:
            self.titular = titular
        if tipo_cuenta is not None:
            self.tipo_cuenta = tipo_cuenta
        self.actualizado_por = admin_username
        self.updated_at = utcnow_naive()
    
    def actualizar_qr(self, qr_url: str, admin_username: str):
        """
        Actualiza el QR de pago
        
        Args:
            qr_url: Nueva URL del QR
            admin_username: Username del admin que actualiza
        """
        self.qr_url = qr_url
        self.actualizado_por = admin_username
        self.updated_at = utcnow_naive()
    
    class Settings:
        name = "payment_config"
