from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException
from models.payment import Payment
from models.user import User
from models.student import Student
from schemas.payment import PaymentCreate, PaymentResponse, PaymentUpdate
from services import payment_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[PaymentResponse])
async def read_payments(
    skip: int = 0,
    limit: int = 100,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Recuperar pagos.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Ven todos los pagos
    - STUDENT: Solo ve sus propios pagos
    """
    if isinstance(current_user, Student):
        # Estudiantes solo ven sus pagos
        payments = await Payment.find(
            Payment.estudiante_id == current_user.id
        ).skip(skip).limit(limit).to_list()
    else:
        # Admins ven todos
        payments = await payment_service.get_payments(skip=skip, limit=limit)
    
    return payments

@router.post("/", response_model=PaymentResponse)
async def create_payment(
    *,
    payment_in: PaymentCreate,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Crear nuevo pago.
    
    Requiere: Autenticación (cualquier rol)
    """
    payment = await payment_service.create_payment(payment_in=payment_in)
    return payment

@router.get("/{id}", response_model=PaymentResponse)
async def read_payment(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener pago por ID.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden ver cualquier pago
    - STUDENT: Solo puede ver sus propios pagos
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    # Si es estudiante, solo puede ver sus propios pagos
    if isinstance(current_user, Student) and payment.estudiante_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para ver este pago"
        )
    
    return payment

@router.put("/{id}", response_model=PaymentResponse)
async def update_payment(
    *,
    id: PydanticObjectId,
    payment_in: PaymentUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar pago.
    
    Requiere: ADMIN o SUPERADMIN
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    payment = await payment_service.update_payment(payment=payment, payment_in=payment_in)
    return payment

@router.post("/{id}/approve", response_model=PaymentResponse)
async def approve_payment(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Aprobar un pago.
    Actualiza el estado del pago y el saldo de la inscripción.
    
    Requiere: ADMIN o SUPERADMIN
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    payment = await payment_service.approve_payment(payment=payment)
    return payment

@router.delete("/{id}", response_model=PaymentResponse)
async def delete_payment(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar pago.
    
    Requiere: SUPERADMIN
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    payment = await payment_service.delete_payment(id=id)
    return payment
