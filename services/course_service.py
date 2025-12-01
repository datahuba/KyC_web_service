"""
Servicio de Cursos
==================

Lógica de negocio para cursos (Funciones).
"""

from typing import List, Optional, Dict, Any, Union
from models.course import Course
from schemas.course import CourseCreate, CourseUpdate
from beanie import PydanticObjectId

async def get_course(id: PydanticObjectId) -> Optional[Course]:
    """Obtiene un curso por su ID"""
    return await Course.get(id)

async def get_courses(skip: int = 0, limit: int = 100) -> List[Course]:
    """Obtiene múltiples cursos con paginación"""
    return await Course.find_all().skip(skip).limit(limit).to_list()

async def create_course(course_in: CourseCreate) -> Course:
    """Crea un nuevo curso"""
    course = Course(**course_in.dict())
    await course.create()
    return course

async def update_course(
    course: Course, 
    course_in: Union[CourseUpdate, Dict[str, Any]]
) -> Course:
    """Actualiza un curso existente"""
    if isinstance(course_in, dict):
        update_data = course_in
    else:
        update_data = course_in.dict(exclude_unset=True)
        
    for field, value in update_data.items():
        setattr(course, field, value)
        
    await course.save()
    return course

async def delete_course(id: PydanticObjectId) -> Optional[Course]:
    """Elimina un curso"""
    course = await Course.get(id)
    if course:
        await course.delete()
    return course
