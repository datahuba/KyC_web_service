"""
Servicio de Estudiantes
=======================

Lógica de negocio para estudiantes (Funciones).
"""

from typing import List, Optional, Dict, Any, Union
from models.student import Student
from schemas.student import StudentCreate, StudentUpdate
from beanie import PydanticObjectId

async def get_student(id: PydanticObjectId) -> Optional[Student]:
    """Obtiene un estudiante por su ID"""
    return await Student.get(id)

async def get_students(skip: int = 0, limit: int = 100) -> List[Student]:
    """Obtiene múltiples estudiantes con paginación"""
    return await Student.find_all().skip(skip).limit(limit).to_list()

async def create_student(student_in: StudentCreate) -> Student:
    """Crea un nuevo estudiante"""
    student = Student(**student_in.dict())
    await student.create()
    return student

async def update_student(
    student: Student, 
    student_in: Union[StudentUpdate, Dict[str, Any]]
) -> Student:
    """Actualiza un estudiante existente"""
    if isinstance(student_in, dict):
        update_data = student_in
    else:
        update_data = student_in.dict(exclude_unset=True)
        
    for field, value in update_data.items():
        setattr(student, field, value)
        
    await student.save()
    return student

async def delete_student(id: PydanticObjectId) -> Optional[Student]:
    """Elimina un estudiante"""
    student = await Student.get(id)
    if student:
        await student.delete()
    return student
