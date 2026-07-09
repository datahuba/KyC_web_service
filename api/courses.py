from typing import List, Any, Union
import asyncio
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from beanie.operators import In
from models.course import Course
from models.user import User
from models.student import Student
from models.enrollment import Enrollment
from models.enums import UserRole
from schemas.course import CourseCreate, CourseResponse, CourseUpdate, CourseEnrolledStudent
from services import course_service
from beanie import PydanticObjectId

# Nuevas dependencias de seguridad del ISSUE L
from api.dependencies import require_superadmin, require_cpd, require_staff, get_current_user, require_encargado_curso

router = APIRouter()


class ComunicadoRequest(BaseModel):
    """Comunicado por correo del Encargado de Programa/CPD a los estudiantes de un programa."""
    asunto: str = Field(..., min_length=1, max_length=200)
    mensaje: str = Field(..., min_length=1, max_length=5000)


@router.post("/{id}/comunicado", summary="Enviar comunicado por correo a los estudiantes del programa")
async def enviar_comunicado_programa(
    *,
    id: PydanticObjectId,
    payload: ComunicadoRequest,
    current_user: User = Depends(require_encargado_curso)  # ENCARGADO_CURSO/COORDINADOR/CPD/ADMIN/SUPERADMIN
) -> Any:
    """
    Envía un comunicado (asunto + mensaje) a TODOS los estudiantes inscritos en
    el programa: notificación in-app (siempre) + correo real si tienen email y
    SMTP está configurado. El Encargado de Curso solo puede enviarlo a sus
    programas asignados. Envíos concurrentes (semáforo) para no hacer timeout
    con muchos estudiantes.
    """
    course = await Course.get(id)
    if not course:
        raise HTTPException(status_code=404, detail="Programa no encontrado")

    if current_user.rol == UserRole.ENCARGADO_CURSO and id not in current_user.cursos_asignados:
        raise HTTPException(status_code=403, detail="No tienes asignado este programa")

    enrollments = await Enrollment.find(Enrollment.curso_id == id).to_list()
    student_ids = list({e.estudiante_id for e in enrollments})
    if not student_ids:
        return {"success": True, "total_estudiantes": 0, "correos_enviados": 0,
                "detail": "El programa no tiene estudiantes inscritos."}

    students = await Student.find(In(Student.id, student_ids)).to_list()

    from services.notification_service import create_notification
    from core.email_utils import send_email, build_comunicado_email
    from core.config import settings

    portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/dashboard"
    nombre_programa = course.nombre_programa
    asunto = payload.asunto.strip()
    mensaje = payload.mensaje.strip()

    sem = asyncio.Semaphore(8)
    correos_enviados = 0

    async def _procesar(st: Student):
        nonlocal correos_enviados
        async with sem:
            try:
                await create_notification(
                    destinatario_id=st.id,
                    tipo_destinatario="student",
                    titulo=asunto,
                    mensaje=mensaje,
                    tipo_alerta="info",
                    ruta="/app/dashboard"
                )
            except Exception as e:
                print(f"Error notificando comunicado a {st.id}: {str(e)}")
            if st.email:
                try:
                    html = build_comunicado_email(
                        nombre=st.nombre or st.registro,
                        asunto=asunto,
                        mensaje=mensaje,
                        programa=nombre_programa,
                        portal_link=portal_link
                    )
                    ok = await send_email(st.email, f"{asunto} · {nombre_programa}", html)
                    if ok:
                        correos_enviados += 1
                except Exception as e:
                    print(f"Error enviando comunicado por correo a {st.email}: {str(e)}")

    await asyncio.gather(*[_procesar(st) for st in students])

    return {
        "success": True,
        "total_estudiantes": len(students),
        "correos_enviados": correos_enviados,
        "detail": f"Comunicado enviado a {len(students)} estudiante(s)."
    }

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from models.enums import TipoCurso, Modalidad
from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[CourseResponse],
    summary="Listar Cursos"
)
async def read_courses(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por nombre o código"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    tipo_curso: Optional[TipoCurso] = Query(None, description="Filtrar por tipo de curso"),
    modalidad: Optional[Modalidad] = Query(None, description="Filtrar por modalidad"),
    current_user: Union[User, Student] = Depends(get_current_user) # Abierto para todos
) -> Any:
    """Listar cursos con paginación y filtros"""
    courses, total_count = await course_service.get_courses(
        page=page,
        per_page=per_page,
        q=q,
        activo=activo,
        tipo_curso=tipo_curso,
        modalidad=modalidad
    )
    
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    
    return {
        "data": courses,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1)
        )
    }

