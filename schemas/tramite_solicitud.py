"""
Schemas de Solicitud de Trámite (Tramite Solicitud)
===================================================

F-TRAMITES-SOLICITUD (2026-07-29): schemas para los 4 tipos de solicitudes
que el estudiante crea desde /app/requests:
  - convalidacion | tutoria | readmision | titulacion
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from models.base import PyObjectId
from models.enums import TipoTramite, EstadoTramite


# Tipos de archivo aceptado por cada tipo de trámite. Sirve para validar
# que el estudiante subió lo que corresponde antes de aceptar la solicitud.
ARCHIVOS_REQUERIDOS_POR_TIPO: dict = {
    TipoTramite.CONVALIDACION: ["carta", "certificado_nota", "comprobante_pago"],
    TipoTramite.TUTORIA: ["carta", "certificado_nota", "comprobante_pago"],
    TipoTramite.READMISION: ["carta"],
    TipoTramite.TITULACION: ["carta", "comprobante_pago"],
}


class ArchivoAdjuntoCreate(BaseModel):
    """Adjunto que el estudiante sube al crear la solicitud."""
    nombre_campo: str = Field(..., description="Identificador: 'carta' | 'certificado_nota' | 'comprobante_pago' | 'otro'")
    url: str = Field(..., min_length=10, description="URL pública de Cloudinary")
    nombre_archivo: Optional[str] = Field(None, description="Nombre original del archivo")
    mime_type: Optional[str] = Field(None, description="image/jpeg, application/pdf, etc.")

    @field_validator("nombre_campo")
    @classmethod
    def validar_nombre_campo(cls, v: str) -> str:
        allowed = {"carta", "certificado_nota", "comprobante_pago", "otro"}
        if v not in allowed:
            raise ValueError(f"nombre_campo debe ser uno de {sorted(allowed)}")
        return v


class TramiteSolicitudCreate(BaseModel):
    """
    Uso: POST /tramites/ (estudiante).
    """
    tipo: TipoTramite = Field(..., description="Tipo de solicitud")
    enrollment_id: Optional[str] = Field(None, description="ID del enrollment asociado (opcional)")

    nombre_completo: str = Field(..., min_length=3, max_length=200)
    ci: Optional[str] = Field(None, max_length=20)
    email: Optional[str] = Field(None, max_length=200)
    telefono: Optional[str] = Field(None, max_length=50)

    motivo: str = Field(..., min_length=10, max_length=2000, description="Detalle de la solicitud")
    programa_relacionado: Optional[str] = Field(None, max_length=300)
    modulos_relacionados: Optional[List[str]] = Field(default_factory=list, max_length=20)
    monto_pago_bs: Optional[float] = Field(None, ge=0)

    archivos: List[ArchivoAdjuntoCreate] = Field(
        default_factory=list,
        description="Archivos subidos a Cloudinary antes de llamar al endpoint"
    )

    @field_validator("archivos")
    @classmethod
    def validar_archivos_requeridos(cls, v: List["ArchivoAdjuntoCreate"], info) -> List["ArchivoAdjuntoCreate"]:
        tipo: Optional[TipoTramite] = info.data.get("tipo")
        if not tipo:
            return v
        requeridos = ARCHIVOS_REQUERIDOS_POR_TIPO.get(tipo, [])
        subidos = {a.nombre_campo for a in v}
        faltantes = [r for r in requeridos if r not in subidos]
        if faltantes:
            raise ValueError(
                f"Para solicitudes de tipo '{tipo.value}' debes adjuntar: {', '.join(requeridos)}. "
                f"Faltan: {', '.join(faltantes)}."
            )
        return v


class TramiteSolicitudAprobar(BaseModel):
    """Uso: PATCH /tramites/{id}/aprobar (staff)"""
    comentario: Optional[str] = Field(None, max_length=2000, description="Comentario opcional del staff")


class TramiteSolicitudRechazar(BaseModel):
    """Uso: PATCH /tramites/{id}/rechazar (staff)"""
    motivo: str = Field(..., min_length=3, max_length=2000, description="Motivo del rechazo")


class TramiteSolicitudCancelar(BaseModel):
    """Uso: PATCH /tramites/{id}/cancelar (estudiante)"""
    motivo: Optional[str] = Field(None, max_length=2000)


class TramiteSolicitudResponse(BaseModel):
    """Uso: GET /tramites/ y /tramites/{id}"""
    id: PyObjectId = Field(..., alias="_id")
    tipo: str
    estudiante_id: PyObjectId
    enrollment_id: Optional[PyObjectId] = None

    nombre_completo: str
    ci: Optional[str] = None
    email: Optional[str] = None
    telefono: Optional[str] = None

    motivo: str
    programa_relacionado: Optional[str] = None
    modulos_relacionados: List[str] = Field(default_factory=list)
    monto_pago_bs: Optional[float] = None

    archivos: List[dict] = Field(default_factory=list)

    estado: str
    fecha_revision: Optional[datetime] = None
    revisado_por: Optional[str] = None
    motivo_rechazo: Optional[str] = None
    motivo_cancelacion: Optional[str] = None
    fecha_cancelacion: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }


class TramiteSolicitudListResponse(BaseModel):
    """Lista paginada de solicitudes (staff)."""
    items: List[TramiteSolicitudResponse]
    total: int
    page: int
    per_page: int
    pages: int


class TramiteEstadisticas(BaseModel):
    """Estadísticas por tipo y estado, para el panel staff."""
    por_tipo: dict = Field(..., description="Dict[tipo] = {estado: count}")
    por_estado: dict = Field(..., description="Dict[estado] = count")
    total: int
    pendientes_hoy: int = Field(..., description="Solicitudes en 'pendiente' creadas hoy (UTC)")
