from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException
from models.course import Course
from schemas.course import CourseCreate, CourseResponse, CourseUpdate
from services import course_service
from beanie import PydanticObjectId

router = APIRouter()

@router.get("/", response_model=List[CourseResponse])
async def read_courses(
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Recuperar cursos.
    """
    courses = await course_service.get_courses(skip=skip, limit=limit)
    return courses

@router.post("/", response_model=CourseResponse)
async def create_course(
    *,
    course_in: CourseCreate,
) -> Any:
    """
    Crear nuevo curso.
    """
    course = await course_service.create_course(course_in=course_in)
    return course

@router.get("/{id}", response_model=CourseResponse)
async def read_course(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Obtener curso por ID.
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
) -> Any:
    """
    Actualizar curso.
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
) -> Any:
    """
    Eliminar curso.
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.delete_course(id=id)
    return course
