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
from pydantic import BaseModel, Field
from core.timezone_utils import utcnow_naive
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Path, Body
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
    ModuloNotaUpdate,
    BulkEnrollmentRequest,
    BulkEnrollmentResponse,
    BulkEnrollmentErrorItem,
)
from services import enrollment_service, payment_service
from beanie import PydanticObjectId
from beanie.operators import In

# Nuevas dependencias de seguridad del ISSUE L
from api.dependencies import require_superadmin, require_cpd, require_staff, require_docente, get_current_user, filtro_cursos_por_rol, require_encargado_curso, require_mae

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math


# ========================================================================
# SCHEMAS: F-070 - Validación de notas pendientes (ISSUE-Q-NOTA-BORRADOR)
# ========================================================================
class NotaPendienteItem(BaseModel):
    """Item de nota pendiente de validación (CPD/Superadmin)."""
    enrollment_id: str = Field(..., description="ID del enrollment")
    estudiante_id: str
    estudiante_nombre: str
    estudiante_registro: Optional[str] = None
    estudiante_ci: Optional[str] = None
    curso_id: str
    curso_codigo: str
    curso_nombre: Optional[str] = None
    modulo_index: int = Field(..., description="Índice 0-based del módulo")
    modulo_nombre: str
    nota_borrador: float
    docente_username: Optional[str] = None
    docente_nombre: Optional[str] = None
    fecha_subida: Optional[datetime] = None
    estado: str = Field(..., description="siempre 'pendiente_validacion'")


class NotasPendientesResponse(BaseModel):
    total: int
    items: List[NotaPendienteItem]
    filtros_aplicados: dict = Field(default_factory=dict)


class BulkValidarItem(BaseModel):
    enrollment_id: str
    modulo_index: int


class BulkValidarRequest(BaseModel):
    items: List[BulkValidarItem] = Field(..., min_length=1, max_length=200)


class BulkValidarResultado(BaseModel):
    enrollment_id: str
    modulo_index: int
    ok: bool
    error: Optional[str] = None
    nota_final: Optional[float] = None


class BulkValidarResponse(BaseModel):
    total: int
    exitosos: int
    fallidos: int
    resultados: List[BulkValidarResultado]


class EditarNotaRequest(BaseModel):
    """F-070: Editar una nota ya validada (CPD/Superadmin)."""
    nota: float = Field(..., ge=0, le=100)
    motivo: Optional[str] = Field(None, max_length=500, description="Motivo del ajuste (auditoría)")


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
            admin_username=current_user.nombre_visible  # ISSUE-R-PERFIL-GENERICO
        )
        enriched_enrollment = await enrollment_service.enrich_enrollment_dates(enrollment)
        return enriched_enrollment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post(
    "/bulk",
    response_model=BulkEnrollmentResponse,
    status_code=200,
    summary="[Staff] Inscripción en lote: múltiples estudiantes a un mismo programa",
)
async def create_enrollments_bulk(
    *,
    bulk_in: BulkEnrollmentRequest,
    current_user: User = Depends(require_encargado_curso),  # CPD, ENCARGADO_CURSO, COORDINADOR o superior
) -> Any:
    """
    F-INSCRIPCION-LOTE (2026-07-31): inscribe varios estudiantes al
    mismo programa en una sola operación. Pensado para cuando llega
    una lista de admitidos (excel del CPD / Coordinadores) y hay que
    matricularlos en masa.

    Comportamiento:
    - Itera secuencialmente (no asyncio.gather) para no perder
      actualizaciones de `course.inscritos` y `student.lista_cursos_ids`
      (esos modelos no tienen optimistic locking).
    - Si un estudiante ya está inscrito en el curso, se reporta como
      `ya_inscritos` (NO falla toda la operación).
    - Si un estudiante no existe o el curso no está activo, se reporta
      como `fallidos` con el motivo específico.
    - Aplica un mismo descuento_id o descuento_personalizado a todos
      (útil para becas grupales o promociones).

    Permisos:
    - superadmin / admin / cpd: cualquier curso.
    - encargado_curso: solo cursos en cursos_asignados.
    - coordinador: cualquier curso.
    """
    # 1. Verificar que el usuario puede inscribir en este curso
    if (
        current_user.rol == UserRole.ENCARGADO_CURSO
        and bulk_in.curso_id not in (current_user.cursos_asignados or [])
    ):
        raise HTTPException(
            status_code=403,
            detail="No tienes asignado este curso (encargado_curso).",
        )

    # 2. Cargar el curso UNA vez (reutilizado para todos los estudiantes)
    course = await Course.get(bulk_in.curso_id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    if not course.activo:
        raise HTTPException(
            status_code=400,
            detail="Este curso no está activo y no acepta nuevas inscripciones",
        )

    # 3. Pre-cargar todos los estudiantes (1 sola query Mongo, no N)
    estudiante_ids_unicos = list({str(eid) for eid in bulk_in.estudiantes_ids})
    students = await Student.find(
        {"_id": {"$in": [PydanticObjectId(sid) for sid in estudiante_ids_unicos]}}
    ).to_list()
    student_map: dict = {str(s.id): s for s in students}

    # 4. Iterar y crear inscripciones (secuencial para no chocar con
    # course.inscritos / student.lista_cursos_ids)
    exitosos = 0
    ya_inscritos_count = 0
    fallidos = 0
    enrollments_creados: List[EnrollmentResponse] = []
    errores: List[BulkEnrollmentErrorItem] = []

    for est_id in bulk_in.estudiantes_ids:
        est_id_str = str(est_id)
        try:
            student = student_map.get(est_id_str)
            if not student:
                raise ValueError(f"Estudiante {est_id_str} no encontrado")

            enrollment_in = EnrollmentCreate(
                estudiante_id=est_id,
                curso_id=bulk_in.curso_id,
                descuento_id=bulk_in.descuento_id,
                descuento_personalizado=bulk_in.descuento_personalizado,
            )
            # skip_link_updates=True: actualizamos course.inscritos /
            # student.lista_cursos_ids en batch al final (ver abajo)
            enrollment = await enrollment_service.create_enrollment(
                enrollment_in=enrollment_in,
                admin_username=current_user.nombre_visible,
                student=student,
                course=course,
                skip_link_updates=True,
            )
            enriched = await enrollment_service.enrich_enrollment_dates(enrollment)
            enrollments_creados.append(enriched)
            exitosos += 1
        except ValueError as e:
            msg = str(e)
            if "ya está inscrito" in msg.lower():
                ya_inscritos_count += 1
            else:
                fallidos += 1
                errores.append(BulkEnrollmentErrorItem(
                    estudiante_id=est_id_str,
                    error=msg,
                ))
        except Exception as e:
            fallidos += 1
            errores.append(BulkEnrollmentErrorItem(
                estudiante_id=est_id_str,
                error=f"Error inesperado: {str(e)}",
            ))

    # 5. Batch update de course.inscritos y student.lista_cursos_ids.
    # Como usamos `skip_link_updates=True` en create_enrollment para no
    # chocar con optimistic locking durante el loop, ahora actualizamos
    # las referencias cruzadas en una sola pasada.
    if exitosos > 0:
        inscritos_set = {str(e["estudiante_id"]) for e in enrollments_creados}
        # Actualizar course.inscritos (lista de PyObjectId)
        for sid_str in inscritos_set:
            sid = PydanticObjectId(sid_str)
            if sid not in course.inscritos:
                course.inscritos.append(sid)
        await course.save()
        # Actualizar student.lista_cursos_ids
        for s in students:
            if bulk_in.curso_id not in s.lista_cursos_ids:
                s.lista_cursos_ids.append(bulk_in.curso_id)
                await s.save()

    return BulkEnrollmentResponse(
        total_solicitados=len(bulk_in.estudiantes_ids),
        exitosos=exitosos,
        ya_inscritos=ya_inscritos_count,
        fallidos=fallidos,
        enrollments_creados=enrollments_creados,
        errores=errores,
    )


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
    con_descuento: Optional[bool] = Query(None, description="Filtrar solo inscripciones con (True) o sin (False) descuento personal aplicado"),
    descuento_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por un Discount específico"),
    requiere_accion_documentos: Optional[bool] = Query(None, description="Filtrar inscripciones con documentos pendientes de validación o subida"),
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
            cursos_permitidos=cursos_permitidos,
            con_descuento=con_descuento, descuento_id=descuento_id,
            requiere_accion_documentos=requiere_accion_documentos
        )
    elif isinstance(current_user, Student):
        all_enrollments = await enrollment_service.get_enrollments_by_student(
            student_id=current_user.id
        )
        if estado:
            all_enrollments = [e for e in all_enrollments if e.estado == estado]
        total_count = len(all_enrollments)
        total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
        has_next = page < total_pages
        has_prev = page > 1
        start = (page - 1) * per_page
        end = start + per_page
        enrollments = all_enrollments[start:end]
        # F-FIX-DESCONOCIDO-ENROLLMENTS (2026-08-09, Kevin): enriquecer
        # tambien para estudiantes (sus propias inscripciones) para que
        # vean el nombre del curso (no "Desconocido").
        enriched_enrollments = await enrollment_service.enrich_enrollments_batch(enrollments)
        # FIX-ISSUE-250 (2026-08-14): items + data (retro-compat).
        return {
            "items": enriched_enrollments,
            "data": enriched_enrollments,  # alias retro-compat
            "meta": PaginationMeta(
                page=page, limit=per_page, totalItems=total_count,
                totalPages=total_pages, hasNextPage=has_next, hasPrevPage=has_prev
            )
        }
    else:
        raise HTTPException(status_code=403, detail="No autorizado")

    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1

    # F-FIX-DESCONOCIDO-ENROLLMENTS (2026-08-09, Kevin): usar batch lookup
    # (2 queries: students + courses con In) en vez de N queries individuales.
    # Esto ademas joinea el nombre del estudiante/curso en el response,
    # arreglando el bug "Desconocido" del frontend.
    enriched_enrollments = await enrollment_service.enrich_enrollments_batch(enrollments)

    return {
        # FIX-ISSUE-250 (2026-08-14): items + data (retro-compat).
        "items": enriched_enrollments,
        "data": enriched_enrollments,  # alias retro-compat
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total_count,
            totalPages=total_pages, hasNextPage=has_next, hasPrevPage=has_prev
        )
    }


