"""
Router de Pre-registro de Estudiantes
======================================

ISSUE-Q-PRE-REGISTRO-FORM (2026-07-17): formularios dinámicos para que
visitantes externos llenen sus datos y CPD/Encargado los apruebe para
crearles un Student + User con la convención 'Uagrm.<CI>'.

Endpoints:
  PÚBLICOS (sin auth):
    GET  /pre-registrations/public/{slug}                -> ver form por slug
    POST /pre-registrations/public/{slug}                -> enviar submission
    POST /pre-registrations/public/{slug}/upload-carta   -> subir carta firmada (F-2026-08-11-CAMPOS-EC-MODALIDAD)

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
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
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
from core.cloudinary_utils import upload_document
from api.dependencies import require_superadmin, require_cpd, require_encargado_curso

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


# F-2026-08-11-CAMPOS-EC-MODALIDAD: endpoint público para subir la carta
# firmada por el director desde el wizard de preinscripción. Reusa Cloudinary
# (ya configurado en el sistema) en lugar de guardar archivos en disco local,
# porque (a) el sistema ya tiene Cloudinary operativo, (b) la URL resultante
# es https pública y se puede servir directamente, (c) el contenedor se puede
# reiniciar sin perder los archivos.
#
# Tipos permitidos: PDF, JPG, PNG. Tamaño max: 20MB (mismo limite que
# upload_document de cloudinary_utils). El endpoint es público (sin auth)
# porque el visitante del wizard no está logueado.
@router.post(
    "/public/{slug}/upload-carta",
    summary="Subir carta firmada por el director (público, sin auth)"
)
async def upload_carta_firmada(slug: str, file: UploadFile = File(...)) -> Any:
    """
    Sube la carta firmada (PDF/JPG/PNG, max 20MB) a Cloudinary y devuelve
    la URL publica que el frontend guarda en `cartaFirmadaUrl`.

    Valida que el slug exista y el formulario este abierto (no requiere auth).
    """
    # Validar que el form exista y este abierto (reusa la misma validacion
    # que submit_public_form)
    try:
        await pre_registration_service.get_public_form_by_slug(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Subir a Cloudinary en folder dedicado. Reusa la funcion generica
    # upload_document que ya valida tipo y tamaño (max 20MB).
    try:
        result = await upload_document(
            file=file,
            folder=f"pre-registrations/cartas-firmadas/{slug}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir la carta firmada: {str(e)}",
        )

    return {
        "url": result["url"],
        "public_id": result["public_id"],
        "resource_type": result["resource_type"],
        "mime_type": result["mime_type"],
        "size_bytes": result["size_bytes"],
    }


# F-2026-08-11-CAMPOS-EC-RESOLUCION (Kevin 22:37): el estudiante puede subir
# opcionalmente la resolucion de BECA / DESCUENTO al que se inscribe
# (PDF que emite Vicerrectorado aprobando el descuento). NO es la resolucion
# del programa (eso lo emite el CPD/admin), sino la resolucion que aplica el
# descuento del estudiante (educacion continua tiene descuentos por convenio,
# por vinculo familiar con la UAGRM, etc).
#
# Es OPCIONAL porque a veces la resolucion la sube el admin despues. Pero si
# el estudiante ya la tiene a mano, puede incluirla aca para ahorrar tiempo
# al encargado de EC.
#
# Misma mecanica que upload-carta: valida que el form exista y este abierto,
# sube a Cloudinary (folder dedicado), devuelve la URL publica.
@router.post(
    "/public/{slug}/upload-resolucion-beca",
    summary="Subir resolucion de beca/descuento (publico, opcional, sin auth)"
)
async def upload_resolucion(slug: str, file: UploadFile = File(...)) -> Any:
    """
    Sube la resolucion de beca/descuento (PDF/JPG/PNG, max 20MB) a Cloudinary
    y devuelve la URL publica que el frontend guarda en `resolucionUrl`.

    Valida que el slug exista y el formulario este abierto (no requiere auth).
    """
    try:
        await pre_registration_service.get_public_form_by_slug(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await upload_document(
            file=file,
            folder=f"pre-registrations/resoluciones-beca/{slug}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir la resolucion de beca: {str(e)}",
        )

    return {
        "url": result["url"],
        "public_id": result["public_id"],
        "resource_type": result["resource_type"],
        "mime_type": result["mime_type"],
        "size_bytes": result["size_bytes"],
    }


# F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12, reunion UAGRM):
# el estudiante que NO es primera carrera debe subir una foto o escaneo
# del titulo profesional. El encargado de educacion continua lo valida
# desde el modal de detalle de la submission.
#
# Misma mecanica que upload-carta y upload-resolucion-beca: valida que el
# form exista y este abierto, sube a Cloudinary (folder dedicado), devuelve
# la URL publica que el frontend guarda en `tituloProfesionalUrl`.
@router.post(
    "/public/{slug}/upload-titulo",
    summary="Subir foto del titulo profesional (publico, sin auth, requerido si NO es primer carrera)"
)
async def upload_titulo_profesional(slug: str, file: UploadFile = File(...)) -> Any:
    """
    Sube la foto del titulo profesional (PDF/JPG/PNG, max 20MB) a Cloudinary
    y devuelve la URL publica que el frontend guarda en `tituloProfesionalUrl`.

    Valida que el slug exista y el formulario este abierto (no requiere auth).
    El estudiante solo la sube si respondio que NO es primera carrera en la
    UAGRM (es_primer_carrera=False). El encargado de educacion continua
    valida el documento desde el modal de detalle de la submission.
    """
    try:
        await pre_registration_service.get_public_form_by_slug(slug)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await upload_document(
            file=file,
            folder=f"pre-registrations/titulos-profesionales/{slug}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir el titulo profesional: {str(e)}",
        )

    return {
        "url": result["url"],
        "public_id": result["public_id"],
        "resource_type": result["resource_type"],
        "mime_type": result["mime_type"],
        "size_bytes": result["size_bytes"],
    }


# ============================================================================
# ADMIN (auth) — prefijo /pre-registrations/forms y /pre-registrations/submissions
# ============================================================================

@router.get(
    "/forms",
    response_model=PaginatedResponse[PreRegistrationFormResponse],
    summary="Listar Formularios visibles para mi rol"
)
@router.get(
	"/forms",
	response_model=PaginatedResponse[PreRegistrationFormResponse],
	summary="Listar Formularios visibles para mi rol"
)
async def list_forms(
	page: int = Query(1, ge=1),
	per_page: int = Query(20, ge=1, le=100),
	current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-FIX-COUNTERS-403: encargado_curso/coordinador tambien pueden listar forms
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
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-FIX-COUNTERS-403: encargado_curso/coordinador tambien pueden ver forms individuales
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
    summary="Crear Formulario (encargado EC / super admin)"
)
async def create_form(
    data: PreRegistrationFormCreate,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO: encargado_curso y coordinador (educacion continua) pueden crear formularios.
) -> Any:
    try:
        form = await pre_registration_service.create_form(data, current_user.username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.patch(
    "/forms/{form_id}",
    response_model=PreRegistrationFormResponse,
    summary="Editar Formulario (encargado EC / super admin)"
)
async def update_form(
    form_id: PydanticObjectId,
    data: PreRegistrationFormUpdate,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO
) -> Any:
    try:
        form = await pre_registration_service.update_form(form_id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await _enrich_form(form)


@router.post(
    "/forms/{form_id}/close",
    response_model=PreRegistrationFormResponse,
    summary="Cerrar Formulario manualmente (encargado EC / super admin)"
)
async def close_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO
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
    summary="Reabrir Formulario (encargado EC / super admin)"
)
async def reopen_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO
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
    response_class=Response,
    summary="Eliminar Formulario (encargado EC / super admin)"
)
async def delete_form(
    form_id: PydanticObjectId,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO
):
    try:
        await pre_registration_service.delete_form(form_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
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
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-FIX-COUNTERS-403: encargado_curso/coordinador tambien pueden listar submissions
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
    # F-FIX-PRE-REGISTROS-EC-APPROVE (2026-08-12, Kevin): el EC (encargado
    # de curso) tiene un rol activo en el panel de pre-registros (valida
    # titulo, valida descuento, ve detalle, etc) y DEBE poder aprobar
    # pre-inscripciones de los cursos que le corresponden. Antes solo
    # CPD/ADMIN/SUPERADMIN podian aprobar porque el decorador era
    # `require_cpd`. Eso bloqueaba al EC con 403 ANTES de llegar a la
    # logica del check de cursos_asignados que ya estaba abajo. Cambiar
    # a `require_encargado_curso` permite al EC llegar al check, y la
    # logica valida que la submission sea de un curso que le pertenece.
    current_user: User = Depends(require_encargado_curso)
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
    # F-FIX-PRE-REGISTROS-EC-APPROVE (2026-08-12, Kevin): mismo fix que
    # approve_submission. El EC debe poder rechazar pre-inscripciones
    # de sus cursos.
    current_user: User = Depends(require_encargado_curso)
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
async def counters(current_user: User = Depends(require_encargado_curso)) -> Any: # F-2026-08-11-EC-FIX-COUNTERS-403: encargado_curso/coordinador tambien pueden ver badges de counters
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
