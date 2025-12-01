"""
Servicio de Estudiantes
=======================

Lógica de negocio para estudiantes (Funciones).
"""

from typing import List, Optional
from models.student import Student
from schemas.student import StudentCreate, StudentUpdate
from beanie import PydanticObjectId


async def get_students(skip: int = 0, limit: int = 100) -> List[Student]:
    """Obtener lista de estudiantes"""
    return await Student.find_all().skip(skip).limit(limit).to_list()


async def get_student(id: PydanticObjectId) -> Optional[Student]:
    """Obtener estudiante por ID"""
    return await Student.get(id)


async def create_student(student_in: StudentCreate) -> Student:
    """
    Crear nuevo estudiante
    
    La contraseña se hashea automáticamente antes de guardar.
    """
    from core.security import get_password_hash
    
    student_data = student_in.model_dump()
    student_data["password"] = get_password_hash(student_data["password"])
    
    student = Student(**student_data)
    await student.insert()
    return student


async def update_student(
    student: Student,
    student_in: StudentUpdate
) -> Student:
    """Actualizar estudiante existente"""
    update_data = student_in.model_dump(exclude_unset=True)
    
    # Si se actualiza la contraseña, hashearla
    if "password" in update_data:
        from core.security import get_password_hash
        update_data["password"] = get_password_hash(update_data["password"])
    
    for field, value in update_data.items():
        setattr(student, field, value)
    
    await student.save()
    return student


async def delete_student(id: PydanticObjectId) -> Student:
    """Eliminar estudiante"""
    student = await Student.get(id)
    if student:
        await student.delete()
    return student