# F-070 (2026-07-22, reunión Lic. Miguel/Kevin): Endpoint para que CPD/Superadmin
# gestione las notas pendientes de validación de manera centralizada, en lugar
# de ir enrollment por enrollment. Surge del bug urgente: Miguel (socio de Kevin)
# tenía 51 notas cargadas en estado "pendiente_validacion" y no había forma
# rápida de aprobarlas todas. Aquí se listan y se aprueban en bulk.
# ========================================================================

async def _enriquecer_nota_pendiente(enrollment: Enrollment, modulo_index: int) -> Optional[NotaPendienteItem]:
    """Helper: toma un enrollment y un índice de módulo y construye el item de respuesta."""
    if not enrollment or not enrollment.modulos or modulo_index >= len(enrollment.modulos):
        return None
    modulo = enrollment.modulos[modulo_index]
    if modulo.estado_validacion_nota != "pendiente_validacion":
        return None

    # estudiante
    student = await Student.get(enrollment.estudiante_id)
    if not student:
        return None

    # curso
    course = await Course.get(enrollment.curso_id)
    curso_codigo = course.codigo if course and hasattr(course, "codigo") else "?"
    curso_nombre = course.nombre if course and hasattr(course, "nombre") else None

    # docente del módulo
    docente_username = None
    docente_nombre = None
    if course and hasattr(course, "modulos") and modulo_index < len(course.modulos):
        mod_docente = course.modulos[modulo_index]
        if hasattr(mod_docente, "docente_id") and mod_docente.docente_id:
            docente = await User.get(mod_docente.docente_id)
            if docente:
                docente_username = docente.username
                docente_nombre = docente.nombre_funcional or docente.nombre_visible or docente.username

    return NotaPendienteItem(
        enrollment_id=str(enrollment.id),
        estudiante_id=str(student.id),
        estudiante_nombre=student.nombre,
        estudiante_registro=student.registro,
        estudiante_ci=student.carnet_identidad,
        curso_id=str(enrollment.curso_id),
        curso_codigo=curso_codigo or "?",
        curso_nombre=curso_nombre,
        modulo_index=modulo_index,
        modulo_nombre=modulo.nombre,
        nota_borrador=modulo.nota_borrador,
        docente_username=docente_username,
        docente_nombre=docente_nombre,
        fecha_subida=enrollment.updated_at,
        estado="pendiente_validacion",
    )


@router.get(
    "/notas-pendientes",
    response_model=NotasPendientesResponse,
    summary="Listar notas pendientes de validación (CPD/Superadmin)",
)
async def listar_notas_pendientes(
    *,
    # F-070-FIX (2026-07-22): aceptar string vacío como None para no romper
    # cuando el frontend envíe ?curso_id= o ?estudiante_query= vacíos.
    # Usamos `str` y validamos manualmente. FastAPI/Pydantic intenta
    # convertir "" a PydanticObjectId antes del handler y eso retornaba 422.
    curso_id: Optional[str] = Query(None, description="Filtrar por curso (string vacío se ignora)"),
    modulo_index: Optional[int] = Query(None, ge=0, description="Filtrar por índice de módulo"),
    estudiante_query: Optional[str] = Query(None, description="Buscar por nombre, registro o CI"),
    current_user: User = Depends(require_cpd)
) -> Any:
    """
    F-070: Lista todos los enrollments con al menos un módulo en estado
    `pendiente_validacion`. Pensado para que CPD/Superadmin haga una pasada
    rápida de aprobación/rechazo.

    Permisos: CPD, ADMIN, SUPERADMIN (mismo criterio que validar/rechazar
    notas individuales).
    """
    # F-070-FIX: normalizar string vacío a None antes de validar el ObjectId
    from bson import ObjectId as _ObjectId
    if curso_id is not None and str(curso_id).strip() == "":
        curso_id = None
    if curso_id is not None:
        try:
            curso_id = _ObjectId(curso_id)
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=f"curso_id inválido: '{curso_id}' no es un ObjectId válido.",
            )
    if estudiante_query is not None and estudiante_query.strip() == "":
        estudiante_query = None
    # Filtro base: cualquier modulo con nota_borrador pendiente
    # (necesitamos un $elemMatch para que MongoDB evalúe cada elemento del array)
    match_dict: dict = {
        "modulos": {
            "$elemMatch": {"estado_validacion_nota": "pendiente_validacion"}
        }
    }
    if curso_id:
        match_dict["curso_id"] = curso_id
    if modulo_index is not None:
        match_dict["modulos.$elemMatch.estado_validacion_nota"] = "pendiente_validacion"
        match_dict["modulos"] = {
            "$elemMatch": {
                "estado_validacion_nota": "pendiente_validacion",
            }
        }
        # Filtrar también por el índice específico requiere unwind; lo hacemos
        # en Python después para mantener la query simple

    # Filtro de encargado_curso
    if current_user.rol == UserRole.ENCARGADO_CURSO and current_user.cursos_asignados:
        match_dict["curso_id"] = {"$in": current_user.cursos_asignados}

    # Buscar enrollments candidatos
    raw = await Enrollment.find(match_dict).to_list()

    # Si hay filtro por módulo_index, filtrar en Python
    items: List[NotaPendienteItem] = []
    for e in raw:
        for idx, m in enumerate(e.modulos or []):
            if m.estado_validacion_nota != "pendiente_validacion":
                continue
            if modulo_index is not None and idx != modulo_index:
                continue
            item = await _enriquecer_nota_pendiente(e, idx)
            if not item:
                continue
            # filtro de búsqueda por texto
            if estudiante_query:
                q = estudiante_query.lower()
                hay = (
                    q in (item.estudiante_nombre or "").lower()
                    or q in (item.estudiante_registro or "")
                    or q in (item.estudiante_ci or "")
                )
                if not hay:
                    continue
            items.append(item)

    # Ordenar por curso + estudiante para hacerlo predecible
    items.sort(key=lambda x: (x.curso_codigo, x.estudiante_nombre or ""))

    return NotasPendientesResponse(
        total=len(items),
        items=items,
        filtros_aplicados={
            "curso_id": str(curso_id) if curso_id else None,
            "modulo_index": modulo_index,
            "estudiante_query": estudiante_query,
        },
    )


