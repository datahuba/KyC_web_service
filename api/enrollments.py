"""
API de Inscripciones (Enrollments)
==================================

Endpoints para gestionar inscripciones de estudiantes a cursos.

Permisos (Según Jerarquía UAGRM):
---------
- POST /enrollments/: CPD, ADMIN, SUPERADMIN
- GET /enrollments/: STAFF (todos) / STUDENT (solo las suyas)
- GET /enrollments/{id}: STAFF / STUDENT (si es suya)
- PATCH /enrollments/{id}: CPD, ADMIN, SUPERADMIN
- DELETE /enrollments/{id}: SOLO SUPERADMIN
- GET /enrollments/student/{student_id}: STAFF / STUDENT (si es él mismo)
- GET /enrollments/course/{course_id}: DOCENTES, STAFF
- Requisitos KYC: CPD aprueba/rechaza
"""

from typing import List, Any, Optional, Union
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Path
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.user import User
from models.enums import EstadoInscripcion, EstadoRequisito, UserRole
from core.cloudinary_utils import upload_image, upload_pdf
from schemas.requisito import RequisitoResponse, RequisitoRechazarRequest, RequisitoListResponse
from schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithDetails,
    ModuloNotaUpdate
)
from services import enrollment_service, payment_service
from beanie import PydanticObjectId

# Nuevas dependencias de seguridad del ISSUE L
from api.dependencies import require_superadmin, require_cpd, require_staff, require_docente, get_current_user, filtro_cursos_por_rol, require_encargado_curso, require_mae

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math


