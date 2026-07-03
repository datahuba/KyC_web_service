"""
Schemas de Solicitud de Cuenta (Account Request)
================================================
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr, field_validator
from models.base import PyObjectId
from models.enums import TipoEstudiante


class AccountRequestCreate(BaseModel):
    """Solicitud pública de creación de cuenta (validaciones básicas)."""
    nombre: str = Field(..., min_length=3, max_length=200)
    email: EmailStr
    carnet: str = Field(..., min_length=4, max_length=20)
    celular: Optional[str] = Field(None, max_length=20)
    registro: Optional[str] = Field(None, max_length=30)
    es_estudiante_interno: TipoEstudiante = TipoEstudiante.EXTERNO
    mensaje: Optional[str] = Field(None, max_length=500)

    @field_validator('carnet')
    @classmethod
    def carnet_valido(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError('El carnet debe contener solo números.')
        return v

    @field_validator('celular')
    @classmethod
    def celular_valido(cls, v):
        if v is None:
            return v
        v = v.strip()
        if v and not v.isdigit():
            raise ValueError('El celular debe contener solo números.')
        return v or None

    @field_validator('nombre')
    @classmethod
    def nombre_limpio(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError('El nombre completo es obligatorio.')
        return v


class AccountRequestResponse(BaseModel):
    id: PyObjectId = Field(..., alias="_id")
    nombre: str
    email: EmailStr
    carnet: str
    celular: Optional[str] = None
    registro: Optional[str] = None
    es_estudiante_interno: TipoEstudiante
    mensaje: Optional[str] = None
    estado: str
    motivo_rechazo: Optional[str] = None
    revisado_por: Optional[str] = None
    fecha_revision: Optional[datetime] = None
    estudiante_id: Optional[PyObjectId] = None
    created_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class AccountRequestReject(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=500, description="Motivo del rechazo")