@router.post(
    "/notas/bulk-validar",
    response_model=BulkValidarResponse,
    summary="Aprobar en bulk notas pendientes (CPD/Superadmin)",
)
async def bulk_validar_notas(
    *,
    payload: BulkValidarRequest,
    current_user: User = Depends(require_cpd)
) -> Any:
    """
    F-070: aprueba (valida) varias notas pendientes en una sola llamada.
    Cada item es (enrollment_id, modulo_index). Devuelve un resumen con
    éxitos/fallos por item para que el frontend pueda mostrar cuáles pasaron
    y cuáles no.
    """
    resultados: List[BulkValidarResultado] = []
    exitosos = 0
    fallidos = 0

    for item in payload.items:
        try:
            eid = PydanticObjectId(item.enrollment_id)
            # Validar primero que existe y está pendiente
            e = await Enrollment.get(eid)
            if not e:
                raise ValueError("Inscripción no encontrada")
            if item.modulo_index < 0 or item.modulo_index >= len(e.modulos):
                raise ValueError(f"Índice de módulo {item.modulo_index} fuera de rango")
            mod = e.modulos[item.modulo_index]
            if mod.estado_validacion_nota != "pendiente_validacion":
                raise ValueError(f"El módulo no está en estado 'pendiente_validacion' (actual: {mod.estado_validacion_nota})")

            # Validar (reutiliza la lógica existente)
            updated = await enrollment_service.validar_nota_borrador(
                enrollment_id=eid,
                modulo_index=item.modulo_index,
                evaluador_username=current_user.nombre_funcional or current_user.username,
            )
            resultados.append(BulkValidarResultado(
                enrollment_id=item.enrollment_id,
                modulo_index=item.modulo_index,
                ok=True,
                nota_final=updated.nota_final,
            ))
            exitosos += 1
        except Exception as ex:
            resultados.append(BulkValidarResultado(
                enrollment_id=item.enrollment_id,
                modulo_index=item.modulo_index,
                ok=False,
                error=str(ex),
            ))
            fallidos += 1

    return BulkValidarResponse(
        total=len(payload.items),
        exitosos=exitosos,
        fallidos=fallidos,
        resultados=resultados,
    )


