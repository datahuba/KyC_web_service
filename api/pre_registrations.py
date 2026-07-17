"""
Router de Pre-registro de Estudiantes
======================================

ISSUE-Q-PRE-REGISTRO-FORM (2026-07-17): formularios dinámicos para que
visitantes externos llenen sus datos y CPD/Encargado los apruebe para
crearles un Student + User con la convención 'Uagrm.<CI>'.

Endpoints:
  PÚBLICOS (sin auth):
    GET  /pre-registrations/public/{slug}    -> ver form por slug
    POST /pre-registrations/public/{slug}    -> enviar submission

  ADMIN (auth requerida):
    GET  /pre-registrations/forms            -> listar forms visibles (superadmin, admin, cpd, encargado, coord)
    GET  /pre-registrations/forms/{id}       -> ver un form
    POST /pre-registrations/forms            -> crear form (solo superadmin)
    PATCH /pre-registrations/forms/{id}      -> editar form (solo superadmin)
    POST /pre-registrations/forms/{id}/close -> cerrar (solo superadmin)
    POST /pre-registrations/forms/{id}/reopen-> reabrir (solo superadmin)
    DELETE /pre-registrations/forms/{id}     -> eliminar (solo superadmin, falla si tiene submissions)
    GET  /pre-registrations/submissions      -> listar submissions visibles
    POST /pre-registrations/submissions/{id}/approve -> aprobar (migra a Student)
    POST /pre-registrations/submissions/{id}/reject  -> rechazar con motivo
    GET  /pre-registrations/counters         -> contadores para badges
"""

import math
from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from beanie import PydanticObjectId

from models.user import User
from models.pre_registration import PreRegistrationForm
from models.student import Student
from models.course import Course
from schemas.pre_registration import (
    PreRegistrationFormCreate,
    PreRegistrationFormUpdate,
    PreRegistrationFormResponse,
    PreRegistrationSubmit,
    PreRegistrationResponse,
    PreRegistrationReject,
)
from schemas.common import PaginatedResponse, PaginationMeta
from services import pre_registration_service
from api.dependencies import require_superadmin, require_cpd

router = APIRouter()


# ============================================================================
# PÚBLICOS (sin auth) — prefijo /pre-registrations/public
# ============================================================================

@router.get(
    "/public/{slug}",
    response_model=PreRegistrationFormResponse,
    summary="Ver Formulario Público por Slug (sin auth)"
)
async def get_public_form(slug: str) -> Any:
    """Devuelve la metadata del formulario para que la página pública sepa qué pintar."""
    try:
        form = await pre_registration_service.get_public_form_by_slug(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.post(
    "/public/{slug}",
    response_model=PreRegistrationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Enviar Pre-inscripción Pública (sin auth)"
)
async def submit_public_form(slug: str, data: PreRegistrationSubmit) -> Any:
    """Público: cualquier persona con el link puede enviar."""
    try:
        sub = await pre_registration_service.submit_public_form(slug, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_submission(sub)


# ============================================================================
# ADMIN (auth) — prefijo /pre-registrations/forms y /pre-registrations/submissions
# ============================================================================

@router.get(
    "/forms",
    response_model=PaginatedResponse[PreRegistrationFormResponse],
    summary="Listar Formularios visibles para mi rol"
)
async def list_forms(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(require_cpd)
) -> Any:
    items, total = await pre_registration_service.get_forms_for_admin(
        current_user=current_user, page=page, per_page=per_page
    )
    enriched = [await _enrich_form(f) for f in items]
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "data": enriched,
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total, totalPages=total_pages,
            hasNextPage=(page < total_pages), hasPrevPage=(page > 1),
        ),
    }


