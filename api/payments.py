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
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
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
    file: UploadFile = File(..., description="Comprobante de pago (imagen JPG/PNG/WEBP o PDF)"),
    inscripcion_id: str = Form(..., description="ID de la inscripción"),
    numero_transaccion: str = Form(..., description="Número de transacción bancaria"),
    descuento_aplicado: Optional[float] = Form(None, description="Descuento adicional (opcional)"),
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Crear un nuevo pago (solo estudiantes)
    
    Requiere: Autenticación como STUDENT
    
    Content-Type: multipart/form-data
    
    El estudiante sube:
    - file: Comprobante de pago en IMAGEN (JPG, PNG, WEBP) o PDF
    - inscripcion_id: ID de la inscripción a la que pertenece el pago
    - numero_transaccion: Número de transacción bancaria
    - descuento_aplicado: Descuento adicional (opcional)
    
    El sistema automáticamente:
    1. Detecta si es imagen o PDF
    2. Valida el formato del archivo
    3. Sube el comprobante a Cloudinary
    4. Calcula el monto exacto a pagar (matrícula o cuota)
    5. Determina el concepto (Matrícula, Cuota X)
    6. Crea el pago en estado PENDIENTE
    
    El pago queda en estado PENDIENTE hasta que un admin lo apruebe.
    
    Validaciones:
    - El archivo debe ser imagen (JPG, PNG, WEBP) o PDF
    - Tamaño máximo: 5MB para imágenes, 10MB para PDFs
    - La inscripción debe existir
    - El estudiante debe ser dueño de la inscripción
    - El monto se calcula automáticamente (NO es editable)
    """
    from core.cloudinary_utils import upload_image, upload_pdf
    from schemas.payment import PaymentCreate
    
    # Solo estudiantes pueden crear pagos
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )
    
    try:
        # Detectar tipo de archivo y subir según corresponda
        folder = f"payments/{current_user.id}"
        safe_transaction = numero_transaccion.replace(' ', '_').replace('/', '_')
        public_id = f"voucher_{safe_transaction}"
        
        # Tipos de archivo permitidos
        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        pdf_type = "application/pdf"
        
        if file.content_type in image_types:
            # Es una imagen - usar upload_image
            comprobante_url = await upload_image(file, folder, public_id)
            
        elif file.content_type == pdf_type:
            # Es un PDF - usar upload_pdf
            comprobante_url = await upload_pdf(file, folder, public_id)
            
        else:
            # Tipo no permitido
            raise HTTPException(
                status_code=400,
                detail=f"Formato no permitido: {file.content_type}. "
                       f"Use imagen (JPG, PNG, WEBP) o PDF"
            )
        
        # Crear schema con los datos + URL generada
        payment_in = PaymentCreate(
            inscripcion_id=inscripcion_id,
            numero_transaccion=numero_transaccion,
            comprobante_url=comprobante_url,
            descuento_aplicado=descuento_aplicado
        )
        
        # Crear pago usando el servicio
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=current_user.id
        )
        
        return payment
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear pago: {str(e)}")


from schemas.common import PaginatedResponse, PaginationMeta
import math

@router.get("/", response_model=PaginatedResponse[PaymentResponse])
async def list_payments(
    *,
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=500, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por transacción o comprobante"),
    estado: Optional[EstadoPago] = Query(None, description="Filtrar por estado"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Curso ID"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Estudiante ID"),
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Listar pagos con paginación y filtros
    
    Permisos:
    - ADMIN: Ve todos los pagos (con filtros avanzados)
    - STUDENT: Ve solo sus propios pagos
    """
    # Si es admin, retorna todos (paginadas en DB)
    if isinstance(current_user, User):
        payments, total_count = await payment_service.get_all_payments(
            page=page,
            per_page=per_page,
            q=q,
            estado=estado,
            curso_id=curso_id,
            estudiante_id=estudiante_id
        )
    
    # Si es estudiante, solo sus pagos (paginadas en memoria por ahora)
    elif isinstance(current_user, Student):
        all_payments = await payment_service.get_payments_by_student(
            student_id=current_user.id
        )
        
        # Aplicar filtro de estado si lo pidió
        if estado:
            all_payments = [p for p in all_payments if p.estado_pago == estado]
            
        total_count = len(all_payments)
        
        # Aplicar paginación manual
        start = (page - 1) * per_page
        end = start + per_page
        payments = all_payments[start:end]
    
    else:
        raise HTTPException(status_code=403, detail="No autorizado")

    # Calcular metadatos comunes
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": payments,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=has_next,
            hasPrevPage=has_prev
        )
    }


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
