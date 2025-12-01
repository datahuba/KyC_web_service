from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdate
from services import student_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[StudentResponse])
async def read_students(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Recuperar estudiantes.
    
    Requiere: ADMIN o SUPERADMIN
    """
    students = await student_service.get_students(skip=skip, limit=limit)
    return students

@router.post("/", response_model=StudentResponse)
async def create_student(
    *,
    student_in: StudentCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo estudiante.
    
    Requiere: ADMIN o SUPERADMIN
    """
    student = await student_service.create_student(student_in=student_in)
    return student

@router.get("/{id}", response_model=StudentResponse)
async def read_student(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener estudiante por ID.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden ver cualquier estudiante
    - STUDENT: Solo puede ver su propio perfil
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Si es estudiante, solo puede ver su propio perfil
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para ver este estudiante"
        )
    
    return student

@router.put("/{id}", response_model=StudentResponse)
async def update_student(
    *,
    id: PydanticObjectId,
    student_in: StudentUpdate,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Actualizar estudiante.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden actualizar cualquier estudiante
    - STUDENT: Solo puede actualizar su propio perfil
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Si es estudiante, solo puede actualizar su propio perfil
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para actualizar este estudiante"
        )
    
    student = await student_service.update_student(student=student, student_in=student_in)
    return student

@router.delete("/{id}", response_model=StudentResponse)
async def delete_student(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Eliminar estudiante.
    
    Requiere: ADMIN o SUPERADMIN (solo SUPERADMIN puede eliminar)
    """
    # Solo SUPERADMIN puede eliminar
    from models.enums import UserRole
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo SUPERADMIN puede eliminar estudiantes"
        )
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    student = await student_service.delete_student(id=id)
    return student
