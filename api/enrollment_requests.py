"""
Router de Solicitudes de Inscripción (Enrollment Requests)
=============================================================

ISSUE-R-SOLICITUD-INSCRIPCION: el estudiante solicita cursar un programa
activo desde su perfil; CPD/Admin/Superadmin aprueba (crea la inscripción
real) o rechaza con motivo.

- POST /enrollment-requests/                  -> STUDENT (propio)
- GET  /enrollment-requests/                  -> CPD, ADMIN, SUPERADMIN
- GET  /enrollment-requests/me                -> STUDENT (propio historial)
- POST /enrollment-requests/{id}/approve      -> CPD, ADMIN, SUPERADMIN
- POST /enrollment-requests/{id}/reject       -> CPD, ADMIN, SUPERADMIN
"""

import math
from typing import Any, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status
from beanie import PydanticObjectId

from models.user import User
from models.student import Student
from schemas.enrollment_request import (
    EnrollmentRequestCreate,
    EnrollmentRequestReject,
    EnrollmentRequestResponse,
)
from schemas.enrollment import EnrollmentResponse
from schemas.common import PaginatedResponse, PaginationMeta
from services import enrollment_request_service, enrollment_service
from api.dependencies import require_cpd, get_current_user

router = APIRouter()


async def _enrich_requests(requests) -> list:
    """Adjunta nombre de estudiante y curso a cada solicitud para la vista de CPD."""
    from models.course import Course

    estudiante_ids = {r.estudiante_id for r in requests}
    curso_ids = {r.curso_id for r in requests}

    students_map = {}
    if estudiante_ids:
        from beanie.operators import In
        students = await Student.find(In(Student.id, list(estudiante_ids))).to_list()
        students_map = {s.id: s for s in students}

    courses_map = {}
    if curso_ids:
        from beanie.operators import In
        courses = await Course.find(In(Course.id, list(curso_ids))).to_list()
        courses_map = {c.id: c for c in courses}

    enriched = []
    for r in requests:
        student = students_map.get(r.estudiante_id)
        course = courses_map.get(r.curso_id)
        data = EnrollmentRequestResponse.model_validate(r, from_attributes=True)
        data.estudiante_nombre = student.nombre if student else None
        data.estudiante_registro = student.registro if student else None
        data.curso_nombre = course.nombre_programa if course else None
        data.curso_codigo = course.codigo if course else None
        enriched.append(data)
    return enriched


@router.post(
    "/",
    response_model=EnrollmentRequestResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Solicitar Inscripción a un Curso"
)
async def create_request(
    data: EnrollmentRequestCreate,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Solo estudiantes pueden solicitar su propia inscripción a un curso activo."""
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden solicitar inscripción a un curso"
        )
    try:
        return await enrollment_request_service.create_enrollment_request(data, current_user)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=PaginatedResponse[EnrollmentRequestResponse],
    summary="Listar Solicitudes de Inscripción (CPD)"
)
async def list_requests(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    estado: Optional[str] = Query(None, description="Filtrar: pendiente | aprobado | rechazado"),
    current_user: User = Depends(require_cpd)
) -> Any:
    items, total = await enrollment_request_service.get_enrollment_requests(
        estado=estado, page=page, per_page=per_page
    )
    enriched = await _enrich_requests(items)
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "data": enriched,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1)
        )
    }


@router.get(
    "/me",
    summary="Mis Solicitudes de Inscripción (Estudiante)"
)
async def list_my_requests(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo estudiantes tienen historial de solicitudes de inscripción")
    items = await enrollment_request_service.get_my_enrollment_requests(current_user.id)
    return await _enrich_requests(items)


@router.post(
    "/{id}/approve",
    response_model=EnrollmentResponse,
    summary="Aprobar Solicitud de Inscripción (CPD)"
)
async def approve_request(id: PydanticObjectId, current_user: User = Depends(require_cpd)) -> Any:
    try:
        enrollment = await enrollment_request_service.approve_enrollment_request(id, current_user.nombre_visible)
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/reject",
    response_model=EnrollmentRequestResponse,
    summary="Rechazar Solicitud de Inscripción (CPD)"
)
async def reject_request(
    id: PydanticObjectId,
    body: EnrollmentRequestReject,
    current_user: User = Depends(require_cpd)
) -> Any:
    try:
        return await enrollment_request_service.reject_enrollment_request(id, current_user.nombre_visible, body.motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
