"""
Modelo de Línea de Extracto Bancario (Bank Statement Entry)
=============================================================

Registro manual de movimientos bancarios (depósitos/transferencias) para
que Cobranza/CPD puedan cruzarlos contra los comprobantes subidos por los
estudiantes cuando la glosa no identifica al alumno.

NOTA DE ALCANCE (ISSUE-P-EXTRACTO): por ahora es 100% manual (sin integración
con el banco). El campo `origen` deja espacio para una futura fuente
'importado' sin romper lo manual.

Colección MongoDB: bank_statement_entries
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class BankStatementEntry(MongoBaseModel):
    fecha_movimiento: datetime = Field(
        ..., description="Fecha del depósito/transferencia según el extracto bancario"
    )
    banco: str = Field(..., min_length=1, max_length=100, description="Banco donde se registró el movimiento")
    monto: float = Field(..., gt=0, description="Monto del movimiento")
    tipo_movimiento: str = Field(
        ..., description="Tipo de movimiento: 'deposito' o 'transferencia'"
    )
    referencia: Optional[str] = Field(
        None, max_length=300,
        description="Número de cuenta visible, glosa parcial u otra referencia del movimiento"
    )
    origen: str = Field(
        default="manual",
        description="'manual' (implementado ahora) o 'importado' (reservado para integración futura)"
    )
    registrado_por: str = Field(..., description="Username de quien transcribió el movimiento")
    payment_id: Optional[PyObjectId] = Field(
        None, description="Payment cruzado manualmente con este movimiento, si corresponde"
    )
    notas: Optional[str] = Field(None, max_length=500, description="Notas libres del revisor")

    class Settings:
        name = "bank_statement_entries"
        indexes = [
            [("fecha_movimiento", pymongo.DESCENDING)],
            [("banco", pymongo.ASCENDING), ("fecha_movimiento", pymongo.DESCENDING)],
            "payment_id",
        ]
