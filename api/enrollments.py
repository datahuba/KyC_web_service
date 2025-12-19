"""
API de Inscripciones (Enrollments)
==================================

Endpoints para gestionar inscripciones de estudiantes a cursos.

Permisos:
---------
- POST /enrollments/: ADMIN/SUPERADMIN
- GET /enrollments/: ADMIN (todas) / STUDENT (solo las suyas)
- GET /enrollments/{id}: ADMIN / STUDENT (si es suya)
- PATCH /enrollments/{id}: ADMIN/SUPERADMIN
- GET /enrollments/student/{student_id}: ADMIN / STUDENT (si es él mismo)
- GET /enrollments/course/{course_id}: ADMIN
"""

from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Path
from models.enrollment import Enrollment
from models.student import Student
from models.user import User
from models.enums import EstadoInscripcion, EstadoRequisito
from core.cloudinary_utils import upload_image, upload_pdf
from schemas.requisito import RequisitoResponse, RequisitoRechazarRequest, RequisitoListResponse
from schemas.enrollment import (
    EnrollmentCreate,
    EnrollmentResponse,
    EnrollmentUpdate,
    EnrollmentWithDetails
)
from services import enrollment_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()


@router.post(
    "/",
    response_model=EnrollmentResponse,
    status_code=201,
    summary="Crear Inscripción",
    responses={
        201: {"description": "Inscripción creada exitosamente. Los requisitos del curso se copian automáticamente."},
        400: {"description": "Error de validación: estudiante ya inscrito, curso/estudiante no existe, etc."},
        403: {"description": "Sin permisos - Solo Admin/SuperAdmin"},
        404: {"description": "Estudiante o curso no encontrado"}
    }
)
async def create_enrollment(
    *,
    enrollment_in: EnrollmentCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nueva inscripción de estudiante a un curso
    
    **Requiere:** Admin o SuperAdmin
    
    **El sistema automáticamente:**
    - ✅ Aplica precio según tipo de estudiante (interno/externo)
    - ✅ Calcula descuentos (curso + personalizado)
    - ✅ Copia requisitos del curso al enrollment
    - ✅ Inicializa requisitos en estado "pendiente"
    - ✅ Calcula total a pagar y saldo pendiente
    
    **Validaciones:**
    - Estudiante existe y está activo
    - Curso existe y está activo
    - Estudiante NO está ya inscrito en ese curso
    
    **Sistema de Doble Descuento:**
    1. Descuento del Curso (nivel 1): Se aplica del curso al monto base
    2. Descuento Personalizado (nivel 2): Se aplica sobre el resultado anterior
    
    **Ejemplo de cálculo:**
    ```
    Precio base: 3000 Bs
    - Descuento curso (10%): -300 Bs → 2700 Bs
    - Descuento personal (5%): -135 Bs → 2565 Bs
    Total a pagar: 2565 Bs
    ```
    """
    try:
        enrollment = await enrollment_service.create_enrollment(
            enrollment_in=enrollment_in,
            admin_username=current_user.username
        )
        return enrollment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


from schemas.common import PaginatedResponse, PaginationMeta
import math

@router.get(
    "/",
    response_model=PaginatedResponse[EnrollmentResponse],
    summary="Listar Inscripciones",
    responses={
        200: {"description": "Lista de inscripciones con paginación y filtros"},
        403: {"description": "Sin permisos"}
    }
)
async def list_enrollments(
    *,
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=500, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por estudiante o curso"),
    estado: Optional[EstadoInscripcion] = Query(None, description="Filtrar por estado"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Curso ID"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Estudiante ID"),
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Listar inscripciones con paginación y filtros avanzados
    
    **Permisos:**
    - **Admin:** Ve TODAS las inscripciones con filtros avanzados
    - **Estudiante:** Ve SOLO sus propias inscripciones
    
    **Filtros disponibles (Admin):**
    - `q`: Búsqueda por nombre de estudiante o curso
    - `estado`: Filtrar por estado (pendiente_pago, activo, etc.)
    - `curso_id`: Ver inscritos de un curso específico
    - `estudiante_id`: Ver inscripciones de un estudiante
    
    **Paginación:**
    - `page`: Número de página (default: 1)
    - `per_page`: Elementos por página (default: 10, max: 500)
    
    **Retorna:**
    ```json
    {
      "data": [...],
      "meta": {
        "page": 1,
        "limit": 10,
        "totalItems": 36,
        "totalPages": 4,
        "hasNextPage": true,
        "hasPrevPage": false
      }
    }
    ```
    """
    # Si es admin, retorna todas (paginadas en DB)
    if isinstance(current_user, User):
        enrollments, total_count = await enrollment_service.get_all_enrollments(
            page=page,
            per_page=per_page,
            q=q,
            estado=estado,
            curso_id=curso_id,
            estudiante_id=estudiante_id
        )
    
    # Si es estudiante, solo sus inscripciones (paginadas en memoria por ahora)
    elif isinstance(current_user, Student):
        all_enrollments = await enrollment_service.get_enrollments_by_student(
            student_id=current_user.id
        )
        
        # Aplicar filtro de estado si lo pidió
        if estado:
            all_enrollments = [e for e in all_enrollments if e.estado == estado]
            
        total_count = len(all_enrollments)
        
        # Aplicar paginación manual
        start = (page - 1) * per_page
        end = start + per_page
        enrollments = all_enrollments[start:end]
    
    else:
        raise HTTPException(status_code=403, detail="No autorizado")

    # Calcular metadatos comunes
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": enrollments,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=has_next,
            hasPrevPage=has_prev
        )
    }


