"""
Router de Solicitudes de Inscripción (Enrollment Requests)
=============================================================

ISSUE-R-SOLICITUD-INSCRIPCION: el estudiante solicita cursar un programa
activo desde su perfil; CPD/Admin/Superadmin aprueba (crea la inscripción
real) o rechaza con motivo.

- POST /enrollment-requests/                  -> STUDENT (propio)
- GET  /enrollment-requests/                  -> CPD, ADMIN, SUPERADMIN
- GET  /enrollment-requests/me                -> STUDENT (propio historial)
- GET  /enrollment-requests/{id}              -> CPD/ADMIN/SUPERADMIN (ver detalle) o STUDENT (propia)
- POST /enrollment-requests/{id}/approve      -> CPD, ADMIN, SUPERADMIN
- POST /enrollment-requests/{id}/reject       -> CPD, ADMIN, SUPERADMIN
- DELETE /enrollment-requests/{id}            -> CPD, ADMIN, SUPERADMIN (cascade si se borra enrollment)
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
from api.dependencies import require_encargado_curso, get_current_user
from models.enums import UserRole

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
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    cursos_permitidos = current_user.cursos_asignados if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR] else None
    items, total = await enrollment_request_service.get_enrollment_requests(
        estado=estado, page=page, per_page=per_page, cursos_permitidos=cursos_permitidos
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


# F-FIX-ENROLLMENT-REQUEST-GET-BY-ID (2026-08-10, Kevin): antes NO existia
# el endpoint GET /enrollment-requests/{id} (individual). El listado
# funcionaba, pero no se podia ver el detalle de una solicitud. Esto
# rompia la UI cuando el usuario hacia click en una solicitud del listado
# y queria ver el detalle. Tambien impedia que scripts de cleanup/test
# pudieran borrar solicitudes por id (DELETE siempre daba 404).
@router.get(
    "/{id}",
    response_model=EnrollmentRequestResponse,
    summary="Ver Detalle de Solicitud de Inscripción"
)
async def get_enrollment_request(
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    from models.enrollment_request import EnrollmentRequest
    solicitud = await EnrollmentRequest.get(id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # Estudiantes solo pueden ver SUS PROPIAS solicitudes
    if isinstance(current_user, Student):
        if solicitud.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver solicitudes de otros estudiantes"
            )
    # Encargado/Coordinador solo pueden ver solicitudes de SUS cursos asignados
    elif isinstance(current_user, User) and current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if solicitud.curso_id not in current_user.cursos_asignados:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver solicitudes de este curso"
            )

    enriched = await _enrich_requests([solicitud])
    return enriched[0]


# F-FIX-ENROLLMENT-REQUEST-DELETE (2026-08-10, Kevin): agregar DELETE
# /enrollment-requests/{id} para limpieza administrativa. Antes no existia,
# asi que las solicitudes huerfanas (e.g. una solicitud aprobada cuyo
# enrollment fue borrado) quedaban en la BD sin forma de removerlas.
# Solo CPD/Admin/Superadmin pueden borrar.
@router.delete(
    "/{id}",
    status_code=200,
    summary="Eliminar Solicitud de Inscripción (CPD/Admin)"
)
async def delete_enrollment_request(
    id: PydanticObjectId,
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    from models.enrollment_request import EnrollmentRequest
    solicitud = await EnrollmentRequest.get(id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")

    # Encargado/Coordinador solo pueden borrar solicitudes de SUS cursos
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if solicitud.curso_id not in current_user.cursos_asignados:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para borrar solicitudes de este curso"
            )

    await solicitud.delete()
    return {"message": "Solicitud eliminada", "_id": str(id)}


@router.post(
    "/{id}/approve",
    response_model=EnrollmentResponse,
    summary="Aprobar Solicitud de Inscripción (CPD)"
)
async def approve_request(id: PydanticObjectId, current_user: User = Depends(require_encargado_curso)) -> Any:
    from models.enrollment_request import EnrollmentRequest
    solicitud = await EnrollmentRequest.get(id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if solicitud.curso_id not in current_user.cursos_asignados:
            raise HTTPException(status_code=403, detail="No tienes permiso para aprobar solicitudes de este curso.")

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
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    from models.enrollment_request import EnrollmentRequest
    solicitud = await EnrollmentRequest.get(id)
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if solicitud.curso_id not in current_user.cursos_asignados:
            raise HTTPException(status_code=403, detail="No tienes permiso para rechazar solicitudes de este curso.")

    try:
        return await enrollment_request_service.reject_enrollment_request(id, current_user.nombre_visible, body.motivo)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
