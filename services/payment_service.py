"""
Servicio de Pagos (Payments)
============================

Lógica de negocio para pagos.

Permisos:
---------
- CREAR pago: Solo STUDENT (sube su propio comprobante)
- APROBAR/RECHAZAR pago: Solo ADMIN/SUPERADMIN
- VER pagos: ADMIN (todos), STUDENT (solo los suyos)
"""

from typing import List, Optional
from datetime import datetime
from models.payment import Payment
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.enums import EstadoPago
from schemas.payment import PaymentCreate
from beanie import PydanticObjectId
from services import enrollment_service


async def create_payment(
    payment_in: PaymentCreate,
    student_id: PydanticObjectId
) -> Payment:
    """
    Crear un nuevo pago (estudiante sube comprobante)
    
    Proceso:
    1. Validar que la inscripción existe
    2. Validar que el estudiante sea dueño de la inscripción
    3. Obtener datos de enrollment para llenar referencias
    4. Crear pago con estado PENDIENTE
    
    Args:
        payment_in: Datos del pago
        student_id: ID del estudiante que crea el pago
    
    Returns:
        Pago creado
    
    Raises:
        ValueError: Si la inscripción no existe
        ValueError: Si el estudiante no es dueño de la inscripción
    """
    
    # 1. Obtener inscripción
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment_in.inscripcion_id} no encontrada")
    
    # 2. Validar que el estudiante sea dueño de la inscripción
    if enrollment.estudiante_id != student_id:
        raise ValueError(
            "No puedes crear un pago para una inscripción que no te pertenece"
        )
    
    # 3. Crear pago
    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,
        estudiante_id=enrollment.estudiante_id,
        curso_id=enrollment.curso_id,
        concepto=payment_in.concepto,
        numero_cuota=payment_in.numero_cuota,
        numero_transaccion=payment_in.numero_transaccion,
        cantidad_pago=payment_in.cantidad_pago,
        descuento_aplicado=payment_in.descuento_aplicado,
        comprobante_url=payment_in.comprobante_url,
        estado_pago=EstadoPago.PENDIENTE
    )
    
    await payment.insert()
    return payment


async def get_payment(id: PydanticObjectId) -> Optional[Payment]:
    """Obtener un pago por ID"""
    return await Payment.get(id)


async def get_payments_by_student(student_id: PydanticObjectId) -> List[Payment]:
    """Obtener todos los pagos de un estudiante"""
    return await Payment.find(
        Payment.estudiante_id == student_id
    ).to_list()


async def get_payments_by_enrollment(enrollment_id: PydanticObjectId) -> List[Payment]:
    """Obtener todos los pagos de una inscripción"""
    return await Payment.find(
        Payment.inscripcion_id == enrollment_id
    ).to_list()


async def get_payments_by_course(course_id: PydanticObjectId) -> List[Payment]:
    """Obtener todos los pagos de un curso"""
    return await Payment.find(
        Payment.curso_id == course_id
    ).to_list()


async def get_all_payments(
    skip: int = 0,
    limit: int = 100,
    estado: Optional[EstadoPago] = None
) -> List[Payment]:
    """
    Obtener todos los pagos (solo admins)
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        estado: Filtrar por estado (opcional)
    """
    query = Payment.find()
    
    if estado:
        query = query.find(Payment.estado_pago == estado)
    
    return await query.skip(skip).limit(limit).to_list()


async def get_payments_pendientes() -> List[Payment]:
    """
    Obtener todos los pagos pendientes de revisión (solo admins)
    
    Útil para mostrar al admin los pagos que necesitan aprobación
    """
    return await Payment.find(
        Payment.estado_pago == EstadoPago.PENDIENTE
    ).to_list()


async def aprobar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> Payment:
    """
    Aprobar un pago (solo admin)
    
    Proceso:
    1. Obtener pago
    2. Validar que esté PENDIENTE
    3. Cambiar estado a APROBADO
    4. Actualizar enrollment (total_pagado, saldo_pendiente)
    5. Cambiar estado de enrollment si corresponde
    
    Args:
        payment_id: ID del pago
        admin_username: Username del admin que aprueba
    
    Returns:
        Pago aprobado
    
    Raises:
        ValueError: Si el pago no existe
        ValueError: Si el pago no está pendiente
    """
    
    # 1. Obtener pago
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    # 2. Validar estado
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede aprobar un pago que está en estado {payment.estado_pago}"
        )
    
    # 3. Aprobar pago
    payment.aprobar_pago(admin_username)
    await payment.save()
    
    # 4. Actualizar enrollment
    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=payment.inscripcion_id,
        monto_pago_aprobado=payment.cantidad_pago
    )
    
    return payment


async def rechazar_pago(
    payment_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> Payment:
    """
    Rechazar un pago (solo admin)
    
    Proceso:
    1. Obtener pago
    2. Validar que esté PENDIENTE
    3. Cambiar estado a RECHAZADO con motivo
    
    Args:
        payment_id: ID del pago
        admin_username: Username del admin que rechaza
        motivo: Razón del rechazo
    
    Returns:
        Pago rechazado
    
    Raises:
        ValueError: Si el pago no existe
        ValueError: Si el pago no está pendiente
    """
    
    # 1. Obtener pago
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    # 2. Validar estado
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede rechazar un pago que está en estado {payment.estado_pago}"
        )
    
    # 3. Rechazar pago
    payment.rechazar_pago(admin_username, motivo)
    await payment.save()
    
    return payment


async def get_resumen_pagos_enrollment(enrollment_id: PydanticObjectId) -> dict:
    """
    Obtener resumen de pagos de una inscripción
    
    Returns:
        dict con estadísticas:
        - total_pagos: cantidad total de pagos
        - pendientes: cantidad pendientes
        - aprobados: cantidad aprobados
        - rechazados: cantidad rechazados
        - monto_total_aprobado: suma de pagos aprobados
    """
    payments = await get_payments_by_enrollment(enrollment_id)
    
    resumen = {
        "total_pagos": len(payments),
        "pendientes": len([p for p in payments if p.estado_pago == EstadoPago.PENDIENTE]),
        "aprobados": len([p for p in payments if p.estado_pago == EstadoPago.APROBADO]),
        "rechazados": len([p for p in payments if p.estado_pago == EstadoPago.RECHAZADO]),
        "monto_total_aprobado": sum(
            p.cantidad_pago for p in payments if p.estado_pago == EstadoPago.APROBADO
        ),
    }
    
    return resumen