@router.post(
    "/",
    response_model=CourseResponse,
    status_code=201,
    summary="Crear Curso"
)
async def create_course(
    *,
    course_in: CourseCreate,
    current_user: User = Depends(require_cpd) # <-- CPD CREA LOS PROGRAMAS
) -> Any:
    """Crear nuevo curso"""
    try:
        course = await course_service.create_course(course_in=course_in)
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get(
    "/{id}",
    response_model=CourseResponse,
    summary="Ver Curso"
)
async def read_course(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Ver detalles de un curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return course

@router.put(
    "/{id}",
    response_model=CourseResponse,
    summary="Actualizar Curso"
)
async def update_course(
    *,
    id: PydanticObjectId,
    course_in: CourseUpdate,
    current_user: User = Depends(require_cpd) # <-- CPD EDITA LOS PROGRAMAS
) -> Any:
    """Actualizar curso existente"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    try:
        course = await course_service.update_course(course=course, course_in=course_in)
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete(
    "/{id}",
    response_model=CourseResponse,
    summary="Eliminar Curso"
)
async def delete_course(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin) # <-- SOLO SUPERADMIN BORRA
) -> Any:
    """Eliminar curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.delete_course(id=id)
    return course

@router.get(
    "/{id}/students",
    response_model=List[CourseEnrolledStudent],
    summary="Ver Inscritos del Curso"
)
async def get_course_students(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_staff) # <-- TODOS LOS ADMINISTRATIVOS VEN EL REPORTE
) -> Any:
    """Reporte detallado de estudiantes inscritos en un curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
        
    report = await course_service.get_course_students(course_id=id)
    return report

# ========================================================================
# NUEVO ENDPOINT (ISSUE R): Obtener Módulos por Docente
# ========================================================================
@router.get(
    "/modules/by-teacher/{teacher_id}",
    summary="Obtener módulos asignados a un docente"
)
async def get_modules_by_teacher(
    *,
    teacher_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user) # <-- PERMISO ABIERTO PARA DOCENTE Y STAFF
) -> Any:
    """
    Obtiene todos los módulos que un docente tiene asignados, iterando sobre los cursos activos.
    """
    # Verificación de seguridad: Evitar que estudiantes vean esto
    if isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Acceso denegado para estudiantes.")
        
    # Validar que si es un docente, solo pueda solicitar ver sus PROPIOS módulos
    if current_user.rol.value not in ["superadmin", "admin", "cpd", "mae", "cobranza"]:
        if str(current_user.id) != str(teacher_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para ver esta sección administrativa.")

    # Buscamos todos los cursos activos en la base de datos
    courses = await Course.find(Course.activo == True).to_list()
    
    assigned_modules = []
    
    for course in courses:
        # Iteramos sobre el array de módulos de cada curso
        for index, module in enumerate(course.modulos):
            # Si el módulo tiene un docente asociado y coincide con el solicitado
            if module.docente_id and str(module.docente_id) == str(teacher_id):
                assigned_modules.append({
                    "curso_id": str(course.id),
                    "curso_nombre": course.nombre_programa,
                    "curso_codigo": course.codigo,
                    "modulo_nombre": module.nombre,
                    "modulo_costo": module.costo,
                    "modulo_index": index + 1
                })
                
    return assigned_modules
