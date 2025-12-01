from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException
from models.course import Course
from models.user import User
from models.student import Student
from schemas.course import CourseCreate, CourseResponse, CourseUpdate
from services import course_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[CourseResponse])
async def read_courses(
    skip: int = 0,
    limit: int = 100,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Recuperar cursos.
    
    Requiere: Autenticación (cualquier rol)
    """
    courses = await course_service.get_courses(skip=skip, limit=limit)
    return courses

@router.post("/", response_model=CourseResponse)
async def create_course(
    *,
    course_in: CourseCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo curso.
    
    Requiere: ADMIN o SUPERADMIN
    """
    course = await course_service.create_course(course_in=course_in)
    return course

@router.get("/{id}", response_model=CourseResponse)
async def read_course(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener curso por ID.
    
    Requiere: Autenticación (cualquier rol)
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    return course

@router.put("/{id}", response_model=CourseResponse)
async def update_course(
    *,
    id: PydanticObjectId,
    course_in: CourseUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar curso.
    
    Requiere: ADMIN o SUPERADMIN
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.update_course(course=course, course_in=course_in)
    return course

@router.delete("/{id}", response_model=CourseResponse)
async def delete_course(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar curso.
    
    Requiere: SUPERADMIN
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.delete_course(id=id)
    return course
