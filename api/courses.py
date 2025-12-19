from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException
from models.course import Course
from models.user import User
from models.student import Student
from schemas.course import CourseCreate, CourseResponse, CourseUpdate, CourseEnrolledStudent
from services import course_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin, get_current_user

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from models.enums import TipoCurso, Modalidad
from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[CourseResponse],
    summary="Listar Cursos",
    responses={
        200: {"description": "Lista de cursos con paginación y filtros"}
    }
)
async def read_courses(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por nombre o código"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    tipo_curso: Optional[TipoCurso] = Query(None, description="Filtrar por tipo de curso"),
    modalidad: Optional[Modalidad] = Query(None, description="Filtrar por modalidad"),
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Listar cursos con paginación y filtros
    
    **Requiere:** Usuario autenticado (cualquier rol)
    
    **Filtros disponibles:**
    - `q`: Búsqueda por nombre o código del curso
    - `activo`: true/false
    - `tipo_curso`: diplomado, curso, taller, seminario
    - `modalidad`: presencial, virtual, híbrido
    """
    courses, total_count = await course_service.get_courses(
        page=page,
        per_page=per_page,
        q=q,
        activo=activo,
        tipo_curso=tipo_curso,
        modalidad=modalidad
    )
    
    # Calcular metadatos
    total_pages = math.ceil(total_count / per_page)
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": courses,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=has_next,
            hasPrevPage=has_prev
        )
    }

@router.post(
    "/",
    response_model=CourseResponse,
    status_code=201,
    summary="Crear Curso",
    responses={
        201: {"description": "Curso creado exitosamente con requisitos configurados"},
        400: {"description": "Error de validación"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def create_course(
    *,
    course_in: CourseCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo curso
    
    **Requiere:** Admin o SuperAdmin
    
    **Puede incluir:**
    - Requisitos dinámicos (documentos que deben presentar los estudiantes)
    - Precios diferenciados (interno/externo)
    - Descuento del curso
    - Fechas de inicio/fin
    """
    course = await course_service.create_course(course_in=course_in)
    return course

@router.get(
    "/{id}",
    response_model=CourseResponse,
    summary="Ver Curso",
    responses={
        200: {"description": "Detalles completos del curso incluyendo requisitos"},
        404: {"description": "Curso no encontrado"}
    }
)
async def read_course(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Ver detalles de un curso
    
    **Requiere:** Usuario autenticado
    
    **Incluye:**
    - Información del curso
    - Requisitos configurados
    - Precios (interno/externo)
    - Lista de inscritos
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return course

@router.put(
    "/{id}",
    response_model=CourseResponse,
    summary="Actualizar Curso",
    responses={
        200: {"description": "Curso actualizado exitosamente"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Curso no encontrado"}
    }
)
async def update_course(
    *,
    id: PydanticObjectId,
    course_in: CourseUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar curso existente
    
    **Requiere:** Admin o SuperAdmin
    
    **Se puede actualizar:**
    - Información del curso
    - Requisitos (agregar/quitar/modificar)
    - Precios
    - Estado (activo/inactivo)
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.update_course(course=course, course_in=course_in)
    return course

@router.delete(
    "/{id}",
    response_model=CourseResponse,
    summary="Eliminar Curso",
    responses={
        200: {"description": "Curso eliminado exitosamente"},
        403: {"description": "Sin permisos - Solo SuperAdmin"},
        404: {"description": "Curso no encontrado"}
    }
)
async def delete_course(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar curso
    
    **Requiere:** SOLO SuperAdmin
    
    **Nota:** No se puede eliminar un curso con inscripciones activas
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.delete_course(id=id)
    return course

@router.get(
    "/{id}/students",
    response_model=List[CourseEnrolledStudent],
    summary="Ver Inscritos del Curso",
    responses={
        200: {"description": "Lista de estudiantes inscritos con información financiera"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Curso no encontrado"}
    }
)
async def get_course_students(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Reporte detallado de estudiantes inscritos en un curso
    
    **Requiere:** Admin o SuperAdmin
    
    **Para cada estudiante incluye:**
    - Datos personales (nombre, carnet, contacto)
    - Datos de inscripción (fecha, estado, tipo)
    - Datos financieros (total, pagado, saldo, % avance)
    
    **Útil para:**
    - Dashboard del curso
    - Reportes financieros
    - Seguimiento de pagos
    """
    # Verificar que el curso existe
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
        
    report = await course_service.get_course_students(course_id=id)
    return report
