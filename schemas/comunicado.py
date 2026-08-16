"""
Schemas Pydantic para Comunicados
==================================

US-003 (2026-08-03): DTOs para CRUD de comunicados, listado visible
al estudiante, y tracking de vistos.
"""

from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
from beanie import PydanticObjectId


# =====================================================================
# INPUTS
# =====================================================================

class ComunicadoCreate(BaseModel):
    """Datos para crear un comunicado."""
    titulo: str = Field(..., min_length=1, max_length=200)
    contenido: str = Field(..., min_length=1)
    cursos_ids: List[PydanticObjectId] = Field(
        default_factory=list,
        description="Audiencia. Vacío = todos los estudiantes activos."
    )
    importancia: Literal["normal", "urgente"] = "normal"
    adjuntos: List[dict] = Field(default_factory=list)
    expira_en: Optional[datetime] = None
    enviar_email: bool = False


class ComunicadoUpdate(BaseModel):
    """Datos para editar un comunicado (todos opcionales)."""
    titulo: Optional[str] = Field(None, min_length=1, max_length=200)
    contenido: Optional[str] = Field(None, min_length=1)
    cursos_ids: Optional[List[PydanticObjectId]] = None
    importancia: Optional[Literal["normal", "urgente"]] = None
    adjuntos: Optional[List[dict]] = None
    expira_en: Optional[datetime] = None


# =====================================================================
# OUTPUTS
# =====================================================================

class AdjuntoResponse(BaseModel):
    url: str
    nombre: str
    tipo: str  # 'image' o 'pdf'
    public_id: str


class ComunicadoResponse(BaseModel):
    """Representación de un comunicado para listar y ver detalle."""
    id: str
    titulo: str
    contenido: str
    autor_id: str
    autor_nombre: str
    autor_rol: str
    cursos_ids: List[str]
    importancia: str
    adjuntos: List[dict]
    expira_en: Optional[datetime]
    enviar_email: bool
    email_enviado: bool
    email_enviado_en: Optional[datetime]
    email_destinatarios: int
    total_vistos: int
    created_at: datetime
    updated_at: datetime


class ComunicadoListItem(BaseModel):
    """Versión resumida para listados (sin contenido completo)."""
    id: str
    titulo: str
    autor_nombre: str
    autor_rol: str
    importancia: str
    cursos_count: int  # cantidad de cursos a los que va (0 = todos)
    total_vistos: int
    email_enviado: bool
    created_at: datetime


class ComunicadoEstudianteResponse(BaseModel):
    """
    Comunicado tal como lo ve el estudiante, con flag `visto`.
    """
    id: str
    titulo: str
    contenido: str
    autor_nombre: str
    autor_rol: str
    importancia: str
    adjuntos: List[dict]
    expira_en: Optional[datetime]
    created_at: datetime
    visto: bool  # true si el estudiante ya marcó como visto


class ComunicadosPendientesResponse(BaseModel):
    """Respuesta del endpoint /comunicados/pending (estudiante)."""
    cantidad: int
    comunicados: List[ComunicadoEstudianteResponse]


class ComunicadoVistoResponse(BaseModel):
    """Respuesta del endpoint /comunicados/{id}/mark-as-seen."""
    ok: bool
    comunicado_id: str
    visto_en: datetime


class ComunicadosListResponse(BaseModel):
    """Listado paginado para el panel admin."""
    items: List[ComunicadoListItem]
    total: int