@router.put(
    "/{id}/modulos/{index}/nota",
    response_model=EnrollmentResponse,
    summary="Editar nota validada (CPD/Superadmin)",
)
async def editar_nota_validada(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0),
    payload: EditarNotaRequest,
    current_user: User = Depends(require_cpd)
) -> Any:
    """
    F-070: edita una nota que ya fue validada (estado_validacion_nota='validada'
    o sin_borrador). Solo CPD/Superadmin. Registra quién y cuándo la modificó
    para auditoría.

    Aplica la misma lógica que `actualizar_nota_modulo` (recalcula promedio,
    beca, estado académico Aprobado/Reprobado) y notifica al estudiante.
    """
    try:
        enrollment = await Enrollment.get(id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        if not enrollment.modulos or len(enrollment.modulos) == 0:
            raise HTTPException(status_code=400, detail="Inscripción sin módulos")
        if index >= len(enrollment.modulos):
            raise HTTPException(status_code=400, detail=f"Índice {index} fuera de rango (hay {len(enrollment.modulos)} módulos)")

        modulo = enrollment.modulos[index]
        nota_anterior = modulo.nota
        # Solo permitir editar si la nota ya está validada o el módulo no tiene borrador pendiente
        if modulo.estado_validacion_nota == "pendiente_validacion":
            raise HTTPException(
                status_code=400,
                detail="No se puede editar una nota pendiente de validación. Use el flujo validar/rechazar primero."
            )

        modulo.nota = round(payload.nota, 2)
        modulo.estado_academico = "Aprobado" if payload.nota >= 51 else "Reprobado"
        enrollment.updated_at = utcnow_naive()

        # Recalcular promedio
        notas_evaluadas = [m.nota for m in enrollment.modulos if m.nota is not None]
        if notas_evaluadas:
            promedio = sum(notas_evaluadas) / len(notas_evaluadas)
            enrollment.nota_final = round(promedio, 2)
        else:
            enrollment.nota_final = None

        await enrollment.save()

        # Notificar al estudiante
        try:
            from services.notification_service import create_notification
            nombre_modulo = modulo.nombre if hasattr(modulo, "nombre") else f"Módulo {index + 1}"
            await create_notification(
                destinatario_id=enrollment.estudiante_id,
                tipo_destinatario="student",
                titulo="Nota ajustada por CPD",
                mensaje=(
                    f"Tu nota de '{nombre_modulo}' fue ajustada de {nota_anterior} a {modulo.nota} "
                    f"por {current_user.nombre_funcional or current_user.username}. "
                    + (f"Motivo: {payload.motivo}. " if payload.motivo else "")
                    + f"Tu promedio final es ahora {enrollment.nota_final}."
                ),
                tipo_alerta="info",
                ruta="/app/enrollments",
                referencia_tipo="enrollment",
                referencia_id=enrollment.id,
            )
        except Exception as e:
            print(f"Error notificando edición de nota: {str(e)}")

        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========================================================================

@router.get(
    "/me",
    response_model=List[EnrollmentResponse],
    summary="Ver Mis Inscripciones (Estudiante autenticado)"
)
async def get_my_enrollments(
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    FIX-ERRORES-500: lista las inscripciones del estudiante autenticado.
    Importante: este endpoint debe declararse ANTES de /{id} para que
    no se matchee con id="me" (que rompe PydanticObjectId).

    F-FIX-ENROLLMENTS-ME-JOIN (2026-08-10, Kevin): ahora joinea
    estudiante_nombre, curso_nombre, etc. para que el estudiante vea
    los nombres en su dashboard (no IDs).

    F-2026-08-11-MODULOS-EC: si el estudiante tiene saldo_pendiente > 0 en
    alguna inscripcion, sus notas (nota, nota_borrador) y estado_academico
    se devuelven como null. Solo cuando pague todo (saldo_pendiente == 0)
    podra ver las notas. Regla de la reunion educacion continua UAGRM
    2026-08-11: "estudiante no ve nota hasta pagar".
    """
    enrollments = await Enrollment.find(
        Enrollment.estudiante_id == current_user.id
    ).sort("-created_at").to_list()
    # F-FIX-ENROLLMENTS-ME-JOIN: joinear nombres (1 query batch por
    # coleccion, no N+1).
    enriched = await enrollment_service.enrich_enrollments_batch(enrollments)

    # F-2026-08-11-MODULOS-EC: filtrar notas si hay deuda pendiente.
    # NO mutamos el objeto de la DB, solo el snapshot que se serializa.
    # Si saldo_pendiente > 0: ocultar nota, nota_borrador, estado_academico
    # (forzar a "Cursando") y nota_final del enrollment.
    for enr in enriched:
        saldo = (enr.get("saldo_pendiente") or 0) if isinstance(enr, dict) else 0
        if saldo > 0:
            modulos = enr.get("modulos") if isinstance(enr, dict) else None
            if modulos:
                for m in modulos:
                    if not isinstance(m, dict):
                        continue
                    if m.get("nota") is not None:
                        m["nota"] = None
                    if m.get("nota_borrador") is not None:
                        m["nota_borrador"] = None
                    if m.get("estado_academico") not in (None, "Cursando"):
                        m["estado_academico"] = "Cursando"
            if isinstance(enr, dict) and enr.get("nota_final") is not None:
                enr["nota_final"] = None

    return enriched


@router.get(
    "/me/cursos-resumen",
    summary="F-087-CAL · Mis cursos activos (resumen para dashboard del estudiante)"
)
async def get_my_courses_resumen(
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Devuelve los cursos del estudiante autenticado enriquecidos con:
    - Código, nombre y tipo del programa
    - Fechas de inicio/fin
    - Estado calculado del PROGRAMA (programado | en_ejecucion | cerrado)
    - Estado de la INSCRIPCIÓN (activo, suspendido, etc.)
    - Progreso de módulos (X de Y pagados)
    - Saldo pendiente

    Pensado para alimentar la sección "Mis cursos activos" del dashboard
    del estudiante, agrupado por estado del programa.
    """
    from models.course import Course
    from models.estado_programa import EstadoPrograma

    enrollments = await Enrollment.find(
        Enrollment.estudiante_id == current_user.id
    ).sort("-created_at").to_list()

    # Trae todos los cursos en batch
    curso_ids = list({e.curso_id for e in enrollments if e.curso_id})
    cursos_list = await Course.find({"_id": {"$in": curso_ids}}).to_list() if curso_ids else []
    cursos_map = {c.id: c for c in cursos_list}

    items = []
    for e in enrollments:
        c = cursos_map.get(e.curso_id)
        if not c:
            continue
        estado_programa = c.get_estado_actual()
        modulos_pagados = sum(
            1 for m in (e.modulos or [])
            if (m.estado or "").lower() in ("pagado", "completo")
        )
        items.append({
            "enrollment_id": str(e.id),
            "curso_id": str(c.id),
            "curso_codigo": c.codigo,
            "curso_nombre": c.nombre_programa,
            "curso_tipo": c.tipo_curso.value if hasattr(c.tipo_curso, "value") else str(c.tipo_curso),
            "curso_modalidad": c.modalidad.value if hasattr(c.modalidad, "value") else str(c.modalidad),
            "fecha_inicio": c.fecha_inicio.isoformat() if c.fecha_inicio else None,
            "fecha_fin": c.fecha_fin.isoformat() if c.fecha_fin else None,
            "estado_programa": estado_programa,  # programado | en_ejecucion | cerrado
            "estado_inscripcion": e.estado.value if hasattr(e.estado, "value") else str(e.estado),
            "motivo_suspension": e.motivo_suspension,
            "total_a_pagar": e.total_a_pagar,
            "total_pagado": e.total_pagado,
            "saldo_pendiente": e.saldo_pendiente,
            "modulos_total": len(e.modulos or []),
            "modulos_pagados": modulos_pagados,
            "matricula_pagada": bool(e.matricula_pagada),
            "fecha_inscripcion": e.fecha_inscripcion.isoformat() if e.fecha_inscripcion else None,
        })

    return {
        "items": items,
        "resumen": {
            "total_cursos": len(items),
            "en_ejecucion": sum(1 for it in items if it["estado_programa"] == EstadoPrograma.EN_EJECUCION.value),
            "programado": sum(1 for it in items if it["estado_programa"] == EstadoPrograma.PROGRAMADO.value),
            "cerrado": sum(1 for it in items if it["estado_programa"] == EstadoPrograma.CERRADO.value),
            "saldo_pendiente_total": sum(it["saldo_pendiente"] or 0 for it in items),
        }
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
        # BUG (2026-07-09, reportado por el usuario): antes solo se
        # recalculaba si venía `descuento_personalizado`, ignorando
        # `descuento_id` por completo -- asignar una beca real (Discount)
        # desde el formulario nunca disparaba el recálculo.
        if enrollment_in.descuento_personalizado is not None or enrollment_in.descuento_id is not None:
            enrollment = await enrollment_service.update_enrollment_descuento(
                enrollment_id=id,
                descuento_personalizado=enrollment_in.descuento_personalizado,
                admin_username=current_user.nombre_visible,  # ISSUE-R-PERFIL-GENERICO
                descuento_id=enrollment_in.descuento_id
            )
        
        if enrollment_in.estado is not None:
            enrollment = await enrollment_service.cambiar_estado_enrollment(
                enrollment_id=id,
                nuevo_estado=enrollment_in.estado,
                admin_username=current_user.nombre_visible  # ISSUE-R-PERFIL-GENERICO
            )
        
        # F-FIX-EXCLUIR-POR-COBRAR (2026-08-16): este endpoint procesa los
        # campos UNO POR UNO (no hace un setattr generico), asi que sin este
        # bloque el flag se ignoraba aunque el schema lo aceptara.
        if enrollment_in.excluir_por_cobrar is not None:
            enrollment = await enrollment_service.get_enrollment(id)
            if not enrollment:
                raise HTTPException(status_code=404, detail="Inscripcion no encontrada")
            enrollment.excluir_por_cobrar = enrollment_in.excluir_por_cobrar
            await enrollment.save()

        if enrollment_in.descuento_personalizado is None and enrollment_in.descuento_id is None and enrollment_in.estado is None and enrollment_in.excluir_por_cobrar is None:
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


# ========================================================================
# F-COBRANZA-035 (2026-07-22): desglose inscritos/activos/pasivos
# ========================================================================
# Pedido Lic. Sandra Zabala (vía Telegram 2026-07-22 10:34):
# "En esta sección si se puede visualizar los estudiantes que están en
# modo pasivo, es decir los congelados, para que tengamos la diferencia
# del total de inscritos inicialmente, cuantos son los activo y cuantos
# los pasivos."
#
# Devuelve un resumen agregado que la UI puede usar para renderizar
# tarjetas. El total incluye TODOS los estados MENOS cancelados (porque
# cancelados = nunca inscritos realmente). Activos = PENDIENTE_PAGO +
# ACTIVO. Pasivos = SUSPENDIDO (con motivo_suspension en {pasivo,
# congelado, abandono}). Completados = COMPLETADO.
#
# F-083 (2026-07-28): se agrega RETIRADO como categoría SEPARADA de
# pasivos. Pedido de Lic. Sorich: "retirados ya no vuelven, no son
# pasivos; pasivo tiene la opción de volver luego, y retirados ya no
# vuelven". Los retirados SÍ cuentan en total_inicial (cursaron algo)
# pero se muestran aparte de "pasivos" en la UI.
@router.get(
    "/stats/resumen",
    summary="Resumen de inscritos: total, activos, pasivos, completados, retirados (F-035 + F-083)",
)
async def get_enrollments_resumen(
    *,
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Curso ID"),
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    F-COBRANZA-035 + F-083: devuelve el conteo de inscripciones agrupadas
    por categoría visual, filtrable opcionalmente por curso. Roles:
    cualquier staff autenticado. Estudiantes NO tienen acceso.
    """
    from models.enums import EstadoInscripcion

    if isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Los estudiantes no tienen acceso al resumen de inscritos."
        )

    # Filtro base (para encargado_curso si aplica)
    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    # Si el caller pasó curso_id y NO está en sus permitidos, rechazar
    if curso_id and cursos_permitidos and curso_id not in cursos_permitidos:
        raise HTTPException(
            status_code=403,
            detail="No tienes asignado ese curso."
        )

    # Si no pasó curso_id y el rol tiene cursos asignados, filtrar
    if not curso_id and cursos_permitidos:
        filtro_curso = {"curso_id": {"$in": cursos_permitidos}}
    elif curso_id:
        filtro_curso = {"curso_id": curso_id}
    else:
        filtro_curso = {}

    # Aggregate: una sola query para todas las categorías
    pipeline = [
        {"$match": filtro_curso},
        {"$group": {
            "_id": {
                "estado": "$estado",
                "motivo": "$motivo_suspension",
            },
            "count": {"$sum": 1}
        }}
    ]
    raw = await Enrollment.aggregate(pipeline).to_list()

    # Inicializar contadores
    total_inicial = 0  # TODOS los inscritos, MENOS cancelados
    activos = 0
    pasivos_congelado = 0
    pasivos_pasivo = 0
    pasivos_abandono = 0
    completados_legacy = 0  # F-DASHBOARD-R10: ya no se usa para "completados" del UI
    cancelados = 0
    pendientes_pago = 0
    retirados = 0  # F-083

    for r in raw:
        estado = r["_id"].get("estado")
        motivo = r["_id"].get("motivo")
        count = r.get("count", 0)

        if estado == "cancelado":
            cancelados += count
            continue  # NO cuentan en total_inicial

        total_inicial += count

        if estado == "activo":
            activos += count
        elif estado == "pendiente_pago":
            pendientes_pago += count
            activos += count  # pendiente_pago se considera activo (aún no paga pero sigue en el programa)
        elif estado == "suspendido":
            if motivo == "congelado":
                pasivos_congelado += count
            elif motivo == "abandono":
                pasivos_abandono += count
            elif motivo == "pasivo":
                pasivos_pasivo += count
            else:
                # motivo None o desconocido -> cuenta como pasivo genérico
                pasivos_pasivo += count
        elif estado == "completado":
            # F-DASHBOARD-R10 (2026-08-06, Kevin): NO contar como "completado"
            # del UI. R10 explicito: "completado = módulo académico cerrado
            # (nota + pago), NO programa completo". El estado=completado del
            # enrollment se setea al pagar TODO, no al terminar académicamente.
            # Por eso se calcula aparte abajo.
            completados_legacy += count
        elif estado == "retirado":  # F-083
            retirados += count

    # F-DASHBOARD-R10: contar "completados" reales = TODOS los modulos
    # con estado_academico='Aprobado' (nota subida Y validada). NO basarse
    # en enrollment.estado='completado' porque eso se setea al pagar todo,
    # no al terminar el programa académicamente.
    # Caso real (2026-08-06, DIPL-IA-2026): Andrea Gutierrez Ruiz tiene
    # enrollment.estado='completado' pero solo 1 de 5 modulos aprobados
    # (van por el 2do modulo). Esto inflaba el conteo.
    pipeline_completados = [
        {"$match": {**filtro_curso, "estado": {"$nin": ["cancelado", "retirado"]}}},
        {"$project": {
            "modulos_aprobados": {
                "$size": {
                    "$filter": {
                        "input": {"$ifNull": ["$modulos", []]},
                        "as": "m",
                        "cond": {"$eq": ["$$m.estado_academico", "Aprobado"]}
                    }
                }
            },
            "total_modulos": {
                "$size": {"$ifNull": ["$modulos", []]}
            }
        }},
        {"$match": {
            "$expr": {
                "$and": [
                    {"$gt": ["$total_modulos", 0]},
                    {"$eq": ["$modulos_aprobados", "$total_modulos"]}
                ]
            }
        }},
        {"$count": "total"}
    ]
    completados_result = await Enrollment.aggregate(pipeline_completados).to_list()
    completados = completados_result[0]["total"] if completados_result else 0

    total_pasivos = pasivos_congelado + pasivos_pasivo + pasivos_abandono

    return {
        "total_inicial": total_inicial,  # inscritos totales (excluye cancelados)
        "activos": activos,  # activo + pendiente_pago
        "pendientes_pago": pendientes_pago,
        "pasivos": {
            "total": total_pasivos,
            "congelado": pasivos_congelado,
            "pasivo": pasivos_pasivo,
            "abandono": pasivos_abandono,
        },
        "completados": completados,  # F-DASHBOARD-R10: TODOS los modulos aprobados
        "completados_legacy": completados_legacy,  # estado enrollment (referencia)
        "retirados": retirados,  # F-083: separado de pasivos
        "cancelados": cancelados,  # NO cuentan como inscritos
        "curso_id": str(curso_id) if curso_id else None,
    }


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
            
        # ISSUE-R-PERFIL-GENERICO: nombre_visible en vez de username (CPD/Docente
        # normalmente no tienen nombre_funcional, así que cae al mismo username).
        username = current_user.nombre_visible if hasattr(current_user, 'nombre_visible') else "docente_autorizado"

        if current_user.rol == UserRole.DOCENTE:
            updated_enrollment = await enrollment_service.subir_nota_borrador(
                enrollment_id=id, modulo_index=index, nota_borrador=nota_update.nota
            )

            # NOTIFICACIÓN a CPD/Admin/Superadmin: el docente subió un borrador
            # que requiere validación. Sin esto, CPD nunca se enteraba.
            try:
                from services.notification_service import create_notification
                from beanie.operators import Or as _Or

                nombre_modulo = (
                    updated_enrollment.modulos[index].nombre
                    if index < len(updated_enrollment.modulos)
                    else f"Módulo {index + 1}"
                )

                revisores = await User.find(
                    User.activo == True,
                    _Or(
                        User.rol == UserRole.CPD,
                        User.rol == UserRole.ADMIN,
                        User.rol == UserRole.SUPERADMIN
                    )
                ).to_list()

                for revisor in revisores:
                    await create_notification(
                        destinatario_id=revisor.id,
                        tipo_destinatario="user",
                        titulo="Nota Borrador Pendiente",
                        mensaje=f"El docente {username} propuso una nota de {nota_update.nota} para '{nombre_modulo}'. Requiere tu validación.",
                        tipo_alerta="warning",
                        ruta="/app/enrollments",
                        referencia_tipo="enrollment",
                        referencia_id=id
                    )
            except Exception as e:
                print(f"Error notificando borrador de nota a CPD: {str(e)}")

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
        updated = await enrollment_service.validar_nota_borrador(id, index, current_user.nombre_visible)

        # NOTIFICACIÓN al docente asignado: su borrador fue aprobado/oficializado.
        try:
            from services.notification_service import create_notification
            from models.course import Course

            nombre_modulo = (
                updated.modulos[index].nombre
                if index < len(updated.modulos)
                else f"Módulo {index + 1}"
            )

            course = await Course.get(updated.curso_id)
            if course and index < len(course.modulos) and course.modulos[index].docente_id:
                await create_notification(
                    destinatario_id=course.modulos[index].docente_id,
                    tipo_destinatario="user",
                    titulo="Nota Oficializada",
                    mensaje=f"Tu nota propuesta para '{nombre_modulo}' fue validada y oficializada por CPD ({current_user.nombre_visible}).",
                    tipo_alerta="success",
                    ruta="/app/dashboard",
                    referencia_tipo="enrollment",
                    referencia_id=id
                )
        except Exception as e:
            print(f"Error notificando validación de borrador al docente: {str(e)}")

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
        # Cargar enrollment ANTES del rechazo para obtener el nombre del módulo
        enrollment = await Enrollment.get(id)
        nombre_modulo = (
            enrollment.modulos[index].nombre
            if enrollment and index < len(enrollment.modulos)
            else f"Módulo {index + 1}"
        )

        updated = await enrollment_service.rechazar_nota_borrador(id, index)

        # NOTIFICACIÓN al docente asignado: su borrador fue rechazado.
        # Sin esto, el docente no se enteraba y creía que su nota seguía pendiente.
        try:
            from services.notification_service import create_notification
            from models.course import Course

            course = await Course.get(updated.curso_id)
            if course and index < len(course.modulos) and course.modulos[index].docente_id:
                await create_notification(
                    destinatario_id=course.modulos[index].docente_id,
                    tipo_destinatario="user",
                    titulo="Borrador de Nota Rechazado",
                    mensaje=f"CPD ({current_user.nombre_visible}) rechazó tu nota propuesta para '{nombre_modulo}'. Por favor, revisa y envía una nueva calificación.",
                    tipo_alerta="error",
                    ruta="/app/dashboard",
                    referencia_tipo="enrollment",
                    referencia_id=id
                )
        except Exception as e:
            print(f"Error notificando rechazo de borrador al docente: {str(e)}")

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
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")

    # Autorización: el estudiante dueño, o el personal habilitado. CPD/Admin/
    # Superadmin sin restricción; Encargado de Curso/Coordinador pueden subir
    # documentos por el estudiante (el Encargado solo en sus programas asignados).
    # Cobranza/Docente/MAE NO suben requisitos.
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(403, "No es tu inscripción")
    else:
        roles_permitidos = {
            UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN,
            UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR
        }
        if current_user.rol not in roles_permitidos:
            raise HTTPException(403, "No tienes permiso para subir documentos")
        if current_user.rol == UserRole.ENCARGADO_CURSO and enrollment.curso_id not in current_user.cursos_asignados:
            raise HTTPException(403, "No tienes asignado el programa de esta inscripción")

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

        # ISSUE-Q-DOCUMENTOS-KYC (2026-07-09): al subir el estudiante, se
        # notifica a quienes pueden aprobarlo (CPD/Admin/Superadmin siempre, +
        # el Encargado de Curso asignado a ese curso) para que lo revisen. No
        # bloqueante: si la notificación falla, la subida ya quedó registrada.
        try:
            from services.notification_service import create_notification
            from beanie.operators import Or as _Or, In as _In

            nombre_doc = enrollment.requisitos[index].descripcion
            if isinstance(current_user, Student):
                nombre_est = current_user.nombre or current_user.registro
            else:
                _est = await Student.get(enrollment.estudiante_id)
                nombre_est = (_est.nombre or _est.registro) if _est else "Un estudiante"

            revisores = await User.find(
                User.activo == True,
                _Or(
                    User.rol == UserRole.CPD,
                    User.rol == UserRole.ADMIN,
                    User.rol == UserRole.SUPERADMIN,
                    _In(User.cursos_asignados, [enrollment.curso_id])
                )
            ).to_list()

            for revisor in revisores:
                # El Encargado de Curso solo si el curso está entre sus asignados
                if revisor.rol == UserRole.ENCARGADO_CURSO and enrollment.curso_id not in revisor.cursos_asignados:
                    continue
                await create_notification(
                    destinatario_id=revisor.id,
                    tipo_destinatario="user",
                    titulo="Documento por revisar",
                    mensaje=f"{nombre_est} subió el documento '{nombre_doc}' y requiere tu revisión.",
                    tipo_alerta="info",
                    ruta="/app/enrollments",
                    referencia_tipo="enrollment",
                    referencia_id=enrollment.id
                )
        except Exception as e:
            print(f"Error notificando subida de documento a revisores: {str(e)}")

        return enrollment.requisitos[index]
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@router.put("/{id}/requisitos/{index}/aprobar", response_model=RequisitoResponse)
async def aprobar_requisito(
    *, id: PydanticObjectId, index: int = Path(..., ge=0),
    current_user: User = Depends(require_encargado_curso)
    # ISSUE-Q-DOCUMENTOS-KYC (2026-07-09): antes solo CPD podía aprobar/rechazar
    # documentos. Ampliado a Encargado de Curso/Coordinador (restringido a sus
    # cursos_asignados, ver validación abajo) para no sobrecargar solo a CPD --
    # CPD/Admin/Superadmin conservan acceso total sin restricción de curso.
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")

    if current_user.rol == UserRole.ENCARGADO_CURSO and enrollment.curso_id not in current_user.cursos_asignados:
        raise HTTPException(403, "No tienes asignado el curso de esta inscripción")

    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice fuera de rango")
    
    requisito = enrollment.requisitos[index]
    if not requisito.url:
        raise HTTPException(400, "Sin documento")
    if requisito.estado not in [EstadoRequisito.EN_PROCESO, EstadoRequisito.RECHAZADO]:
        raise HTTPException(400, "Estado incorrecto")
    
    enrollment.requisitos[index].aprobar(current_user.nombre_visible)  # ISSUE-R-PERFIL-GENERICO
    await enrollment.save()

    # ISSUE-Q-DOCUMENTOS-KYC: notificar al estudiante que su documento fue aprobado.
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Documento aprobado",
            mensaje=f"Tu documento '{enrollment.requisitos[index].descripcion}' fue aprobado.",
            tipo_alerta="success",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando aprobación de documento al estudiante: {str(e)}")

    return enrollment.requisitos[index]


@router.put("/{id}/requisitos/{index}/rechazar", response_model=RequisitoResponse)
async def rechazar_requisito(
    *, id: PydanticObjectId, index: int = Path(..., ge=0), rechazo: RequisitoRechazarRequest,
    current_user: User = Depends(require_encargado_curso)
    # ISSUE-Q-DOCUMENTOS-KYC (2026-07-09): mismo criterio que aprobar_requisito arriba.
) -> Any:
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Enrollment no encontrado")

    if current_user.rol == UserRole.ENCARGADO_CURSO and enrollment.curso_id not in current_user.cursos_asignados:
        raise HTTPException(403, "No tienes asignado el curso de esta inscripción")

    if index >= len(enrollment.requisitos):
        raise HTTPException(400, f"Índice fuera de rango")
    
    requisito = enrollment.requisitos[index]
    if not requisito.url:
        raise HTTPException(400, "Sin documento")
    if requisito.estado != EstadoRequisito.EN_PROCESO:
        raise HTTPException(400, "Estado incorrecto")
    
    enrollment.requisitos[index].rechazar(current_user.nombre_visible, rechazo.motivo)  # ISSUE-R-PERFIL-GENERICO
    await enrollment.save()

    # ISSUE-Q-DOCUMENTOS-KYC: notificar al estudiante que su documento fue rechazado, con el motivo.
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Documento rechazado",
            mensaje=f"Tu documento '{enrollment.requisitos[index].descripcion}' fue rechazado. Motivo: {rechazo.motivo}. Vuelve a subirlo corregido.",
            tipo_alerta="error",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando rechazo de documento al estudiante: {str(e)}")

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
        enrollment.updated_at = utcnow_naive()
        await enrollment.save()
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")


@router.post(
    "/{id}/formulario-inscripcion",
    response_model=EnrollmentResponse,
    summary="Subir Formulario de Inscripción lleno"
)
async def subir_formulario_inscripcion(
    *,
    id: PydanticObjectId,
    file: UploadFile = File(...),
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Sube (o reemplaza) el formulario de inscripción oficial lleno/firmado del
    estudiante para esta inscripción. El estudiante puede subir el suyo; el
    personal (CPD/Admin/Superadmin) también puede subirlo por él. Acepta PDF o
    imagen (foto del formulario firmado). No bloqueante.
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(404, "Inscripción no encontrada")

    # El estudiante solo puede subir el formulario de su propia inscripción.
    if isinstance(current_user, Student) and enrollment.estudiante_id != current_user.id:
        raise HTTPException(403, "No es tu inscripción")

    try:
        folder = f"enrollments/{id}/formulario_inscripcion"
        public_id = "formulario"

        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        if file.content_type in image_types:
            url = await upload_image(file, folder, public_id)
        elif file.content_type == "application/pdf":
            url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(400, f"Formato no permitido: {file.content_type}. Sube el formulario como PDF o imagen.")

        enrollment.formulario_inscripcion_url = url
        enrollment.updated_at = utcnow_naive()
        await enrollment.save()

        # Notificar a revisores (CPD, Admin, Superadmin y Encargado)
        try:
            from services.notification_service import create_notification
            from beanie.operators import Or as _Or

            if isinstance(current_user, Student):
                nombre_est = current_user.nombre or current_user.registro
            else:
                _est = await Student.get(enrollment.estudiante_id)
                nombre_est = (_est.nombre or _est.registro) if _est else "Un estudiante"

            revisores = await User.find(
                User.activo == True,
                _Or(
                    User.rol == UserRole.CPD,
                    User.rol == UserRole.ADMIN,
                    User.rol == UserRole.SUPERADMIN,
                    User.rol == UserRole.ENCARGADO_CURSO
                )
            ).to_list()

            for revisor in revisores:
                if revisor.rol == UserRole.ENCARGADO_CURSO and enrollment.curso_id not in revisor.cursos_asignados:
                    continue
                await create_notification(
                    destinatario_id=revisor.id,
                    tipo_destinatario="user",
                    titulo="Formulario de Inscripción por revisar",
                    mensaje=f"{nombre_est} subió su Formulario de Inscripción y requiere tu revisión.",
                    tipo_alerta="info",
                    ruta="/app/enrollments",
                    referencia_tipo="enrollment",
                    referencia_id=enrollment.id
                )
        except Exception as e:
            print(f"Error notificando formulario de inscripcion a revisores: {str(e)}")

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
            enrollment_id=id, otorgado_por=current_user.nombre_visible  # ISSUE-R-PERFIL-GENERICO
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
    tasa_pagada: bool = Query(
        False,
        description=(
            "Si la tasa de congelamiento ya fue cobrada. Por defecto False: "
            "el congelamiento NO asume que el estudiante ya pagó (AUDITORÍA #6, "
            "antes se marcaba tasa_congelamiento_pagada=True sin ningún Payment "
            "real asociado). Cobranza debe registrar el cobro real y CPD puede "
            "pasar tasa_pagada=true solo si ese cobro ya ocurrió."
        )
    ),
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
            enrollment_id=id, registrado_por=current_user.nombre_visible, tasa_pagada=tasa_pagada  # ISSUE-R-PERFIL-GENERICO
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
            enrollment_id=id, admin_username=current_user.nombre_visible  # ISSUE-R-PERFIL-GENERICO
        )
        return await enrollment_service.enrich_enrollment_dates(enrollment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========================================================================
# F-083 (2026-07-28): RETIRO VOLUNTARIO DE INSCRIPCIÓN
# ========================================================================
# Pedido Lic. Sorich (chat MS Digital Academy, 2026-07-27 19:40):
# "Vería la opción de colocar retirados, porque ya no vuelven, no son
# pasivos; pasivo tiene la opción de volver luego, y retirados ya no
# vuelven. Analízalo."
#
# Distinto de SUSPENDIDO+abandono (que es automático por inactividad y
# genera multa de reincorporación). RETIRADO es VOLUNTARIO, DEFINITIVO,
# no genera multa.
#
# Lo que ya pagó el estudiante SÍ cuenta como ingreso.
# Lo que falta NO se cobra (no suma a "Por Cobrar").
from pydantic import BaseModel as _PydanticBaseModel, Field as _PydanticField

class RetirarEnrollmentRequest(_PydanticBaseModel):
    motivo_retiro: str = _PydanticField(
        ...,
        min_length=5,
        max_length=500,
        description="Motivo del retiro (obligatorio, mínimo 5 caracteres). Ej: 'cambio de ciudad', 'problemas económicos'."
    )
    notificar_estudiante: bool = _PydanticField(
        default=True,
        description="Si True (default), envía notification in-app al estudiante confirmando el retiro."
    )


@router.post(
    "/{id}/retirar",
    response_model=EnrollmentResponse,
    summary="F-083: Retirar Inscripción (abandono definitivo, no vuelve)"
)
async def retirar_enrollment_endpoint(
    *,
    id: PydanticObjectId,
    body: RetirarEnrollmentRequest,
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN
) -> Any:
    """
    F-083 (2026-07-28): marca una inscripción como RETIRADO (abandono
    DEFINITIVO, no vuelve). Distinto de SUSPENDIDO+abandono.

    Reglas de negocio:
    - Solo CPD/ADMIN/SUPERADMIN pueden retirar (no cobranza, no docente).
    - El retiro es VOLUNTARIO y DEFINITIVO. No reversible.
    - Si la inscripción estaba SUSPENDIDA (congelado/pasivo/abandono
      automático), se limpia motivo_suspension y campos relacionados.
    - El estudiante recibe notification in-app confirmando.
    - Lo que ya pagó SÍ cuenta como ingreso. Lo que falta NO se cobra.

    Distinto de abandono automático:
    - Abandono automático: por inactividad, genera multa de
      reincorporación al volver.
    - Retirado: voluntario, definitivo, NO genera multa.
    """
    try:
        enrollment = await enrollment_service.retirar_inscripcion(
            enrollment_id=id,
            motivo_retiro=body.motivo_retiro,
            retirado_por=current_user.username,
            notificar_estudiante=body.notificar_estudiante
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


# ========================================================================
# ENDPOINTS: INICIAR MÓDULO (F-CUENTAS-POR-COBRAR 2026-07-29)
# ========================================================================
# Habilitan manualmente un módulo como "en curso" para que cuente en la
# CxC real (a la fecha). El módulo 1 de los enrollments activos ya quedó
# backfilleado por scripts/backfill_modulo_iniciado.py; los módulos 2..N
# los irá iniciando el encargado del programa con un click.
#
# RBAC (Kevin: "Solo Admin + Superadmin + Encargado del Curso del programa
# específico"):
# - superadmin / admin: cualquier módulo de cualquier programa.
# - encargado_curso: solo módulos de cursos en cursos_asignados.
# - Cualquier otro rol (cobranza, cpd, mae, coordinador, docente): 403.

async def _puede_iniciar_modulo(current_user: User, enrollment: Enrollment) -> bool:
    """
    Verifica que el usuario puede iniciar módulos del programa del enrollment.
    Devuelve True si:
    - rol in {SUPERADMIN, ADMIN}, o
    - rol = ENCARGADO_CURSO y el curso está en cursos_asignados.
    """
    from models.enums import UserRole
    if current_user.rol in {UserRole.SUPERADMIN, UserRole.ADMIN}:
        return True
    if current_user.rol == UserRole.ENCARGADO_CURSO:
        cursos_asignados = current_user.cursos_asignados or []
        return str(enrollment.curso_id) in [str(c) for c in cursos_asignados]
    return False


@router.post(
    "/{id}/modulos/{index}/iniciar",
    response_model=EnrollmentResponse,
    summary="[Staff] Marcar módulo N como 'en curso' (habilita CxC real)",
)
async def iniciar_modulo_endpoint(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del módulo (0, 1, 2...)"),
    force: bool = Query(False, description="Solo superadmin: saltar la validación de encadenamiento"),
    current_user: User = Depends(require_staff),
) -> Any:
    """
    F-CUENTAS-POR-COBRAR: el encargado del programa inicia manualmente un
    módulo. A partir de este momento, el saldo del módulo entra en la
    "CxC a la fecha" del reporte financiero.

    Permisos: Admin, Superadmin, o Encargado del Curso del programa específico.
    Idempotente: si el módulo ya estaba iniciado, no-op (devuelve 200 OK).

    F-MODAL-GESTION-MODULOS (2026-08-03, Kevin): el módulo N+1 solo se puede
    iniciar si el N está finalizado. Solo superadmin puede saltarse con `?force=true`.
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")

    if not await _puede_iniciar_modulo(current_user, enrollment):
        raise HTTPException(
            status_code=403,
            detail=(
                "Solo Admin, Superadmin, o el Encargado del Curso de este "
                "programa específico pueden iniciar módulos."
            ),
        )

    # F-MODAL-GESTION-MODULOS: el flag force solo lo puede usar superadmin
    from models.enums import UserRole
    if force and current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo SUPERADMIN puede usar force=true para iniciar un módulo fuera de orden.",
        )

    from services import cuentas_por_cobrar_service
    enrollment = await cuentas_por_cobrar_service.iniciar_modulo(
        enrollment=enrollment,
        modulo_index=index,
        current_user=current_user,
        force=force,
    )
    return await enrollment_service.enrich_enrollment_dates(enrollment)


@router.post(
    "/{id}/modulos/{index}/deshacer-inicio",
    response_model=EnrollmentResponse,
    summary="[Staff] Revertir módulo N a 'no iniciado' (corrige CxC real)",
)
async def deshacer_inicio_modulo_endpoint(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del módulo (0, 1, 2...)"),
    current_user: User = Depends(require_staff),
) -> Any:
    """
    F-CUENTAS-POR-COBRAR: revierte el inicio de un módulo (caso de error
    humano). Útil si Sandra/Rocío se equivocó de módulo o de programa.

    Permisos: los mismos que iniciar_modulo.
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")

    if not await _puede_iniciar_modulo(current_user, enrollment):
        raise HTTPException(
            status_code=403,
            detail=(
                "Solo Admin, Superadmin, o el Encargado del Curso de este "
                "programa específico pueden revertir el inicio de un módulo."
            ),
        )

    from services import cuentas_por_cobrar_service
    enrollment = await cuentas_por_cobrar_service.deshacer_inicio_modulo(
        enrollment=enrollment,
        modulo_index=index,
        current_user=current_user,
    )
    return await enrollment_service.enrich_enrollment_dates(enrollment)


# ========================================================================
# ENDPOINTS: FINALIZAR MÓDULO (F-MODULOS-MODAL 2026-07-31)
# ========================================================================
# Cierra un módulo iniciado. El kardex del estudiante usa el ciclo:
#   Pendiente → En curso → Finalizado
# Cuando se finaliza, el módulo ya no se considera "activo" para
# recaudación -- el siguiente paso natural es registrar la nota.
# También expone deshacer_finalizacion por si fue un error humano.

@router.post(
    "/{id}/modulos/{index}/finalizar",
    response_model=EnrollmentResponse,
    summary="[Staff] Cerrar/finalizar módulo N (ciclo completo)",
)
async def finalizar_modulo_endpoint(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del módulo (0, 1, 2...)"),
    asistencia_porcentaje: Optional[float] = Body(
        None, ge=0, le=100,
        description=(
            "F-2026-08-11-MODULOS-EC: porcentaje de asistencia del estudiante "
            "al módulo (0-100). Opcional. Si < 80, el sistema fuerza "
            "estado_academico='Reprobado' (regla de aprobación mínima por "
            "asistencia, educación continua UAGRM 2026-08-11)."
        ),
    ),
    current_user: User = Depends(require_staff),
) -> Any:
    """
    F-MODULOS-MODAL (2026-07-31): marca un módulo como finalizado/cerrado.
    Requisito: el módulo debe estar iniciado (iniciado_en != null).
    Idempotente: si ya estaba finalizado, no-op.

    F-2026-08-11-MODULOS-EC: si se pasa asistencia_porcentaje, se persiste en
    el modulo. Si asistencia < 80%, se fuerza estado_academico='Reprobado'
    independientemente de la nota.
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")

    if not await _puede_iniciar_modulo(current_user, enrollment):
        raise HTTPException(
            status_code=403,
            detail=(
                "Solo Admin, Superadmin, o el Encargado del Curso de este "
                "programa específico pueden finalizar módulos."
            ),
        )

    if index < 0 or index >= len(enrollment.modulos):
        raise HTTPException(
            status_code=400,
            detail=f"Índice de módulo {index} inválido",
        )

    modulo = enrollment.modulos[index]
    if modulo.iniciado_en is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "No se puede finalizar un módulo que no está iniciado. "
                "Primero márcalo como 'en curso'."
            ),
        )

    if modulo.finalizado_en is None:
        modulo.finalizado_en = utcnow_naive()
    # F-2026-08-11-MODULOS-EC: persistir asistencia_porcentaje y aplicar
    # regla del 80% (forzar Reprobado si < 80). Se aplica aunque el módulo
    # ya estuviera finalizado, para soportar correcciones.
    if asistencia_porcentaje is not None:
        modulo.asistencia_porcentaje = asistencia_porcentaje
        if asistencia_porcentaje < 80:
            modulo.estado_academico = "Reprobado"

    await enrollment.save()

    return await enrollment_service.enrich_enrollment_dates(enrollment)


@router.post(
    "/{id}/modulos/{index}/deshacer-finalizacion",
    response_model=EnrollmentResponse,
    summary="[Staff] Revertir cierre de módulo N (caso de error)",
)
async def deshacer_finalizacion_modulo_endpoint(
    *,
    id: PydanticObjectId,
    index: int = Path(..., ge=0, description="Índice del módulo (0, 1, 2...)"),
    current_user: User = Depends(require_staff),
) -> Any:
    """
    F-MODULOS-MODAL: revierte la finalización de un módulo. Útil si fue un
    error humano (ej: cerró el módulo equivocado).
    """
    enrollment = await Enrollment.get(id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")

    if not await _puede_iniciar_modulo(current_user, enrollment):
        raise HTTPException(
            status_code=403,
            detail=(
                "Solo Admin, Superadmin, o el Encargado del Curso de este "
                "programa específico pueden revertir la finalización."
            ),
        )

    if index < 0 or index >= len(enrollment.modulos):
        raise HTTPException(
            status_code=400,
            detail=f"Índice de módulo {index} inválido",
        )

    modulo = enrollment.modulos[index]
    modulo.finalizado_en = None
    await enrollment.save()

    return await enrollment_service.enrich_enrollment_dates(enrollment)
