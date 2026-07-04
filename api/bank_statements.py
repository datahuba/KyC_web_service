"""
Router de Extracto Bancario (Bank Statement Entries)
=======================================================

- POST /bank-statements/            -> Cobranza, CPD, ADMIN, SUPERADMIN
- GET  /bank-statements/            -> Cobranza, CPD, ADMIN, SUPERADMIN
- POST /bank-statements/{id}/match  -> Cobranza, CPD, ADMIN, SUPERADMIN
- GET  /bank-statements/by-payment/{payment_id} -> Cobranza, CPD, ADMIN, SUPERADMIN

Registro y cruce MANUAL de movimientos bancarios (ISSUE-P-EXTRACTO). No hay
integración automática con el banco en esta fase; el módulo es de consulta
y registro, no de aprobación directa de pagos.
"""

import math
from datetime import datetime
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from beanie import PydanticObjectId

from models.user import User
from schemas.bank_statement_entry import (
    BankStatementEntryCreate,
    BankStatementEntryMatch,
    BankStatementEntryResponse,
)
from schemas.common import PaginatedResponse, PaginationMeta
from services import bank_statement_service
from api.dependencies import require_extracto_bancario

router = APIRouter()


@router.post(
    "/",
    response_model=BankStatementEntryResponse,
    status_code=201,
    summary="Registrar Movimiento de Extracto Bancario"
)
async def create_entry(
    data: BankStatementEntryCreate,
    current_user: User = Depends(require_extracto_bancario)
) -> Any:
    try:
        return await bank_statement_service.create_entry(data, current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=PaginatedResponse[BankStatementEntryResponse],
    summary="Listar Movimientos de Extracto Bancario"
)
async def list_entries(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    fecha_desde: Optional[datetime] = Query(None),
    fecha_hasta: Optional[datetime] = Query(None),
    banco: Optional[str] = Query(None),
    monto: Optional[float] = Query(None),
    solo_sin_cruzar: bool = Query(False),
    current_user: User = Depends(require_extracto_bancario)
) -> Any:
    items, total = await bank_statement_service.get_entries(
        fecha_desde=fecha_desde, fecha_hasta=fecha_hasta, banco=banco,
        monto=monto, solo_sin_cruzar=solo_sin_cruzar, page=page, per_page=per_page
    )
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "data": items,
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total, totalPages=total_pages,
            hasNextPage=(page < total_pages), hasPrevPage=(page > 1)
        )
    }


@router.post(
    "/{id}/match",
    response_model=BankStatementEntryResponse,
    summary="Cruzar Movimiento con un Pago"
)
async def match_entry(
    id: PydanticObjectId,
    body: BankStatementEntryMatch,
    current_user: User = Depends(require_extracto_bancario)
) -> Any:
    try:
        return await bank_statement_service.match_entry_to_payment(id, body.payment_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/by-payment/{payment_id}",
    response_model=Optional[BankStatementEntryResponse],
    summary="Ver Movimiento Cruzado con un Pago"
)
async def get_entry_for_payment(
    payment_id: PydanticObjectId,
    current_user: User = Depends(require_extracto_bancario)
) -> Any:
    return await bank_statement_service.get_entry_for_payment(payment_id)
