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
from pydantic import BaseModel, Field
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
    
    lista_estudiantes: List[PyObjectId] = Field(
        default_factory=list,
        description="Lista de IDs de estudiantes que tienen este descuento"
    )
    
    curso_id: Optional[PyObjectId] = Field(
        None,
        description="ID del curso (None = aplica a todos los cursos)"
    )
    
    fecha_inicio: Optional[datetime] = Field(
        None,
        description="Fecha desde la cual es válido"
    )
    
    fecha_fin: Optional[datetime] = Field(
        None,
        description="Fecha hasta la cual es válido"
    )
    
    activo: bool = Field(
        default=True,
        description="Si el descuento está activo"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre": "Beca Excelencia Académica",
                "porcentaje": 50.0,
                "lista_estudiantes": [],
                "curso_id": None,
                "fecha_inicio": None,
                "fecha_fin": None,
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
    lista_estudiantes: List[PyObjectId]
    curso_id: Optional[PyObjectId] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: bool
    created_at: datetime
    updated_at: datetime
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439016",
                "nombre": "Beca Excelencia Académica",
                "porcentaje": 50.0,
                "lista_estudiantes": ["507f1f77bcf86cd799439011"],
                "curso_id": None,
                "fecha_inicio": None,
                "fecha_fin": None,
                "activo": True,
                "created_at": "2024-01-01T10:00:00",
                "updated_at": "2024-01-01T10:00:00"
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
    lista_estudiantes: Optional[List[PyObjectId]] = None
    curso_id: Optional[PyObjectId] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: Optional[bool] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "porcentaje": 60.0,
                "activo": True
            }
        }
    }