@router.get(
    "/forms/{form_id}",
    response_model=PreRegistrationFormResponse,
    summary="Ver un Formulario"
)
async def get_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_cpd)
) -> Any:
    form = await pre_registration_service.get_form_by_id(form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario no encontrado")
    # Chequear visibilidad por rol (mismas reglas que list_forms)
    from models.enums import UserRole
    if current_user.rol == UserRole.CPD and form.programa_id is not None:
        raise HTTPException(status_code=403, detail="No tienes permiso para ver este formulario.")
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        if form.programa_id not in cursos:
            raise HTTPException(status_code=403, detail="No tienes permiso para ver este formulario.")
    return await _enrich_form(form)


@router.post(
    "/forms",
    response_model=PreRegistrationFormResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear Formulario (solo super admin)"
)
async def create_form(
    data: PreRegistrationFormCreate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    try:
        form = await pre_registration_service.create_form(data, current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.patch(
    "/forms/{form_id}",
    response_model=PreRegistrationFormResponse,
    summary="Editar Formulario (solo super admin)"
)
async def update_form(
    form_id: PydanticObjectId,
    data: PreRegistrationFormUpdate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    try:
        form = await pre_registration_service.update_form(form_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.post(
    "/forms/{form_id}/close",
    response_model=PreRegistrationFormResponse,
    summary="Cerrar Formulario manualmente (solo super admin)"
)
async def close_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    from schemas.pre_registration import PreRegistrationFormUpdate
    try:
        form = await pre_registration_service.update_form(form_id, PreRegistrationFormUpdate(estado="cerrado"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.post(
    "/forms/{form_id}/reopen",
    response_model=PreRegistrationFormResponse,
    summary="Reabrir Formulario (solo super admin)"
)
async def reopen_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    from schemas.pre_registration import PreRegistrationFormUpdate
    try:
        form = await pre_registration_service.update_form(form_id, PreRegistrationFormUpdate(estado="activo"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.delete(
    "/forms/{form_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar Formulario (solo super admin)"
)
async def delete_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    try:
        await pre_registration_service.delete_form(form_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================================
# Submissions
# ============================================================================

@router.get(
    "/submissions",
    response_model=PaginatedResponse[PreRegistrationResponse],
    summary="Listar Pre-inscripciones visibles para mi rol"
)
async def list_submissions(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    form_id: Optional[str] = Query(None, description="Filtrar por ID de form"),
    estado: Optional[str] = Query(None, description="pendiente | aprobado | rechazado"),
    current_user: User = Depends(require_cpd)
) -> Any:
    items, total = await pre_registration_service.get_submissions_for_admin(
        current_user=current_user, form_id=form_id, estado=estado, page=page, per_page=per_page
    )
    enriched = [await _enrich_submission(s) for s in items]
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "data": enriched,
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total, totalPages=total_pages,
            hasNextPage=(page < total_pages), hasPrevPage=(page > 1),
        ),
    }


@router.post(
    "/submissions/{submission_id}/approve",
    response_model=Student,
    summary="Aprobar Pre-inscripción (crea Student + User + email de bienvenida)"
)
async def approve_submission(
    submission_id: PydanticObjectId,
    current_user: User = Depends(require_cpd)
) -> Any:
    # Chequear que la submission sea visible para este rol
    from models.pre_registration import PreRegistration
    from models.enums import UserRole

    sub = await PreRegistration.get(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Pre-inscripción no encontrada.")

    form = await PreRegistrationForm.get(sub.form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario asociado no encontrado.")

    if current_user.rol == UserRole.CPD and form.programa_id is not None:
        raise HTTPException(status_code=403, detail="Esta pre-inscripción es para un programa específico.")
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        if form.programa_id not in cursos:
            raise HTTPException(status_code=403, detail="No tienes permiso para aprobar este formulario.")

    try:
        return await pre_registration_service.approve_submission(submission_id, current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/submissions/{submission_id}/reject",
    response_model=PreRegistrationResponse,
    summary="Rechazar Pre-inscripción con motivo"
)
async def reject_submission(
    submission_id: PydanticObjectId,
    body: PreRegistrationReject,
    current_user: User = Depends(require_cpd)
) -> Any:
    from models.pre_registration import PreRegistration
    from models.enums import UserRole

    sub = await PreRegistration.get(submission_id)
    if not sub:
        raise HTTPException(status_code=404, detail="Pre-inscripción no encontrada.")
    form = await PreRegistrationForm.get(sub.form_id)
    if not form:
        raise HTTPException(status_code=404, detail="Formulario asociado no encontrado.")

    if current_user.rol == UserRole.CPD and form.programa_id is not None:
        raise HTTPException(status_code=403, detail="Esta pre-inscripción es para un programa específico.")
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        if form.programa_id not in cursos:
            raise HTTPException(status_code=403, detail="No tienes permiso para rechazar este formulario.")

    try:
        sub = await pre_registration_service.reject_submission(
            submission_id, current_user.username, body.motivo
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_submission(sub)


@router.get(
    "/counters",
    summary="Conteos globales (para badges en sidebar)"
)
async def counters(current_user: User = Depends(require_cpd)) -> Any:
    return await pre_registration_service.get_forms_counters()


# ============================================================================
# Helpers
# ============================================================================

async def _enrich_form(form: PreRegistrationForm) -> PreRegistrationFormResponse:
    """Agrega nombre de programa y conteos para la lista admin."""
    data = PreRegistrationFormResponse.model_validate(form, from_attributes=True)
    if form.programa_id:
        course = await _get_course(form.programa_id)
        if course:
            data.programa_nombre = course.nombre_programa
            data.programa_codigo = course.codigo
    data.submissions_total = await _count_submissions_for_form(form.id)
    data.submissions_pendientes = await _count_submissions_for_form(form.id, "pendiente")
    return data


async def _enrich_submission(sub) -> PreRegistrationResponse:
    """Agrega nombre de form y programa para la lista admin."""
    data = PreRegistrationResponse.model_validate(sub, from_attributes=True)
    form = await PreRegistrationForm.get(sub.form_id)
    if form:
        data.form_nombre = form.nombre
        if form.programa_id:
            data.programa_id = form.programa_id
            course = await _get_course(form.programa_id)
            if course:
                data.programa_nombre = course.nombre_programa
    return data


_course_cache: dict = {}


async def _get_course(course_id):
    if course_id in _course_cache:
        return _course_cache[course_id]
    course = await Course.get(course_id)
    if course:
        _course_cache[course_id] = course
    return course


async def _count_submissions_for_form(form_id, estado: Optional[str] = None) -> int:
    from models.pre_registration import PreRegistration
    query: dict = {"form_id": form_id}
    if estado:
        query["estado"] = estado
    return await PreRegistration.find(query).count()
