"""
API de Pagos (Payments)
=======================

Endpoints para gestionar pagos de estudiantes.

Permisos:
---------
- POST /payments/: STUDENT (solo sus pagos)
- GET /payments/: ADMIN (todos) / STUDENT (solo los suyos)
- GET /payments/{id}: ADMIN / STUDENT (si es suyo)
- PUT /payments/{id}/aprobar: ADMIN/SUPERADMIN
- PUT /payments/{id}/rechazar: ADMIN/SUPERADMIN
- GET /payments/enrollment/{enrollment_id}: ADMIN / STUDENT (si es suya)
- GET /payments/pendientes: ADMIN
"""

from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from models.payment import Payment
from models.student import Student
from models.user import User
from models.enums import EstadoPago
from schemas.payment import (
    PaymentCreate,
    PaymentResponse,
    PaymentApproval,
    PaymentRejection,
    PaymentWithDetails
)
from services import payment_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()


@router.post("/", response_model=PaymentResponse, status_code=201)
async def create_payment(
    *,
    payment_in: PaymentCreate,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Crear un nuevo pago (solo estudiantes)
    
    Requiere: Autenticación como STUDENT
    
    El estudiante sube:
    - Comprobante de pago (PDF en Cloudinary)
    - Número de transacción bancaria
    - Monto pagado
    - Concepto (MATRICULA, CUOTA)
    
    El pago queda en estado PENDIENTE hasta que un admin lo apruebe.
    
    Validaciones:
    - La inscripción existe
    - El estudiante es dueño de la inscripción
    """
    # Solo estudiantes pueden crear pagos
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )
    
    try:
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=current_user.id
        )
        return payment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/", response_model=List[PaymentResponse])
async def list_payments(
    *,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    estado: Optional[EstadoPago] = None,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Listar pagos
    
    Permisos:
    - ADMIN: Ve todos los pagos
    - STUDENT: Ve solo sus propios pagos
    
    Filtros disponibles:
    - estado: Filtrar por estado (PENDIENTE, APROBADO, RECHAZADO)
    """
    # Si es admin, retorna todos
    if isinstance(current_user, User):
        payments = await payment_service.get_all_payments(
            skip=skip,
            limit=limit,
            estado=estado
        )
        return payments
    
    # Si es estudiante, solo sus pagos
    if isinstance(current_user, Student):
        payments = await payment_service.get_payments_by_student(
            student_id=current_user.id
        )
        
        # Aplicar filtro de estado si lo pidió
        if estado:
            payments = [p for p in payments if p.estado_pago == estado]
        
        # Aplicar paginación manual
        return payments[skip:skip + limit]
    
    raise HTTPException(status_code=403, detail="No autorizado")


@router.get("/{id}", response_model=PaymentResponse)
async def get_payment(
    *,
    id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Obtener un pago específico
    
    Permisos:
    - ADMIN: Puede ver cualquier pago
    - STUDENT: Solo puede ver sus propios pagos
    """
    payment = await payment_service.get_payment(id)
    
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    # Si es estudiante, validar que sea suyo
    if isinstance(current_user, Student):
        if payment.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver este pago"
            )
    
    return payment


@router.put("/{id}/aprobar", response_model=PaymentResponse)
async def aprobar_pago(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Aprobar un pago (solo admins)
    
    Requiere: ADMIN o SUPERADMIN
    
    Proceso automático:
    1. Cambia estado del pago a APROBADO
    2. Actualiza enrollment.total_pagado
    3. Actualiza enrollment.saldo_pendiente
    4. Cambia estado de enrollment si corresponde:
       - PENDIENTE_PAGO → ACTIVO (cuando paga matrícula)
       - ACTIVO → COMPLETADO (cuando paga todo)
    """
    try:
        payment = await payment_service.aprobar_pago(
            payment_id=id,
            admin_username=current_user.username
        )
        return payment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/{id}/rechazar", response_model=PaymentResponse)
async def rechazar_pago(
    *,
    id: PydanticObjectId,
    rejection: PaymentRejection,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Rechazar un pago (solo admins)
    
    Requiere: ADMIN o SUPERADMIN
    
    Motivos comunes de rechazo:
    - Voucher ilegible
    - Monto incorrecto
    - Transacción no encontrada en el banco
    - Voucher duplicado
    
    El estudiante podrá ver el motivo y subir un nuevo comprobante.
    """
    try:
        payment = await payment_service.rechazar_pago(
            payment_id=id,
            admin_username=current_user.username,
            motivo=rejection.motivo
        )
        return payment
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/enrollment/{enrollment_id}", response_model=List[PaymentResponse])
async def get_payments_by_enrollment(
    *,
    enrollment_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Obtener todos los pagos de una inscripción
    
    Permisos:
    - ADMIN: Puede ver pagos de cualquier inscripción
    - STUDENT: Solo puede ver pagos de sus inscripciones
    """
    # Si es estudiante, validar que la inscripción sea suya
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver pagos de esta inscripción"
            )
    
    payments = await payment_service.get_payments_by_enrollment(enrollment_id)
    return payments


@router.get("/enrollment/{enrollment_id}/resumen")
async def get_resumen_pagos(
    *,
    enrollment_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Obtener resumen de pagos de una inscripción
    
    Retorna:
    - total_pagos: Cantidad total de pagos
    - pendientes: Cantidad de pagos pendientes
    - aprobados: Cantidad de pagos aprobados
    - rechazados: Cantidad de pagos rechazados
    - monto_total_aprobado: Suma de pagos aprobados
    
    Permisos:
    - ADMIN: Puede ver resumen de cualquier inscripción
    - STUDENT: Solo puede ver resumen de sus inscripciones
    """
    # Si es estudiante, validar que la inscripción sea suya
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver este resumen"
            )
    
    resumen = await payment_service.get_resumen_pagos_enrollment(enrollment_id)
    return resumen


@router.get("/pendientes/list", response_model=List[PaymentResponse])
async def get_payments_pendientes(
    *,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Obtener todos los pagos pendientes de aprobación (solo admins)
    
    Requiere: ADMIN o SUPERADMIN
    
    Útil para:
    - Dashboard de admin (mostrar pagos por revisar)
    - Notificaciones (cantidad de pagos pendientes)
    - Procesamiento batch de aprobaciones
    """
    payments = await payment_service.get_payments_pendientes()
    return payments
