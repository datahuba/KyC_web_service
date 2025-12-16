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
    
    # 3. Calcular detalles del pago automáticamente (Single Source of Truth)
    siguiente = enrollment.siguiente_pago
    
    if siguiente["monto_sugerido"] <= 0:
        raise ValueError("Esta inscripción ya está completamente pagada")
        
    # Forzamos los valores calculados por el sistema
    concepto_final = siguiente["concepto"]
    numero_cuota_final = siguiente["numero_cuota"] if siguiente["numero_cuota"] > 0 else None
    cantidad_final = siguiente["monto_sugerido"]
    
    # Si el usuario envió una cantidad diferente, podríamos lanzar error,
    # pero para cumplir "no tiene opción de poner cantidad distinta",
    # simplemente ignoramos su input y usamos el calculado.
    # El admin verificará si el comprobante coincide con este monto.

    # 4. Crear pago
    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,
        estudiante_id=enrollment.estudiante_id,
        curso_id=enrollment.curso_id,
        concepto=concepto_final,
        numero_cuota=numero_cuota_final,
        numero_transaccion=payment_in.numero_transaccion,
        cantidad_pago=cantidad_final,
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


from beanie.operators import Or

async def get_all_payments(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    estado: Optional[EstadoPago] = None,
    curso_id: Optional[PydanticObjectId] = None,
    estudiante_id: Optional[PydanticObjectId] = None
) -> tuple[List[Payment], int]:
    """
    Obtener todos los pagos con paginación y filtros
    
    Args:
        page: Número de página
        per_page: Elementos por página
        q: Búsqueda por número de transacción o comprobante
        estado: Filtrar por estado
        curso_id: Filtrar por Curso ID
        estudiante_id: Filtrar por Estudiante ID
    """
    query = Payment.find()
    
    # 1. Filtro Estado
    if estado:
        query = query.find(Payment.estado_pago == estado)
        
    # 2. Filtro Curso ID
    if curso_id:
        query = query.find(Payment.curso_id == curso_id)
        
    # 3. Filtro Estudiante ID
    if estudiante_id:
        query = query.find(Payment.estudiante_id == estudiante_id)
        
    # 4. Búsqueda por texto (q)
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        query = query.find(
            Or(
                Payment.numero_transaccion == regex_pattern,
                Payment.comprobante_url == regex_pattern,
                Payment.concepto == regex_pattern
            )
        )
    
    total_count = await query.count()
    skip = (page - 1) * per_page
    
    payments = await query.skip(skip).limit(per_page).to_list()
    return payments, total_count


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
