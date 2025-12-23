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


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=201,
    summary="Registrar Pago",
    responses={
        201: {"description": "Pago registrado exitosamente, pendiente de aprobación"},
        400: {"description": "Error de validación: archivo inválido, inscripción no encontrada, etc."},
        403: {"description": "Sin permisos - No es tu inscripción"}
    }
)
async def create_payment(
    *,
    file: UploadFile = File(..., description="Comprobante de pago (imagen JPG/PNG/WEBP o PDF)"),
    inscripcion_id: str = Form(..., description="ID de la inscripción"),
    numero_transaccion: str = Form(..., description="Número de transacción bancaria"),
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Registrar un nuevo pago
    
    **Requiere:** Estudiante autenticado
    
    **El estudiante sube:**
    - `file`: Comprobante de pago (JPG, PNG, WEBP o PDF)
    - `inscripcion_id`: ID de su inscripción
    - `numero_transaccion`: Número de transacción del banco
    
    **El sistema automáticamente:**
    - ✅ **Detecta qué te falta pagar** (Matrícula -> Cuota 1 -> Cuota 2...)
    - ✅ **Revisa "huecos"**: Si te rechazaron la matrícula, te sugerirá pagarla de nuevo
    - ✅ **Permite múltiples pagos**: Puedes pagar Cuota 1 y Cuota 2 seguidas (quedan pendientes)
    - ✅ **Previene duplicados**: Si ya tienes un pago PENDIENTE para Cuota 1, no te deja crear otro igual
    
    **El admin debe aprobar** el pago para que se actualicen los totales.
    
    **Formatos permitidos:**
    - Imágenes: JPG, PNG, WEBP (máx 5MB)
    - PDF (máx 10MB)
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
            comprobante_url=comprobante_url
        )
        
        # Crear pago usando el servicio
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=current_user.id
        )
        
        # Enriquecer respuesta con datos legibles
        return await payment_service.enrich_payment_with_details(payment)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear pago: {str(e)}")


from schemas.common import PaginatedResponse, PaginationMeta
import math

@router.get(
    "/",
    response_model=PaginatedResponse[PaymentResponse],
    summary="Listar Pagos",
    responses={
        200: {"description": "Lista de pagos con paginación y filtros"},
        403: {"description": "Sin permisos"}
    }
)
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
    
    **Permisos:**
    - **Admin:** Ve TODOS los pagos con filtros avanzados
    - **Estudiante:** Ve SOLO sus propios pagos
    
    **Filtros (Admin):**
    - `estado`: pendiente, aprobado, rechazado
    - `curso_id`: Pagos de un curso específico
    - `estudiante_id`: Pagos de un estudiante
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
    
    # ✅ ENRIQUECER PAGOS con datos legibles (nombre estudiante, progreso, etc.)
    enriched_payments = []
    for payment in payments:
        enriched = await payment_service.enrich_payment_with_details(payment)
        enriched_payments.append(enriched)
    
    return {
        "data": enriched_payments,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=has_next,
            hasPrevPage=has_prev
        )
    }