@router.post(
    "/",
    response_model=EnrollmentResponse,
    status_code=201,
    summary="Crear Inscripción"
)
async def create_enrollment(
    *,
    enrollment_in: EnrollmentCreate,
    current_user: User = Depends(require_encargado_curso) # <-- CPD, ENCARGADO_CURSO, COORDINADOR o superior (ISSUE-R-ROLES)
) -> Any:
    """Crear nueva inscripción de estudiante a un curso"""
    # ISSUE-R-ROLES: un Encargado de Curso solo puede inscribir en sus cursos asignados
    if current_user.rol == UserRole.ENCARGADO_CURSO and enrollment_in.curso_id not in current_user.cursos_asignados:
        raise HTTPException(status_code=403, detail="No tienes asignado este curso")

    try:
        enrollment = await enrollment_service.create_enrollment(
            enrollment_in=enrollment_in,
            admin_username=current_user.username
        )
        enriched_enrollment = await enrollment_service.enrich_enrollment_dates(enrollment)
        return enriched_enrollment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/",
    response_model=PaginatedResponse[EnrollmentResponse],
    summary="Listar Inscripciones"
)
async def list_enrollments(
    *,
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=500, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por estudiante o curso"),
    estado: Optional[EstadoInscripcion] = Query(None, description="Filtrar por estado"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Curso ID"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Estudiante ID"),
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Listar inscripciones con paginación y filtros avanzados"""
    if isinstance(current_user, User):
        # Todo el STAFF (Mae, Cobranza, Cpd, Admin, Coordinador) puede leer la tabla;
        # ENCARGADO_CURSO se segmenta a sus cursos asignados (ISSUE-R-ROLES).
        filtro_rol = filtro_cursos_por_rol(current_user)
        cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None
        enrollments, total_count = await enrollment_service.get_all_enrollments(
            page=page, per_page=per_page, q=q, estado=estado,
            curso_id=curso_id, estudiante_id=estudiante_id,
            cursos_permitidos=cursos_permitidos
        )
    elif isinstance(current_user, Student):
        all_enrollments = await enrollment_service.get_enrollments_by_student(
            student_id=current_user.id
        )
        if estado:
            all_enrollments = [e for e in all_enrollments if e.estado == estado]
        total_count = len(all_enrollments)
        start = (page - 1) * per_page
        end = start + per_page
        enrollments = all_enrollments[start:end]
    else:
        raise HTTPException(status_code=403, detail="No autorizado")

    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1
    
    enriched_enrollments = []
    for enrollment in enrollments:
        enriched = await enrollment_service.enrich_enrollment_dates(enrollment)
        enriched_enrollments.append(enriched)
    
    return {
        "data": enriched_enrollments,
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total_count,
            totalPages=total_pages, hasNextPage=has_next, hasPrevPage=has_prev
        )
    }


@router.get(
    "/{id}",
    response_model=EnrollmentResponse,
    summary="Ver Inscripción"
)
async def get_enrollment(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Ver detalles completos de una inscripción"""
    enrollment = await enrollment_service.get_enrollment(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
            
    enriched_enrollment = await enrollment_service.enrich_enrollment_dates(enrollment)
    return enriched_enrollment


@router.patch(
    "/{id}",
    response_model=EnrollmentResponse,
    summary="Actualizar Inscripción"
)
async def update_enrollment(
    *,
    id: PydanticObjectId,
    enrollment_in: EnrollmentUpdate,
    current_user: User = Depends(require_cpd) # <-- CPD ACTUALIZA INSCRIPCIONES
) -> Any:
    """Actualizar inscripción existente"""
    try:
        if enrollment_in.descuento_personalizado is not None:
            enrollment = await enrollment_service.update_enrollment_descuento(
                enrollment_id=id,
                descuento_personalizado=enrollment_in.descuento_personalizado,
                admin_username=current_user.username
            )
        
        if enrollment_in.estado is not None:
            enrollment = await enrollment_service.cambiar_estado_enrollment(
                enrollment_id=id,
                nuevo_estado=enrollment_in.estado,
                admin_username=current_user.username
            )
        
        if enrollment_in.descuento_personalizado is None and enrollment_in.estado is None:
            enrollment = await enrollment_service.get_enrollment(id)
            if not enrollment:
                raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        
        return enrollment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{id}",
    response_model=EnrollmentResponse,
    summary="Eliminar Inscripción"
)
async def delete_enrollment(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin) # <-- SOLO SUPERADMIN BORRA
) -> Any:
    """Eliminar inscripción manualmente"""
    from models.enums import UserRole
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo SUPERADMIN puede eliminar inscripciones"
        )
    
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    
    student = await Student.get(enrollment.estudiante_id)
    if student and enrollment.curso_id in student.lista_cursos_ids:
        student.lista_cursos_ids.remove(enrollment.curso_id)
        await student.save()

    course = await Course.get(enrollment.curso_id)
    if course and enrollment.estudiante_id in course.inscritos:
        course.inscritos.remove(enrollment.estudiante_id)
        await course.save()
        
    await enrollment.delete()
    return enrollment