@router.get(
    "/{id}",
    response_model=EnrollmentResponse,
    summary="Ver Inscripción",
    responses={
        200: {"description": "Detalles completos de la inscripción"},
        403: {"description": "Sin permisos - Admin o estudiante dueño"},
        404: {"description": "Inscripción no encontrada"}
    }
)
async def get_enrollment(
    *,
    id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Ver detalles completos de una inscripción
    
    **Permisos:**
    - **Admin:** Puede ver cualquier inscripción
    - **Estudiante:** Solo puede ver sus propias inscripciones
    
    **Incluye:**
    - ✅ Información financiera (total, pagado, pendiente)
    - ✅ Siguiente pago calculado automáticamente
    - ✅ Snapshot de precios y descuentos
    - ✅ Estado de la inscripción
    - ✅ **Nota final** (si ha sido calificado)
    - ✅ Requisitos (lista completa con estados)
    - ✅ Cuotas pagadas vs totales
    """
    enrollment = await enrollment_service.get_enrollment(id)
    
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    
    # Si es estudiante, validar que sea suya
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver esta inscripción"
            )
    
    return enrollment


@router.patch(
    "/{id}",
    response_model=EnrollmentResponse,
    summary="Actualizar Inscripción",
    responses={
        200: {"description": "Inscripción actualizada exitosamente"},
        400: {"description": "Datos inválidos"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Inscripción no encontrada"}
    }
)
async def update_enrollment(
    *,
    id: PydanticObjectId,
    enrollment_in: EnrollmentUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar inscripción existente
    
    **Requiere:** Admin o SuperAdmin
    
    **Campos actualizables:**
    - `estado`: Cambiar estado de la inscripción
    - `descuento_personalizado`: Ajustar descuento manual (recalcula totales)
    - `nota_final`: Asignar/actualizar calificación (0-100) ⭐ NUEVO
    
    **Nota:** Los campos financieros (total_pagado, saldo_pendiente)
    se actualizan automáticamente cuando se registra un pago.
    
    **Ejemplo - Asignar nota:**
    ```json
    {
      "nota_final": 85.5
    }
    ```
    
    **Sistema recalcula automáticamente** totales si cambias descuentos.
    """
    try:
        # Actualizar descuento si se proporcionó
        if enrollment_in.descuento_personalizado is not None:
            enrollment = await enrollment_service.update_enrollment_descuento(
                enrollment_id=id,
                descuento_personalizado=enrollment_in.descuento_personalizado,
                admin_username=current_user.username
            )
        
        # Actualizar estado si se proporcionó
        if enrollment_in.estado is not None:
            enrollment = await enrollment_service.cambiar_estado_enrollment(
                enrollment_id=id,
                nuevo_estado=enrollment_in.estado,
                admin_username=current_user.username
            )
        
        # Si no se proporcionó nada, solo retornar la inscripción
        if enrollment_in.descuento_personalizado is None and enrollment_in.estado is None:
            enrollment = await enrollment_service.get_enrollment(id)
            if not enrollment:
                raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        
        return enrollment
    
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/student/{student_id}", response_model=List[EnrollmentResponse])
async def get_enrollments_by_student(
    *,
    student_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Obtener todas las inscripciones de un estudiante
    
    Permisos:
    - ADMIN: Puede ver inscripciones de cualquier estudiante
    - STUDENT: Solo puede ver sus propias inscripciones
    """
    # Si es estudiante, validar que pida sus propias inscripciones
    if isinstance(current_user, Student):
        if student_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver inscripciones de otros estudiantes"
            )
    
    enrollments = await enrollment_service.get_enrollments_by_student(student_id)
    return enrollments


@router.get("/course/{course_id}", response_model=List[EnrollmentResponse])
async def get_enrollments_by_course(
    *,
    course_id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Obtener todas las inscripciones de un curso (solo admins)
    
    Requiere: ADMIN o SUPERADMIN
    
    Útil para:
    - Ver lista de estudiantes inscritos
    - Generar reportes de un curso
    - Ver estado de pagos por curso
    """
    enrollments = await enrollment_service.get_enrollments_by_course(course_id)
    return enrollments


# ========================================================================
# ENDPOINTS DE REQUISITOS
# ========================================================================

@router.get(
    "/{id}/requisitos",
    response_model=RequisitoListResponse,
    summary="Ver Requisitos del Enrollment",
    responses={
        200: {"description": "Lista de requisitos con estadísticas"},
        403: {"description": "Sin permisos - Admin o estudiante dueño"},
        404: {"description": "Enrollment no encontrado"}
    }
)
async def listar_requisitos(
    *,
    id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Ver requisitos de una inscripción con estadísticas automáticas
    
    **Permisos:**
    - **Admin:** Puede ver requisitos de cualquier enrollment
    - **Estudiante:** Solo puede ver requisitos de sus enrollments
    
    **Retorna:**
    - `total`: Cantidad total de requisitos
    - `pendientes`: Requisitos sin subir
    - `en_proceso`: Requisitos subidos esperando revisión
    - `aprobados`: Requisitos aprobados por admin
    - `rechazados`: Requisitos rechazados (deben resubirse)
    
    **Estados posibles:**
    - `pendiente`: No subido aún
    - `en_proceso`: Subido, esperando revisión del admin
    - `aprobado`: Admin aprobó el documento
    - `rechazado`: Admin rechazó, debe resubir
    """
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
        "total": total,
        "pendientes": pendientes,
        "en_proceso": en_proceso,
        "aprobados": aprobados,
        "rechazados": rechazados,
        "requisitos": enrollment.requisitos
    }


@router.put(
    "/{id}/requisitos/{index}",
    response_model=RequisitoResponse,
    summary="Subir Documento de Requisito",
    responses={
        200: {"description": "Documento subido exitosamente, estado cambiado a 'en_proceso'"},
        400: {"description": "Índice fuera de rango o formato de archivo no permitido"},
        403: {"description": "Sin permisos - Solo el estudiante dueño"},
        404: {"description": "Enrollment no encontrado"}
    }
)
async def subir_requisito(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del requisito"),
    file: UploadFile = File(..., description="Documento PDF o imagen"),
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Subir documento para un requisito específico
    
    **Requiere:** El estudiante DUEÑO del enrollment
    
    **Parámetros:**
    - `id`: ID del enrollment
    - `index`: Índice del requisito (0, 1, 2...)
    - `file`: Archivo PDF o imagen
    
    **Archivos permitidos:**
    - PDF (máx 10MB)
    - Imágenes: JPG, PNG, WEBP (máx 5MB)
    
    **Índices:**
    Los requisitos están numerados desde 0:
    - [0] = Primer requisito
    - [1] = Segundo requisito
    
    **Resubida:**
    Si un requisito fue rechazado, puedes volver a subirlo usando el mismo índice.
    """
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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@router.put(
    "/{id}/requisitos/{index}/aprobar",
    response_model=RequisitoResponse,
    summary="Aprobar Requisito",
    responses={
        200: {"description": "Requisito aprobado exitosamente"},
        400: {"description": "No se puede aprobar: sin documento o estado incorrecto"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Enrollment no encontrado"}
    }
)
async def aprobar_requisito(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del requisito"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Aprobar un requisito subido por el estudiante
    
    **Requiere:** Admin o SuperAdmin
    
    **Validaciones automáticas:**
    - ✅ Verifica que tenga documento subido
    - ✅ Verifica estado: debe estar en `en_proceso` o `rechazado`
    
    **Lo que hace:**
    1. Cambia estado a `aprobado`
    2. Registra `revisado_por` (username del admin)
    3. Limpia `motivo_rechazo`
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice {index} fuera de rango")
    
    requisito = enrollment.requisitos[index]
    
    if not requisito.url:
        raise HTTPException(400, "No se puede aprobar sin documento")
    
    if requisito.estado not in [EstadoRequisito.EN_PROCESO, EstadoRequisito.RECHAZADO]:
        raise HTTPException(400, f"No se puede aprobar en estado {requisito.estado}")
    
    enrollment.requisitos[index].aprobar(current_user.username)
    await enrollment.save()
    
    return enrollment.requisitos[index]


@router.put(
    "/{id}/requisitos/{index}/rechazar",
    response_model=RequisitoResponse,
    summary="Rechazar Requisito",
    responses={
        200: {"description": "Requisito rechazado con motivo guardado"},
        400: {"description": "No se puede rechazar: sin documento o estado incorrecto"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Enrollment no encontrado"},
        422: {"description": "Motivo de rechazo requerido"}
    }
)
async def rechazar_requisito(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del requisito"),
    rechazo: RequisitoRechazarRequest,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Rechazar un requisito con motivo
    
    **Requiere:** Admin o SuperAdmin
    
    **Parámetros:**
    - `motivo`: **OBLIGATORIO** - Razón del rechazo
    
    **Ejemplos de motivos:**
    - "Imagen muy borrosa, no se lee el número de carnet"
    - "El CV está desactualizado"
    - "Documento incompleto, falta una cara del carnet"
    
    **El estudiante puede:**
    - Ver el motivo del rechazo
    - Volver a subir el mismo requisito
    - Al resubir, el estado vuelve a `en_proceso` y el motivo se limpia
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")
    
    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice {index} fuera de rango")
    
    requisito = enrollment.requisitos[index]
    
    if not requisito.url:
        raise HTTPException(400, "No se puede rechazar sin documento")
    
    if requisito.estado != EstadoRequisito.EN_PROCESO:
        raise HTTPException(400, f"No se puede rechazar en estado {requisito.estado}")
    
    enrollment.requisitos[index].rechazar(current_user.username, rechazo.motivo)
    await enrollment.save()
    
    return enrollment.requisitos[index]
