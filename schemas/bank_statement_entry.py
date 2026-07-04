"""
Schemas de Línea de Extracto Bancario (Bank Statement Entry)
=============================================================
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator
from models.base import PyObjectId

TIPOS_MOVIMIENTO_VALIDOS = {"deposito", "transferencia"}


class BankStatementEntryCreate(BaseModel):
    """Uso: POST /bank-statements/"""
    fecha_movimiento: datetime = Field(..., description="Fecha del movimiento según el extracto")
    banco: str = Field(..., min_length=1, max_length=100)
    monto: float = Field(..., gt=0)
    tipo_movimiento: str = Field(..., description="'deposito' o 'transferencia'")
    referencia: Optional[str] = Field(None, max_length=300)
    notas: Optional[str] = Field(None, max_length=500)

    @field_validator("tipo_movimiento")
    @classmethod
    def validar_tipo_movimiento(cls, v: str) -> str:
        if v not in TIPOS_MOVIMIENTO_VALIDOS:
            raise ValueError(f"tipo_movimiento debe ser uno de: {', '.join(TIPOS_MOVIMIENTO_VALIDOS)}")
        return v

    model_config = {
        "json_schema_extra": {
            "example": {
                "fecha_movimiento": "2026-07-03T00:00:00",
                "banco": "Banco Unión",
                "monto": 500.0,
                "tipo_movimiento": "transferencia",
                "referencia": "Cuenta terminada en 1234",
                "notas": "Sin nombre en la glosa, cruzar con comprobante"
            }
        }
    }


class BankStatementEntryMatch(BaseModel):
    """Uso: POST /bank-statements/{id}/match"""
    payment_id: PyObjectId = Field(..., description="ID del Payment a cruzar con esta línea de extracto")


class BankStatementEntryResponse(BaseModel):
    """Uso: GET /bank-statements/"""
    id: PyObjectId = Field(..., alias="_id")
    fecha_movimiento: datetime
    banco: str
    monto: float
    tipo_movimiento: str
    referencia: Optional[str] = None
    origen: str
    registrado_por: str
    payment_id: Optional[PyObjectId] = None
    notas: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }
