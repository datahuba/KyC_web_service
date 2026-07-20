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
    
    NO hereda de Document porque:
    - No tiene su propia colección en MongoDB
    - Se almacena dentro del array `requisitos` de Enrollment
    - Se identifica por su índice en el array (no necesita _id)
    
    Características:
    ---------------
    - Validación de estado con enum
    - Métodos helper para cambiar estados
    - NO tiene timestamps propios (usa los del Enrollment padre)
    
    Uso:
    ---
    Este modelo se usa en:
    1. Course.requisitos (como template/plantilla)
    2. Enrollment.requisitos (con estado y URL)
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
        Marca que el estudiante subió el documento
        
        Args:
            url: URL del documento en Cloudinary
            
        Cambios:
        -------
        - url → se asigna
        - estado → pasa a EN_PROCESO
        - fecha_subida → timestamp actual
        - motivo_rechazo → se limpia (por si era un rechazo previo)
        """
        self.url = url
        self.estado = EstadoRequisito.EN_PROCESO
        self.fecha_subida = utcnow_naive()
        self.motivo_rechazo = None  # Limpiar rechazo anterior
    
    def aprobar(self, admin_username: str) -> None:
        """
        Admin aprueba el requisito
        
        Args:
            admin_username: Username del admin que aprueba
            
        Cambios:
        -------
        - estado → APROBADO
        - revisado_por → username del admin
        - motivo_rechazo → se limpia
        """
        self.estado = EstadoRequisito.APROBADO
        self.revisado_por = admin_username
        self.motivo_rechazo = None
    
    def rechazar(self, admin_username: str, motivo: str) -> None:
        """
        Admin rechaza el requisito
        
        Args:
            admin_username: Username del admin que rechaza
            motivo: Razón del rechazo
            
        Cambios:
        -------
        - estado → RECHAZADO
        - revisado_por → username del admin
        - motivo_rechazo → razón del rechazo
        
        Nota:
        ----
        El estudiante puede volver a subir el documento después.
        Al hacerlo, el estado vuelve a EN_PROCESO.
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
    
    Solo contiene la descripción del requisito, sin estado ni URL.
    Cuando se crea un Enrollment, estos templates se copian y se
    convierten en objetos Requisito completos con estado PENDIENTE.
    
    Uso:
    ---
    En Course.requisitos solo se define qué se requiere:
      [
        {descripcion: "CV actualizado"},
        {descripcion: "Fotocopia de carnet"}
      ]
    
    Cuando se crea el Enrollment, se copian con valores iniciales:
      [
        {descripcion: "CV actualizado", estado: "pendiente", url: null},
        {descripcion: "Fotocopia de carnet", estado: "pendiente", url: null}
      ]
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
        
        Returns:
            Requisito con estado PENDIENTE y sin URL
        """
        return Requisito(
            descripcion=self.descripcion,
            estado=EstadoRequisito.PENDIENTE,
            url=None,
            motivo_rechazo=None,
            revisado_por=None,
            fecha_subida=None
        )
