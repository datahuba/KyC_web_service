from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException
from models.payment import Payment
from schemas.payment import PaymentCreate, PaymentResponse, PaymentUpdate
from services import payment_service
from beanie import PydanticObjectId

router = APIRouter()

@router.get("/", response_model=List[PaymentResponse])
async def read_payments(
    skip: int = 0,
    limit: int = 100,
) -> Any:
    """
    Recuperar pagos.
    """
    payments = await payment_service.get_payments(skip=skip, limit=limit)
    return payments

@router.post("/", response_model=PaymentResponse)
async def create_payment(
    *,
    payment_in: PaymentCreate,
) -> Any:
    """
    Registrar nuevo pago.
    """
    payment = await payment_service.create_payment(payment_in=payment_in)
    return payment

@router.get("/{id}", response_model=PaymentResponse)
async def read_payment(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Obtener pago por ID.
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    return payment

@router.put("/{id}/approve", response_model=PaymentResponse)
async def approve_payment(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Aprobar un pago.
    Esto actualiza el estado del pago a ACEPTADO y reduce el saldo pendiente de la inscripción.
    """
    payment = await payment_service.approve_payment_logic(payment_id=id)
    return payment

@router.put("/{id}", response_model=PaymentResponse)
async def update_payment(
    *,
    id: PydanticObjectId,
    payment_in: PaymentUpdate,
) -> Any:
    """
    Actualizar pago (edición general).
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    payment = await payment_service.update_payment(payment=payment, payment_in=payment_in)
    return payment

@router.delete("/{id}", response_model=PaymentResponse)
async def delete_payment(
    *,
    id: PydanticObjectId,
) -> Any:
    """
    Eliminar pago.
    """
    payment = await payment_service.get_payment(id=id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    payment = await payment_service.delete_payment(id=id)
    return payment
