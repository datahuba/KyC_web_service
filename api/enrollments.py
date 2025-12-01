from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException
from models.enrollment import Enrollment
from models.user import User
from models.student import Student
from schemas.enrollment import EnrollmentCreate, EnrollmentResponse, EnrollmentUpdate
from services import enrollment_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[EnrollmentResponse])
async def read_enrollments(
    skip: int = 0,
    limit: int = 100,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Recuperar inscripciones.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Ven todas las inscripciones
    - STUDENT: Solo ve sus propias inscripciones
    """
    if isinstance(current_user, Student):
        # Estudiantes solo ven sus inscripciones
        enrollments = await Enrollment.find(
            Enrollment.estudiante_id == current_user.id
        ).skip(skip).limit(limit).to_list()
    else:
        # Admins ven todas
        enrollments = await enrollment_service.get_enrollments(skip=skip, limit=limit)
    
    return enrollments

@router.post("/", response_model=EnrollmentResponse)
async def create_enrollment(
    *,
    enrollment_in: EnrollmentCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nueva inscripción.
    Calcula automáticamente los montos a pagar.
    
    Requiere: ADMIN o SUPERADMIN
    """
    enrollment = await enrollment_service.create_enrollment(enrollment_in=enrollment_in)
    return enrollment

@router.get("/{id}", response_model=EnrollmentResponse)
async def read_enrollment(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener inscripción por ID.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden ver cualquier inscripción
    - STUDENT: Solo puede ver sus propias inscripciones
    """
    enrollment = await enrollment_service.get_enrollment(id=id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    
    # Si es estudiante, solo puede ver sus propias inscripciones
    if isinstance(current_user, Student) and enrollment.estudiante_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para ver esta inscripción"
        )
    
    return enrollment

@router.put("/{id}", response_model=EnrollmentResponse)
async def update_enrollment(
    *,
    id: PydanticObjectId,
    enrollment_in: EnrollmentUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar inscripción.
    
    Requiere: ADMIN o SUPERADMIN
    """
    enrollment = await enrollment_service.get_enrollment(id=id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    enrollment = await enrollment_service.update_enrollment(enrollment=enrollment, enrollment_in=enrollment_in)
    return enrollment

@router.delete("/{id}", response_model=EnrollmentResponse)
async def delete_enrollment(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar inscripción.
    
    Requiere: SUPERADMIN
    """
    enrollment = await enrollment_service.get_enrollment(id=id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    enrollment = await enrollment_service.delete_enrollment(id=id)
    return enrollment
