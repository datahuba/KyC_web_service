"""
Modelo de Requisito (Embedded Document)
=======================================

Representa un requisito/documento que debe cumplir el estudiante.
Este modelo NO es un Document de MongoDB, es un subdocumento embebido.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from core.timezone_utils import utcnow_naive
from models.enums import EstadoRequisito


class Requisito(BaseModel):
    """
    Requisito embebido (subdocumento dentro de Enrollment)
    """
    
    descripcion: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nombre del requisito (ej: 'CV actualizado', 'Fotocopia de carnet')"
    )
    
    estado: EstadoRequisito = Field(
        default=EstadoRequisito.PENDIENTE,
        description="Estado actual: pendiente, en_proceso, aprobado, rechazado"
    )
    
    url: Optional[str] = Field(
        None,
        description="URL del documento en Cloudinary (null si no se ha subido)"
    )
    
    motivo_rechazo: Optional[str] = Field(
        None,
        max_length=500,
        description="Motivo de rechazo si el admin rechazó el documento"
    )
    
    revisado_por: Optional[str] = Field(
        None,
        description="Username del admin que revisó el documento"
    )
    
    fecha_subida: Optional[datetime] = Field(
        None,
        description="Fecha y hora cuando el estudiante subió el documento"
    )
    
    # ========================================================================
    # MÉTODOS HELPER
    # ========================================================================
    
    def subir_documento(self, url: str) -> None:
        """
        Marca que el estudiante subió el documento (auto-validado).
        
        Args:
            url: URL del documento en Cloudinary
        """
        self.url = url
        self.estado = EstadoRequisito.APROBADO
        self.fecha_subida = utcnow_naive()
        self.motivo_rechazo = None

    def aprobar(self, admin_username: str) -> None:
        """
        Admin aprueba el requisito
        """
        self.estado = EstadoRequisito.APROBADO
        self.revisado_por = admin_username
        self.motivo_rechazo = None
    
    def rechazar(self, admin_username: str, motivo: str) -> None:
        """
        Admin rechaza el requisito
        """
        self.estado = EstadoRequisito.RECHAZADO
        self.revisado_por = admin_username
        self.motivo_rechazo = motivo
    
    def esta_aprobado(self) -> bool:
        """Verifica si el requisito fue aprobado"""
        return self.estado == EstadoRequisito.APROBADO
    
    def esta_pendiente(self) -> bool:
        """Verifica si el requisito aún no fue subido"""
        return self.estado == EstadoRequisito.PENDIENTE
    
    def esta_en_proceso(self) -> bool:
        """Verifica si el requisito está esperando revisión"""
        return self.estado == EstadoRequisito.EN_PROCESO
    
    def esta_rechazado(self) -> bool:
        """Verifica si el requisito fue rechazado"""
        return self.estado == EstadoRequisito.RECHAZADO


class RequisitoTemplate(BaseModel):
    """
    Template de requisito (usado en Course)
    """
    
    descripcion: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nombre del requisito a pedir al estudiante"
    )
    
    def to_requisito(self) -> Requisito:
        """
        Convierte el template a un Requisito con valores iniciales
        """
        return Requisito(
            descripcion=self.descripcion,
            estado=EstadoRequisito.PENDIENTE,
            url=None,
            motivo_rechazo=None,
            revisado_por=None,
            fecha_subida=None
        )
