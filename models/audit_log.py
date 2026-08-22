"""
F-FIX-AUDITORIA-FINANCIERA-NO-PERSISTIA (2026-08-22)
=====================================================

AGENTS.md/SOUL.md documentan como regla no-negociable: "Auditoría
inmutable: todo pago approved/rechazado/anulado/caja se registra vía
`_registrar_auditoria_financiera`". Encontrado en la auditoría completa
del 2026-08-22: esa función (`services/payment_service.py`) nunca
persistió nada — hacía `print()` y listo. No existía ningún modelo de
auditoría en `models/`. La regla estaba documentada pero no implementada
desde que se escribió.

Este modelo es el registro real. Inmutable por convención: solo se
inserta (`.insert()`), nunca se expone un endpoint de update/delete.
"""

from datetime import datetime, timezone
from typing import Optional
from pydantic import Field
from beanie import Document, PydanticObjectId


class AuditLogFinanciero(Document):
    accion: str = Field(..., description="Ej: 'aprobar_pago', 'reincorporar_estudiante'")
    payment_id: Optional[PydanticObjectId] = Field(
        default=None, description="None cuando la acción no tiene un Payment asociado (ej. reincorporación)"
    )
    enrollment_id: Optional[PydanticObjectId] = None
    estudiante_id: PydanticObjectId
    monto: float
    admin_username: str
    detalles: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "audit_logs_financieros"
        indexes = [
            "estudiante_id",
            "enrollment_id",
            "accion",
            "timestamp",
        ]
