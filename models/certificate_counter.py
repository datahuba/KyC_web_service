"""
Modelo de Contador de Certificados
==================================

Mantiene el correlativo anual de certificados emitidos. Un documento por año
con un `last_number` que se incrementa atómicamente con `find_one_and_update`
y `$inc`. Esto garantiza que dos requests simultáneos reciban números distintos
aunque el `await` se intercalle, porque MongoDB aplica `$inc` de forma atómica
sobre el documento.

Colección MongoDB: certificate_counters

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md
"""

from datetime import datetime
import pymongo
from pydantic import Field
from .base import MongoBaseModel


class CertificateCounter(MongoBaseModel):
    """
    Contador anual de certificados emitidos.

    Operaciones:
    - `find_one_and_update({anio: Y}, {"$inc": {"last_number": 1}}, upsert=True)`
      retorna el documento con el nuevo valor.
    - El primer certificado del año crea el documento con `last_number: 1`
      (upsert + $inc = 1 desde 0).
    - El folio formateado es `N° {last_number:03d}/{anio}` (ej: `N° 001/2026`).
    """

    anio: int = Field(..., ge=2000, le=2100, description="Año del correlativo")
    last_number: int = Field(default=0, ge=0, description="Último número emitido en este año. Siguiente = last_number + 1")

    class Settings:
        name = "certificate_counters"
        # 1 documento por año, garantía de unicidad.
        indexes = [
            pymongo.IndexModel([("anio", pymongo.ASCENDING)], unique=True, name="uniq_anio"),
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "anio": 2026,
                "last_number": 42,
            }
        }
