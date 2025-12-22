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
    3. Determinar concepto/cuota a pagar (usa siguiente_pago como default)
    4. Validar que NO exista un pago duplicado (PENDIENTE o APROBADO)
    5. Crear pago con estado PENDIENTE
    
    Args:
        payment_in: Datos del pago
        student_id: ID del estudiante que crea el pago
    
    Returns:
        Pago creado
    
    Raises:
        ValueError: Si la inscripción no existe
        ValueError: Si el estudiante no es dueño de la inscripción
        ValueError: Si ya existe un pago para ese concepto/cuota
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
    
    # 3. Determinar concepto y cuota a pagar
    # Por ahora, siempre usamos siguiente_pago (puede extenderse para permitir selección)
    siguiente = enrollment.siguiente_pago
    
    if siguiente["monto_sugerido"] <= 0:
        raise ValueError("Esta inscripción ya está completamente pagada")
        
    concepto_final = siguiente["concepto"]
    numero_cuota_final = siguiente["numero_cuota"] if siguiente["numero_cuota"] > 0 else None
    cantidad_final = siguiente["monto_sugerido"]
    
    # ✅ 4. VALIDACIÓN ANTI-DUPLICADOS
    # Verificar que NO exista un pago PENDIENTE o APROBADO para este concepto/cuota
    existing_payment = await Payment.find_one(
        Payment.inscripcion_id == payment_in.inscripcion_id,
        Payment.concepto == concepto_final,
        Payment.numero_cuota == numero_cuota_final,
        Payment.estado_pago.in_([EstadoPago.PENDIENTE, EstadoPago.APROBADO])
    )
    
    if existing_payment:
        estado_texto = "pendiente" if existing_payment.estado_pago == EstadoPago.PENDIENTE else "aprobado"
        cuota_texto = f" (Cuota {numero_cuota_final})" if numero_cuota_final else ""
        raise ValueError(
            f"Ya existe un pago {estado_texto} para {concepto_final}{cuota_texto}. "
            f"No puedes crear un pago duplicado. "
            f"Si necesitas corregirlo, contacta al administrador para que rechace el pago actual."
        )

    # 5. Crear pago
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
    
    # ✅ 3. VALIDACIÓN ANTI-DUPLICADOS
    # Verificar que NO exista otro pago APROBADO para el mismo concepto/cuota
    existing_approved = await Payment.find_one(
        Payment.id != payment_id,  # Excluir el pago actual
        Payment.inscripcion_id == payment.inscripcion_id,
        Payment.concepto == payment.concepto,
        Payment.numero_cuota == payment.numero_cuota,
        Payment.estado_pago == EstadoPago.APROBADO
    )
    
    if existing_approved:
        cuota_texto = f" (Cuota {payment.numero_cuota})" if payment.numero_cuota else ""
        raise ValueError(
            f"No se puede aprobar: ya existe un pago aprobado para {payment.concepto}{cuota_texto}. "
            f"Pago aprobado existente: {existing_approved.id}. "
            f"Este pago parece ser un duplicado. Considera rechazarlo en su lugar."
        )
    
    # 4. Aprobar pago
    payment.aprobar_pago(admin_username)
    await payment.save()
    
    # 5. Actualizar enrollment
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
