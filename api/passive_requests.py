"""
Router de Solicitudes de Estado Pasivo (Passive Requests)
============================================================

- POST /passive-requests/                          -> ENCARGADO_CURSO (curso asignado), CPD, ADMIN, SUPERADMIN, STUDENT (propio)
- GET  /passive-requests/                           -> CPD, ADMIN, SUPERADMIN
- POST /passive-requests/{id}/approve               -> CPD, ADMIN, SUPERADMIN
- POST /passive-requests/{id}/reject                -> CPD, ADMIN, SUPERADMIN
- POST /passive-requests/enrollment/{id}/reactivate -> CPD, ADMIN, SUPERADMIN
"""

import math
from typing import Any, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from beanie import PydanticObjectId

from models.user import User
from models.student import Student
from schemas.passive_request import (
    PassiveRequestCreate,
    PassiveRequestReject,
    PassiveRequestResponse,
)
from schemas.enrollment import EnrollmentResponse
from schemas.common import PaginatedResponse, PaginationMeta
from services import passive_request_service, enrollment_service
from api.dependencies import require_cpd, get_current_user

router = APIRouter()


@router.post(
    "/",
    response_model=PassiveRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar Estado Pasivo"
)
async def create_request(
    data: PassiveRequestCreate,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Solicita pausar una inscripción. Autorizado para: Encargado de Curso (solo
    en sus cursos asignados), CPD/Admin/Superadmin (cualquiera), o el propio
    Estudiante (solo su inscripción). La validación de autorización ocurre en
    el service.
    """
    try:
        return await passive_request_service.create_passive_request(data, current_user)
    except ValueError as e:
        # Distinguimos errores de autorización (403) de errores de datos (400)
        mensaje = str(e)
        if "No tienes asignado" in mensaje or "no es tuya" in mensaje or "no está autorizado" in mensaje:
            raise HTTPException(status_code=403, detail=mensaje)
        raise HTTPException(status_code=400, detail=mensaje)


@router.get(
    "/",
    response_model=PaginatedResponse[PassiveRequestResponse],
    summary="Listar Solicitudes de Pasivo (CPD)"
)
async def list_requests(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    estado: Optional[str] = Query(None, description="Filtrar: pendiente | aprobado | rechazado"),
    current_user: User = Depends(require_cpd)
) -> Any:
    items, total = await passive_request_service.get_passive_requests(
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


@router.post(
    "/{id}/approve",
    response_model=EnrollmentResponse,
    summary="Aprobar Solicitud de Pasivo (CPD)"
)
async def approve_request(id: PydanticObjectId, current_user: User = Depends(require_cpd)) -> Any:
    try:
        enrollment = await passive_request_service.approve_passive_request(id, current_user.nombre_visible)
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/reject",
    response_model=PassiveRequestResponse,
    summary="Rechazar Solicitud de Pasivo (CPD)"
)
async def reject_request(
    id: PydanticObjectId,
    body: PassiveRequestReject,
    current_user: User = Depends(require_cpd)
) -> Any:
    try:
        return await passive_request_service.reject_passive_request(id, current_user.nombre_visible, body.motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/enrollment/{enrollment_id}/reactivate",
    response_model=EnrollmentResponse,
    summary="Reactivar Inscripción Pasiva (CPD)"
)
async def reactivate(enrollment_id: PydanticObjectId, current_user: User = Depends(require_cpd)) -> Any:
    try:
        enrollment = await passive_request_service.reactivate_enrollment(enrollment_id, current_user.nombre_visible)
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
