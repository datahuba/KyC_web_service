from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException
from models.student import Student
from schemas.student import StudentCreate, StudentResponse, StudentUpdate
from services import student_service
from beanie import PydanticObjectId

router = APIRouter()

@router.get("/", response_model=List[StudentResponse])
async def read_students(
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Recuperar estudiantes.
    """
    students = await student_service.get_students(skip=skip, limit=limit)
    return students

@router.post("/", response_model=StudentResponse)
async def create_student(
    *,
    student_in: StudentCreate,
) -> Any:
    """
    Crear nuevo estudiante.
    """
    student = await student_service.create_student(student_in=student_in)
    return student

@router.get("/{id}", response_model=StudentResponse)
async def read_student(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Obtener estudiante por ID.
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    return student

@router.put("/{id}", response_model=StudentResponse)
async def update_student(
    *,
    id: PydanticObjectId,
    student_in: StudentUpdate,
) -> Any:
    """
    Actualizar estudiante.
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    student = await student_service.update_student(student=student, student_in=student_in)
    return student

@router.delete("/{id}", response_model=StudentResponse)
async def delete_student(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Eliminar estudiante.
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    student = await student_service.delete_student(id=id)
    return student
