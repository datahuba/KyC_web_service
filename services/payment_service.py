"""
Servicio de Pagos
=================

Lógica de negocio para pagos (Funciones).
Actualiza el saldo de la inscripción al registrar un pago.
"""

from typing import List, Optional, Dict, Any, Union
from models.payment import Payment
from models.enrollment import Enrollment
from schemas.payment import PaymentCreate, PaymentUpdate
from beanie import PydanticObjectId
from fastapi import HTTPException

async def get_payment(id: PydanticObjectId) -> Optional[Payment]:
    """Obtiene un pago por su ID"""
    return await Payment.get(id)

async def get_payments(skip: int = 0, limit: int = 100) -> List[Payment]:
    """Obtiene múltiples pagos con paginación"""
    return await Payment.find_all().skip(skip).limit(limit).to_list()

async def create_payment(payment_in: PaymentCreate) -> Payment:
    """
    Registra un pago y actualiza el saldo de la inscripción
    """
    # 1. Verificar inscripción
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        
    # 2. Crear pago
    payment = Payment(**payment_in.dict())
    await payment.create()
    
    return payment

async def update_payment(
    payment: Payment, 
    payment_in: Union[PaymentUpdate, Dict[str, Any]]
) -> Payment:
    """Actualiza un pago existente"""
    if isinstance(payment_in, dict):
        update_data = payment_in
    else:
        update_data = payment_in.dict(exclude_unset=True)
        
    for field, value in update_data.items():
        setattr(payment, field, value)
        
    await payment.save()
    return payment

async def delete_payment(id: PydanticObjectId) -> Optional[Payment]:
    """Elimina un pago"""
    payment = await Payment.get(id)
    if payment:
        await payment.delete()
    return payment
    
async def approve_payment_logic(payment_id: PydanticObjectId) -> Payment:
    """
    Aprueba un pago y actualiza el saldo de la inscripción
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    if payment.estado_pago == "aceptado":
        return payment # Ya estaba aprobado
        
    # Aprobar
    payment.aprobar_pago()
    await payment.save()
    
    # Actualizar inscripción
    enrollment = await Enrollment.get(payment.inscripcion_id)
    if enrollment:
        enrollment.registrar_pago(payment.cantidad_pago)
        await enrollment.save()
        
    return payment