@router.get("/student/{student_id}", response_model=List[EnrollmentResponse])
async def get_enrollments_by_student(
    *,
    student_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Obtener todas las inscripciones de un estudiante"""
    if isinstance(current_user, Student):
        if student_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
    
    enrollments = await enrollment_service.get_enrollments_by_student(student_id)
    return enrollments


@router.get("/course/{course_id}", response_model=List[EnrollmentResponse])
async def get_enrollments_by_course(
    *,
    course_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user) # <-- PERMISO ABIERTO PARA QUE DOCENTES INGRESEN
) -> Any:
    """Obtener todas las inscripciones de un curso (Planilla)"""
    if isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Los estudiantes no tienen acceso a planillas de cursos.")
        
    enrollments = await enrollment_service.get_enrollments_by_course(course_id)
    return enrollments


@router.get(
    "/{id}/next-payment",
    summary="Ver Siguiente Pago Pendiente"
)
async def get_next_payment_info(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Obtiene la información sugerida para el próximo pago."""
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(403, "No es tu enrollment")
            
    next_payment = await payment_service.get_next_pending_payment(id)
    if not next_payment:
        return None
        
    return next_payment


# ========================================================================
# ENDPOINTS ACADÉMICOS (ISSUE P - NOTAS POR MÓDULO)
# ========================================================================
@router.patch("/{id}/modulos/{index}/nota", response_model=EnrollmentResponse, summary="Calificar Módulo")
async def update_modulo_nota(
    *, 
    id: PydanticObjectId, 
    index: int = Path(..., ge=0, description="Índice del módulo en el array (0, 1, 2...)"),
    nota_update: ModuloNotaUpdate,
    current_user: User = Depends(require_docente) # Docentes, CPD, Admins
) -> Any:
    """
    ISSUE-Q-NOTA-BORRADOR: si el usuario es DOCENTE, la nota queda como BORRADOR
    pendiente de validación de CPD (no afecta promedio ni beca todavía).
    Si es CPD/ADMIN/SUPERADMIN, califica directamente (comportamiento actual,
    sin cambios: recalcula promedio y aplica lógica de beca por nota mínima).
    """
    try:
        # BUG R FIX: Verificación de desfase de array y existencia de módulos
        enrollment = await Enrollment.get(id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
            
        if not enrollment.modulos or len(enrollment.modulos) == 0:
            raise HTTPException(
                status_code=400, 
                detail="El estudiante tiene una inscripción antigua (sin módulos). Solicita al CPD que actualice su inscripción."
            )
            
        if index >= len(enrollment.modulos):
            raise HTTPException(
                status_code=400, 
                detail=f"Índice del módulo ({index}) inválido. El estudiante solo tiene {len(enrollment.modulos)} módulos registrados."
            )
            
        username = current_user.username if hasattr(current_user, 'username') else "docente_autorizado"

        if current_user.rol == UserRole.DOCENTE:
            updated_enrollment = await enrollment_service.subir_nota_borrador(
                enrollment_id=id, modulo_index=index, nota_borrador=nota_update.nota
            )
        else:
            updated_enrollment = await enrollment_service.actualizar_nota_modulo(
                enrollment_id=id,
                modulo_index=index,
                nota=nota_update.nota,
                evaluador_username=username
            )
        return await enrollment_service.enrich_enrollment_dates(updated_enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/modulos/{index}/nota/validar",
    response_model=EnrollmentResponse,
    summary="Validar Borrador de Nota (CPD)"
)
async def validar_modulo_nota(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0),
    current_user: User = Depends(require_cpd)  # CPD, ADMIN, SUPERADMIN
) -> Any:
    """ISSUE-Q-NOTA-BORRADOR: convierte el borrador del docente en nota oficial."""
    try:
        updated = await enrollment_service.validar_nota_borrador(id, index, current_user.username)
        return await enrollment_service.enrich_enrollment_dates(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/modulos/{index}/nota/rechazar",
    response_model=EnrollmentResponse,
    summary="Rechazar Borrador de Nota (CPD)"
)
async def rechazar_modulo_nota(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0),
    current_user: User = Depends(require_cpd)
) -> Any:
    """ISSUE-Q-NOTA-BORRADOR: descarta el borrador propuesto por el docente."""
    try:
        updated = await enrollment_service.rechazar_nota_borrador(id, index)
        return await enrollment_service.enrich_enrollment_dates(updated)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========================================================================
# ENDPOINTS DE REQUISITOS (KYC)
# ========================================================================

