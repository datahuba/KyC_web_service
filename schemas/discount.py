"""
Schemas de Descuento
====================

Define los schemas Pydantic para operaciones CRUD de descuentos.

Schemas incluidos:
-----------------
1. DiscountCreate: Para crear nuevos descuentos
2. DiscountResponse: Para mostrar descuentos
3. DiscountUpdate: Para actualizar descuentos
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from models.base import PyObjectId


class DiscountCreate(BaseModel):
    """
    Schema para crear un nuevo descuento
    
    Uso: POST /discounts/
    """
    
    nombre: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nombre descriptivo del descuento"
    )
    
    porcentaje: float = Field(
        ...,
        ge=0,
        le=100,
        description="Porcentaje de descuento (0-100)"
    )
    
    activo: bool = Field(
        default=True,
        description="Si el descuento está activo"
    )

    @field_validator("nombre")
    @classmethod
    def validate_nombre(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("El nombre del descuento no puede estar vacío ni contener solo espacios.")
        return v.strip()

    @field_validator("porcentaje")
    @classmethod
    def validate_porcentaje(cls, v: float) -> float:
        if v < 0.0 or v > 100.0:
            raise ValueError("El porcentaje de descuento debe estar entre 0.0 y 100.0.")
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Beca Excelencia Académica 2024",
                "porcentaje": 30.0,
                "activo": True
            }
        }
    }


class DiscountResponse(BaseModel):
    """
    Schema para mostrar información de un descuento
    
    Uso: GET /discounts/{id}
    """
    
    id: PyObjectId = Field(..., alias="_id")
    nombre: str
    porcentaje: float
    activo: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439077",
                "nombre": "Descuento Estudiante Interno",
                "porcentaje": 10.0,
                "activo": True,
                "created_at": "2024-02-15T10:00:00",
                "updated_at": "2024-02-15T10:00:00"
            }
        }
    }


class DiscountUpdate(BaseModel):
    """
    Schema para actualizar un descuento existente
    
    Uso: PATCH /discounts/{id}
    """
    
    nombre: Optional[str] = Field(None, min_length=1, max_length=200)
    porcentaje: Optional[float] = Field(None, ge=0, le=100)
    activo: Optional[bool] = None

    @field_validator("nombre")
    @classmethod
    def validate_nombre(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not v.strip():
                raise ValueError("El nombre del descuento no puede estar vacío ni contener solo espacios.")
            return v.strip()
        return v

    @field_validator("porcentaje")
    @classmethod
    def validate_porcentaje(cls, v: Optional[float]) -> Optional[float]:
        if v is not None:
            if v < 0.0 or v > 100.0:
                raise ValueError("El porcentaje de descuento debe estar entre 0.0 y 100.0.")
        return v
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Descuento Estudiante Interno 2024",
                "porcentaje": 15.0,
                "activo": True
            }
        }
    }
    