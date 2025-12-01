from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException
from models.enrollment import Enrollment
from schemas.enrollment import EnrollmentCreate, EnrollmentResponse, EnrollmentUpdate
from services import enrollment_service
from beanie import PydanticObjectId

router = APIRouter()

@router.get("/", response_model=List[EnrollmentResponse])
async def read_enrollments(
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Recuperar inscripciones.
    """
    enrollments = await enrollment_service.get_enrollments(skip=skip, limit=limit)
    return enrollments

@router.post("/", response_model=EnrollmentResponse)
async def create_enrollment(
    *,
    enrollment_in: EnrollmentCreate,
) -> Any:
    """
    Crear nueva inscripción.
    Calcula automáticamente los montos a pagar.
    """
    enrollment = await enrollment_service.create_enrollment(enrollment_in=enrollment_in)
    return enrollment

@router.get("/{id}", response_model=EnrollmentResponse)
async def read_enrollment(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Obtener inscripción por ID.
    """
    enrollment = await enrollment_service.get_enrollment(id=id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    return enrollment

@router.put("/{id}", response_model=EnrollmentResponse)
async def update_enrollment(
    *,
    id: PydanticObjectId,
    enrollment_in: EnrollmentUpdate,
) -> Any:
    """
    Actualizar inscripción.
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
) -> Any:
    """
    Eliminar inscripción.
    """
    enrollment = await enrollment_service.get_enrollment(id=id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
    enrollment = await enrollment_service.delete_enrollment(id=id)
    return enrollment