@router.get("/{id}/requisitos", response_model=RequisitoListResponse)
async def listar_requisitos(
    *, id: PydanticObjectId, current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Enrollment no encontrado")
    
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(403, "No puedes ver requisitos de otros estudiantes")
    
    total = len(enrollment.requisitos)
    pendientes = sum(1 for r in enrollment.requisitos if r.estado == EstadoRequisito.PENDIENTE)
    en_proceso = sum(1 for r in enrollment.requisitos if r.estado == EstadoRequisito.EN_PROCESO)
    aprobados = sum(1 for r in enrollment.requisitos if r.estado == EstadoRequisito.APROBADO)
    rechazados = sum(1 for r in enrollment.requisitos if r.estado == EstadoRequisito.RECHAZADO)
    
    return {
        "total": total, "pendientes": pendientes, "en_proceso": en_proceso,
        "aprobados": aprobados, "rechazados": rechazados, "requisitos": enrollment.requisitos
    }


@router.put("/{id}/requisitos/{index}", response_model=RequisitoResponse)
async def subir_requisito(
    *, id: PydanticObjectId, index: int = Path(..., ge=0), file: UploadFile = File(...),
    current_user: Student = Depends(get_current_user)
) -> Any:
    if not isinstance(current_user, Student):
        raise HTTPException(403, "Solo estudiantes")
    
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if enrollment.estudiante_id != current_user.id:
        raise HTTPException(403, "No es tu enrollment")
    
    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice {index} fuera de rango")
    
    try:
        folder = f"enrollments/{id}/requisitos"
        descripcion_safe = enrollment.requisitos[index].descripcion.replace(' ', '_').replace('/', '_')
        public_id = f"req_{index}_{descripcion_safe}"
        
        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        if file.content_type in image_types:
            documento_url = await upload_image(file, folder, public_id)
        elif file.content_type == "application/pdf":
            documento_url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(400, f"Formato no permitido: {file.content_type}")
        
        enrollment.requisitos[index].subir_documento(documento_url)
        await enrollment.save()
        return enrollment.requisitos[index]
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@router.put("/{id}/requisitos/{index}/aprobar", response_model=RequisitoResponse)
async def aprobar_requisito(
    *, id: PydanticObjectId, index: int = Path(..., ge=0), current_user: User = Depends(require_cpd) # <-- CPD APRUEBA
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice fuera de rango")
    
    requisito = enrollment.requisitos[index]
    if not requisito.url:
        raise HTTPException(400, "Sin documento")
    if requisito.estado not in [EstadoRequisito.EN_PROCESO, EstadoRequisito.RECHAZADO]:
        raise HTTPException(400, "Estado incorrecto")
    
    enrollment.requisitos[index].aprobar(current_user.username)
    await enrollment.save()
    return enrollment.requisitos[index]


@router.put("/{id}/requisitos/{index}/rechazar", response_model=RequisitoResponse)
async def rechazar_requisito(
    *, id: PydanticObjectId, index: int = Path(..., ge=0), rechazo: RequisitoRechazarRequest,
    current_user: User = Depends(require_cpd) # <-- CPD RECHAZA
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice fuera de rango")
    
    requisito = enrollment.requisitos[index]
    if not requisito.url:
        raise HTTPException(400, "Sin documento")
    if requisito.estado != EstadoRequisito.EN_PROCESO:
        raise HTTPException(400, "Estado incorrecto")
    
    enrollment.requisitos[index].rechazar(current_user.username, rechazo.motivo)
    await enrollment.save()
    return enrollment.requisitos[index]


@router.post(
    "/{id}/beca-respaldo",
    response_model=EnrollmentResponse,
    summary="Subir Respaldo Documental de Beca"
)
async def subir_beca_respaldo(
    *,
    id: PydanticObjectId,
    file: UploadFile = File(...),
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN (ISSUE-P-BECA-RESPALDO)
) -> Any:
    """
    Sube (o reemplaza) el documento de respaldo de la beca/descuento aplicado a
    esta inscripción. No bloquea ni exige nada al crear/editar la inscripción;
    es un adjunto que puede subirse en cualquier momento posterior.
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Inscripción no encontrada")

    try:
        folder = f"enrollments/{id}/beca_respaldo"
        public_id = "respaldo"

        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        if file.content_type in image_types:
            url = await upload_image(file, folder, public_id)
        elif file.content_type == "application/pdf":
            url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(400, f"Formato no permitido: {file.content_type}")

        enrollment.beca_respaldo_url = url
        enrollment.updated_at = datetime.utcnow()
        await enrollment.save()
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@router.post(
    "/{id}/matricula-exenta",
    response_model=EnrollmentResponse,
    summary="Otorgar Matrícula Exenta (MAE)"
)
async def otorgar_matricula_exenta_endpoint(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_mae)  # <-- SOLO MAE, ADMIN, SUPERADMIN (ISSUE-M-EXENCION)
) -> Any:
    """
    Autoriza a un estudiante a cursar académicamente sin haber pagado la
    matrícula institucional. NO condona la deuda financiera: `saldo_pendiente`
    y `matricula_pagada` no se alteran, Cobranza sigue viendo y cobrando la
    deuda con normalidad. Solo desbloquea el estado académico.
    """
    try:
        enrollment = await enrollment_service.otorgar_matricula_exenta(
            enrollment_id=id, otorgado_por=current_user.username
        )
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{id}/matricula-exenta",
    response_model=EnrollmentResponse,
    summary="Revocar Matrícula Exenta (MAE)"
)
async def revocar_matricula_exenta_endpoint(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_mae)  # <-- SOLO MAE, ADMIN, SUPERADMIN (ISSUE-M-EXENCION)
) -> Any:
    """
    Revoca una exención de matrícula previamente otorgada. Si la matrícula
    real sigue sin pagarse, el estudiante vuelve a estado PENDIENTE_PAGO
    (se re-bloquea el acceso académico).
    """
    try:
        enrollment = await enrollment_service.revocar_matricula_exenta(enrollment_id=id)
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========================================================================
# ISSUE-P-CONGELADO: Congelamiento voluntario y reactivación desde
# congelamiento/abandono. Reutiliza EstadoInscripcion.SUSPENDIDO (mismo
# patrón que ISSUE-R-SOLICITUD-PASIVO) diferenciado por motivo_suspension.
# ========================================================================

@router.post(
    "/{id}/congelar",
    response_model=EnrollmentResponse,
    summary="Congelar Inscripción (CPD)"
)
async def congelar_enrollment_endpoint(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN
) -> Any:
    """
    Congelamiento voluntario de estudios (tasa fija, configurable vía
    settings.TASA_CONGELAMIENTO_BS). Distinto de 'Solicitar Pasivo'
    (ISSUE-R-SOLICITUD-PASIVO): el congelamiento es una acción directa del
    CPD, no requiere flujo de solicitud/aprobación por separado.
    """
    from services import congelado_service
    try:
        enrollment = await congelado_service.congelar_inscripcion(
            enrollment_id=id, registrado_por=current_user.username
        )
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/{id}/reactivar-congelado",
    response_model=EnrollmentResponse,
    summary="Reactivar Inscripción Congelada o en Abandono (CPD)"
)
async def reactivar_congelado_endpoint(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN
) -> Any:
    """
    Reactiva una inscripción SUSPENDIDA por congelamiento o abandono. Si el
    motivo fue 'abandono', marca `multa_reincorporacion_pendiente=True` para
    que Cobranza sepa que corresponde cobrar la multa (no se genera un
    Payment automático).
    """
    from services import congelado_service
    try:
        enrollment = await congelado_service.reactivar_desde_congelado_o_abandono(
            enrollment_id=id, admin_username=current_user.username
        )
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/jobs/verificar-inactividad",
    summary="Disparo Manual del Job de Inactividad (Congelado/Mora/Abandono)"
)
async def disparar_verificacion_inactividad(
    *,
    enrollment_id: Optional[PydanticObjectId] = Query(
        None, description="Si se provee, acota la verificación SOLO a esta inscripción (recomendado para pruebas puntuales)."
    ),
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN
) -> Any:
    """
    Ejecuta manualmente la verificación de inactividad de pagos (la misma
    lógica que corre automáticamente cada 24h). Sin `enrollment_id` revisa
    TODAS las inscripciones activas/pendientes reales — usar con cuidado en
    producción. Con `enrollment_id` acota la revisión a una sola inscripción.
    """
    from services import congelado_service
    ids = [enrollment_id] if enrollment_id else None
    resultado = await congelado_service.verificar_inactividad_pagos(enrollment_ids=ids)
    return resultado