@router.get(
    "/{id}",
    response_model=PaymentResponse,
    summary="Ver Pago",
    responses={
        200: {"description": "Detalles del pago"},
        403: {"description": "Sin permisos - Admin o dueño del pago"},
        404: {"description": "Pago no encontrado"}
    }
)
async def get_payment(
    *,
    id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Ver detalles de un pago
    
    **Permisos:**
    - **Admin:** Puede ver cualquier pago
    - **Estudiante:** Solo puede ver sus propios pagos
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
    
    return await payment_service.enrich_payment_with_details(payment)


@router.put(
    "/{id}/aprobar",
    response_model=PaymentResponse,
    summary="Aprobar Pago",
    responses={
        200: {"description": "Pago aprobado exitosamente, totales actualizados"},
        400: {"description": "Error: pago ya procesado o datos inválidos"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Pago no encontrado"}
    }
)
async def aprobar_pago(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Aprobar un pago
    
    **Requiere:** Admin o SuperAdmin
    
    **El sistema automáticamente:**
    1. Cambia estado del pago a APROBADO
    2. Actualiza `enrollment.total_pagado` (+monto)
    3. Actualiza `enrollment.saldo_pendiente` (-monto)
    4. Cambia estado del enrollment si corresponde:
       - PENDIENTE_PAGO → ACTIVO (al pagar matrícula)
       - ACTIVO → COMPLETADO (al pagar todo)
    """
    try:
        payment = await payment_service.aprobar_pago(
            payment_id=id,
            admin_username=current_user.username
        )
        return await payment_service.enrich_payment_with_details(payment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/{id}/rechazar",
    response_model=PaymentResponse,
    summary="Rechazar Pago",
    responses={
        200: {"description": "Pago rechazado, estudiante puede ver motivo y reenviar"},
        400: {"description": "Error: pago ya procesado"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Pago no encontrado"}
    }
)
async def rechazar_pago(
    *,
    id: PydanticObjectId,
    rejection: PaymentRejection,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Rechazar un pago con motivo
    
    **Requiere:** Admin o SuperAdmin
    
    **Motivos comunes:**
    - "Voucher ilegible"
    - "Monto incorrecto"
    - "Transacción no encontrada en el banco"
    - "Voucher duplicado"
    
    El estudiante puede ver el motivo y subir un nuevo comprobante.
    """
    try:
        payment = await payment_service.rechazar_pago(
            payment_id=id,
            admin_username=current_user.username,
            motivo=rejection.motivo
        )
        return await payment_service.enrich_payment_with_details(payment)
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
    
    # Enriquecer lista
    enriched = []
    for p in payments:
        enriched.append(await payment_service.enrich_payment_with_details(p))
        
    return enriched


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
    
    # Enriquecer lista
    enriched = []
    for p in payments:
        enriched.append(await payment_service.enrich_payment_with_details(p))
        
    return enriched


@router.get(
    "/reportes/excel",
    summary="Generar Reporte Excel de Pagos",
    responses={
        200: {"description": "Archivo Excel generado", "content": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": {}}},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def generar_reporte_excel_pagos(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    current_user: User = Depends(require_admin)
):
    """
    Generar reporte Excel de pagos para cruce de datos
    
    **Requiere:** Admin o SuperAdmin
    
    **Filtros:**
    - `fecha_desde`: Fecha inicial (YYYY-MM-DD). Si no se especifica, toma el día actual
    - `fecha_hasta`: Fecha final (YYYY-MM-DD). Si no se especifica, igual a fecha_desde
    
    **Columnas del Excel:**
    1. Nombre del Estudiante
    2. Fecha
    3. Moneda (Bs)
    4. Monto
    5. Concepto
    6. Nº de Transacción
    7. Estado
    8. Progreso (ej: 7/12)
    
    **Retorna:** Archivo Excel para descargar
    """
    from datetime import datetime, date, timedelta
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from io import BytesIO
    from models.enrollment import Enrollment
    
    # Procesar fechas
    if not fecha_desde:
        fecha_desde = date.today().isoformat()
    if not fecha_hasta:
        fecha_hasta = fecha_desde
    
    try:
        fecha_desde_dt = datetime.fromisoformat(fecha_desde)
        fecha_hasta_dt = datetime.fromisoformat(fecha_hasta).replace(hour=23, minute=59, second=59)
    except:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")
    
    # Obtener pagos del rango de fechas
    payments = await Payment.find(
        Payment.fecha_subida >= fecha_desde_dt,
        Payment.fecha_subida <= fecha_hasta_dt
    ).sort("+fecha_subida").to_list()
    
    # Crear Excel
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte de Pagos"
    
    # Encabezados (Nuevo orden solicitado)
    headers = ["Nombre del Estudiante", "Fecha", "Moneda", "Monto", "Concepto", "Total Cuotas", "Nº de Transacción", "Estado", "Descripción"]
    ws.append(headers)
    
    # Estilo de encabezados
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    # Activar filtros en los encabezados
    ws.auto_filter.ref = ws.dimensions
    
    # Llenar datos
    for payment in payments:
        # Obtener estudiante
        student = await Student.get(payment.estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"
        
        # Obtener enrollment para sacar el Total de Cuotas
        total_cuotas = 0
        try:
            # Optimizacion: Usar proyección para solo traer cantidad_cuotas si es posible,
            # pero Enrollment.get() trae todo.
            enrollment = await Enrollment.get(payment.inscripcion_id)
            if enrollment:
                total_cuotas = enrollment.cantidad_cuotas
        except:
            pass
        
        # Preparar fila
        # Ajustar fecha a hora boliviana (UTC-4)
        fecha_bolivia = ""
        if payment.fecha_subida:
            fecha_bolivia_dt = payment.fecha_subida - timedelta(hours=4)
            fecha_bolivia = fecha_bolivia_dt.strftime("%Y-%m-%d %H:%M:%S")

        row = [
            nombre_estudiante,
            fecha_bolivia,
            "Bs",  # Moneda
            payment.cantidad_pago,
            payment.concepto or "",
            total_cuotas,
            payment.numero_transaccion or "",
            payment.estado_pago.value if payment.estado_pago else "",
            "" # Descripción vacía
        ]
        ws.append(row)
    
    # Ajustar ancho de columnas
    column_widths = [30, 20, 10, 15, 20, 15, 25, 15, 30]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    
    # Guardar en BytesIO
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    # Nombre del archivo
    filename = f"reporte_pagos_{fecha_desde}_{fecha_hasta}.xlsx"
    
    # Retornar archivo
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
