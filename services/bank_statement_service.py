"""
Servicio de Extracto Bancario (Bank Statement Entries)
=========================================================

Registro y cruce MANUAL de movimientos bancarios contra pagos existentes.
(ISSUE-P-EXTRACTO) — sin integración automática con el banco por ahora.
"""

from typing import List, Optional
from datetime import datetime
from core.timezone_utils import utcnow_naive
from beanie import PydanticObjectId

from models.bank_statement_entry import BankStatementEntry
from models.payment import Payment
from schemas.bank_statement_entry import BankStatementEntryCreate


async def create_entry(data: BankStatementEntryCreate, registrado_por: str) -> BankStatementEntry:
    entry = BankStatementEntry(
        fecha_movimiento=data.fecha_movimiento,
        banco=data.banco.strip(),
        monto=data.monto,
        tipo_movimiento=data.tipo_movimiento,
        referencia=data.referencia.strip() if data.referencia else None,
        origen="manual",
        registrado_por=registrado_por,
        payment_id=None,
        notas=data.notas.strip() if data.notas else None,
    )
    await entry.insert()
    return entry


async def get_entries(
    fecha_desde: Optional[datetime] = None,
    fecha_hasta: Optional[datetime] = None,
    banco: Optional[str] = None,
    monto: Optional[float] = None,
    solo_sin_cruzar: bool = False,
    page: int = 1,
    per_page: int = 20,
) -> tuple[List[BankStatementEntry], int]:
    query_dict: dict = {}

    if fecha_desde or fecha_hasta:
        rango: dict = {}
        if fecha_desde:
            rango["$gte"] = fecha_desde
        if fecha_hasta:
            rango["$lte"] = fecha_hasta
        query_dict["fecha_movimiento"] = rango

    if banco:
        query_dict["banco"] = {"$regex": banco, "$options": "i"}

    if monto is not None:
        # Tolerancia pequeña para evitar problemas de precisión de punto flotante
        query_dict["monto"] = {"$gte": monto - 0.01, "$lte": monto + 0.01}

    if solo_sin_cruzar:
        query_dict["payment_id"] = None

    total = await BankStatementEntry.find(query_dict).count()
    skip = (page - 1) * per_page
    items = await BankStatementEntry.find(query_dict).sort("-fecha_movimiento").skip(skip).limit(per_page).to_list()
    return items, total


async def match_entry_to_payment(entry_id: PydanticObjectId, payment_id: PydanticObjectId) -> BankStatementEntry:
    entry = await BankStatementEntry.get(entry_id)
    if not entry:
        raise ValueError("Línea de extracto no encontrada")

    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError("Pago no encontrado")

    entry.payment_id = payment_id
    entry.updated_at = utcnow_naive()
    await entry.save()
    return entry


async def get_entry_for_payment(payment_id: PydanticObjectId) -> Optional[BankStatementEntry]:
    """Devuelve la línea de extracto cruzada con este pago, si existe."""
    return await BankStatementEntry.find_one(BankStatementEntry.payment_id == payment_id)
