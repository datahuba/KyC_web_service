"""
Router de Solicitudes de Cuenta
===============================

- POST /account-requests/            -> PÚBLICO (cualquiera solicita una cuenta)
- GET  /account-requests/            -> CPD (lista para revisión)
- GET  /account-requests/pending-count -> CPD (conteo de pendientes)
- POST /account-requests/{id}/approve  -> CPD (crea el estudiante)
- POST /account-requests/{id}/reject   -> CPD (rechaza con motivo)
"""

import math
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from beanie import PydanticObjectId

from models.user import User
from schemas.account_request import (
    AccountRequestCreate,
    AccountRequestResponse,
    AccountRequestReject,
)
from schemas.common import PaginatedResponse, PaginationMeta
from schemas.student import StudentResponse
from services import account_request_service
from api.dependencies import require_cpd

router = APIRouter()


@router.post(
    "/",
    response_model=AccountRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar Cuenta (Público)"
)
async def create_request(data: AccountRequestCreate) -> Any:
    """Envío público del formulario de solicitud de cuenta. Notifica al CPD."""
    try:
        return await account_request_service.create_account_request(data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=PaginatedResponse[AccountRequestResponse],
    summary="Listar Solicitudes (CPD)"
)
async def list_requests(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    estado: Optional[str] = Query(None, description="Filtrar: pendiente | aprobado | rechazado"),
    current_user: User = Depends(require_cpd)
) -> Any:
    items, total = await account_request_service.get_account_requests(
        estado=estado, page=page, per_page=per_page
    )
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "data": items,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1)
        )
    }


@router.get("/pending-count", summary="Conteo de Solicitudes Pendientes (CPD)")
async def pending_count(current_user: User = Depends(require_cpd)) -> Any:
    count = await account_request_service.get_pending_count()
    return {"pending_count": count}


@router.post(
    "/{id}/approve",
    response_model=StudentResponse,
    summary="Aprobar Solicitud (CPD)"
)
async def approve_request(id: PydanticObjectId, current_user: User = Depends(require_cpd)) -> Any:
    try:
        student = await account_request_service.approve_account_request(id, current_user.username)
        return student
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/reject",
    response_model=AccountRequestResponse,
    summary="Rechazar Solicitud (CPD)"
)
async def reject_request(
    id: PydanticObjectId,
    body: AccountRequestReject,
    current_user: User = Depends(require_cpd)
) -> Any:
    try:
        return await account_request_service.reject_account_request(id, current_user.username, body.motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
