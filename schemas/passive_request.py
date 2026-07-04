"""
Schemas de Solicitud de Estado Pasivo (Passive Request)
========================================================
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
from models.base import PyObjectId


class PassiveRequestCreate(BaseModel):
    """Uso: POST /passive-requests/"""
    enrollment_id: PyObjectId = Field(..., description="ID de la inscripción a pausar")
    motivo: str = Field(..., min_length=3, max_length=500, description="Motivo de la solicitud")
    respaldo_url: Optional[str] = Field(None, description="URL del documento de respaldo (opcional)")

    model_config = {
        "json_schema_extra": {
            "example": {
                "enrollment_id": "507f1f77bcf86cd799439012",
                "motivo": "Licencia médica de 2 meses",
                "respaldo_url": None
            }
        }
    }


class PassiveRequestReject(BaseModel):
    """Uso: POST /passive-requests/{id}/reject"""
    motivo: str = Field(..., min_length=3, max_length=500, description="Motivo del rechazo")


class PassiveRequestResponse(BaseModel):
    """Uso: GET /passive-requests/"""
    id: PyObjectId = Field(..., alias="_id")
    enrollment_id: PyObjectId
    solicitante_id: PyObjectId
    solicitante_tipo: str
    motivo: str
    respaldo_url: Optional[str] = None
    estado: str
    motivo_rechazo: Optional[str] = None
    revisado_por: Optional[str] = None
    fecha_revision: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }
