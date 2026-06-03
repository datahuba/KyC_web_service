# -*- coding: utf-8 -*-
"""
API de Pagos (Payments)
=======================

Endpoints para gestionar pagos de estudiantes.

Permisos:
---------
- POST /payments/: STUDENT (solo sus pagos)
- GET /payments/: STAFF (todos) / STUDENT (solo los suyos)
- GET /payments/{id}: STAFF / STUDENT (si es suyo)
- PUT /payments/{id}/aprobar: COBRANZAS, CPD, ADMIN, SUPERADMIN (según concepto)
- PUT /payments/{id}/rechazar: COBRANZAS, CPD, ADMIN, SUPERADMIN (según concepto)
- GET /payments/enrollment/{enrollment_id}: STAFF / STUDENT (si es suya)
- GET /payments/pendientes: COBRANZAS, CPD, ADMIN, SUPERADMIN (según concepto)
"""

from typing import List, Any, Optional
import asyncio
import re
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from models.course import Course
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
from beanie.operators import In

# Dependencias de seguridad
from api.dependencies import require_cobranza, require_staff, get_current_user

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=201,
    summary="Registrar Pago"
)
async def create_payment(
    *,
    file: UploadFile = File(..., description="Comprobante de pago (imagen JPG/PNG/WEBP o PDF)"),
    inscripcion_id: str = Form(..., description="ID de la inscripción"),
    numero_transaccion: str = Form(..., description="Número de transacción bancaria"),
    remitente: str = Form(...),
    banco: str = Form(...),
    monto_comprobante: float = Form(...),
    fecha_comprobante: str = Form(...),
    cuenta_destino: str = Form(...),
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Registrar un nuevo pago
    """
    from core.cloudinary_utils import upload_image, upload_pdf
    from schemas.payment import PaymentCreate
    
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )
    
    try:
        folder = f"payments/{current_user.id}"
        safe_transaction = numero_transaccion.replace(' ', '_').replace('/', '_')
        public_id = f"voucher_{safe_transaction}"
        
        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        pdf_type = "application/pdf"
        
        if file.content_type in image_types:
            comprobante_url = await upload_image(file, folder, public_id)
        elif file.content_type == pdf_type:
            comprobante_url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Formato no permitido: {file.content_type}. Use imagen o PDF"
            )
        
        payment_in = PaymentCreate(
            inscripcion_id=inscripcion_id,
            numero_transaccion=numero_transaccion,
            remitente=remitente,
            banco=banco,
            monto_comprobante=monto_comprobante,
            fecha_comprobante=fecha_comprobante,
            cuenta_destino=cuenta_destino,
            comprobante_url=comprobante_url
        )
        
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=current_user.id
        )
        
        return await payment_service.enrich_payment_with_details(payment)
        
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear pago: {str(e)}")


@router.get(
    "/",
    response_model=PaginatedResponse[PaymentResponse],
    summary="Listar Pagos"
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
    Listar pagos con paginación y filtros optimizados en lote (Bulk)
    """
    if isinstance(current_user, User):
        filters_dict = {}
        
        if q:
            escaped_q = re.escape(q.strip())
            regex_filter = {"$regex": escaped_q, "$options": "i"}

            matching_students = await Student.find({
                "$or": [
                    {"nombre": regex_filter},
                    {"email": regex_filter},
                    {"registro": regex_filter}
                ]
            }).to_list()

            matching_courses = await Course.find({
                "$or": [
                    {"nombre_programa": regex_filter},
                    {"codigo": regex_filter}
                ]
            }).to_list()

            student_ids = [student.id for student in matching_students if student.id]
            course_ids = [course.id for course in matching_courses if course.id]

            filters_dict["$or"] = [
                {"numero_transaccion": regex_filter},
                {"remitente": regex_filter},
                {"banco": regex_filter},
                {"estudiante_id": {"$in": student_ids}},
                {"curso_id": {"$in": course_ids}}
            ]
            
        if estado:
            filters_dict["estado_pago"] = estado
        if curso_id:
            filters_dict["curso_id"] = curso_id
        if estudiante_id:
            filters_dict["estudiante_id"] = estudiante_id
            
        if current_user.rol == "cpd":
            filters_dict["concepto"] = {"$regex": r"^matr[ií]cula$", "$options": "i"}
        elif current_user.rol == "cobranza":
            filters_dict["concepto"] = {"$not": {"$regex": r"^matr[ií]cula$", "$options": "i"}}
            
        query = Payment.find(filters_dict)
        total_count = await query.count()
        payments = await query.sort("-fecha_subida").skip((page - 1) * per_page).limit(per_page).to_list()
    
    elif isinstance(current_user, Student):
        all_payments = await payment_service.get_payments_by_student(
            student_id=current_user.id
        )
        if estado:
            all_payments = [p for p in all_payments if p.estado_pago == estado]
        total_count = len(all_payments)
        start = (page - 1) * per_page
        end = start + per_page
        payments = all_payments[start:end]
    else:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1
    
    # Optimizador: Enriquecimiento en LOTE ( Bulk Load )
    enriched_payments = await payment_service.enrich_payments_with_details_bulk(payments)
    
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
    summary="Ver Pago"
)
async def get_payment(
    *,
    id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """Ver detalles de un pago"""
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
    
    if isinstance(current_user, Student):
        if payment.estudiante_id != current_user.id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para ver este pago"
            )
            
    if isinstance(current_user, User):
        concepto_lower = (payment.concepto or "").lower().strip()
        is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
        
        if current_user.rol == "cpd" and not is_matricula:
            raise HTTPException(
                status_code=403,
                detail="El rol CPD solo tiene acceso a pagos de concepto Matrícula"
            )
        elif current_user.rol == "cobranza" and is_matricula:
            raise HTTPException(
                status_code=403,
                detail="El rol Cobranza no tiene acceso a pagos de concepto Matrícula"
            )
    
    return await payment_service.enrich_payment_with_details(payment)


@router.put(
    "/{id}/aprobar",
    response_model=PaymentResponse,
    summary="Aprobar Pago"
)
async def aprobar_pago(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_staff)
) -> Any:
    """Aprobar un pago"""
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="Su rol no tiene permisos para aprobar pagos")
        
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    concepto_lower = (payment.concepto or "").lower().strip()
    is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
    
    if current_user.rol == "cpd" and not is_matricula:
        raise HTTPException(
            status_code=403,
            detail="El rol CPD solo puede aprobar pagos con concepto de Matrícula."
        )
        
    if current_user.rol == "cobranza" and is_matricula:
        raise HTTPException(
            status_code=403,
            detail="El rol Cobranza no puede aprobar pagos con concepto de Matrícula."
        )
        
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
    summary="Rechazar Pago"
)
async def rechazar_pago(
    *,
    id: PydanticObjectId,
    rejection: PaymentRejection,
    current_user: User = Depends(require_staff)
) -> Any:
    """Rechazar un pago con motivo"""
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="Su rol no tiene permisos para rechazar pagos")
        
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")
        
    concepto_lower = (payment.concepto or "").lower().strip()
    is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
    
    if current_user.rol == "cpd" and not is_matricula:
        raise HTTPException(
            status_code=403,
            detail="El rol CPD solo puede rechazar pagos con concepto de Matrícula."
        )
        
    if current_user.rol == "cobranza" and is_matricula:
        raise HTTPException(
            status_code=403,
            detail="El rol Cobranza no puede rechazar pagos con concepto de Matrícula."
        )
        
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
    """Obtener todos los pagos de una inscripción"""
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
            
    if isinstance(current_user, User):
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado")
    
    payments = await payment_service.get_payments_by_enrollment(enrollment_id)
    
    filtered_payments = []
    for p in payments:
        if isinstance(current_user, User):
            concepto_lower = (p.concepto or "").lower().strip()
            is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
            if current_user.rol == "cpd" and not is_matricula:
                continue
            if current_user.rol == "cobranza" and is_matricula:
                continue
        filtered_payments.append(p)
        
    # Enriquecer lote en milisegundos con resolución Bulk
    return await payment_service.enrich_payments_with_details_bulk(filtered_payments)


@router.get("/enrollment/{enrollment_id}/resumen")
async def get_resumen_pagos(
    *,
    enrollment_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """Obtener resumen de pagos de una inscripción"""
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
            
    if isinstance(current_user, User) and current_user.rol == "cpd":
        raise HTTPException(
            status_code=403,
            detail="El rol CPD tiene estrictamente prohibido visualizar flujos de caja y estados financieros"
        )
    
    resumen = await payment_service.get_resumen_pagos_enrollment(enrollment_id)
    return resumen


@router.get("/pendientes/list", response_model=List[PaymentResponse])
async def get_payments_pendientes(
    *,
    current_user: User = Depends(require_staff)
) -> Any:
    """Obtener todos los pagos pendientes de aprobación"""
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="No autorizado para listar pagos pendientes")
        
    payments = await payment_service.get_payments_pendientes()
    
    filtered_payments = []
    for p in payments:
        concepto_lower = (p.concepto or "").lower().strip()
        is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
        
        if current_user.rol == "cpd":
            if is_matricula:
                filtered_payments.append(p)
        elif current_user.rol == "cobranza":
            if not is_matricula:
                filtered_payments.append(p)
        else:
            filtered_payments.append(p)
            
    return await payment_service.enrich_payments_with_details_bulk(filtered_payments)


@router.get(
    "/reportes/excel",
    summary="Generar Reporte Excel de Pagos"
)
async def generar_reporte_excel_pagos(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    current_user: User = Depends(require_staff)
):
    """
    Generar reporte Excel de pagos (Optimizado contra Timeouts y cuellos de botella)
    """
    from datetime import datetime, date
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from io import BytesIO
    from models.enrollment import Enrollment
    
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza", "mae"]:
        raise HTTPException(status_code=403, detail="No autorizado para generar reportes")
        
    if not fecha_desde:
        fecha_desde = date.today().isoformat()
    if not fecha_hasta:
        fecha_hasta = fecha_desde
    
    try:
        fecha_desde_dt = datetime.fromisoformat(fecha_desde)
        fecha_hasta_dt = datetime.fromisoformat(fecha_hasta).replace(hour=23, minute=59, second=59)
    except:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")
        
    criteria = {
        "fecha_subida": {
            "$gte": fecha_desde_dt,
            "$lte": fecha_hasta_dt
        }
    }
    
    if current_user.rol == "cpd":
        criteria["concepto"] = {"$regex": r"^matr[ií]cula$", "$options": "i"}
    elif current_user.rol == "cobranza":
        criteria["concepto"] = {"$not": {"$regex": r"^matr[ií]cula$", "$options": "i"}}
    
    payments = await Payment.find(criteria).sort("-fecha_subida").to_list()
    
    # --- PREFETCH BULK DE ALTO RENDIMIENTO (1 SOLA CONSULTA DE RED) ---
    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})
    
    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    
    students, enrollments = await asyncio.gather(students_task, enrollments_task)
    
    students_map = {s.id: s for s in students}
    enrollments_map = {e.id: e for e in enrollments}
    # ------------------------------------------------------------------
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte de Pagos"
    
    headers = ["Nombre del Estudiante", "Fecha", "Moneda", "Monto", "Concepto", "Total Cuotas", "Nº de Transacción", "Estado", "Descripción"]
    ws.append(headers)
    
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    ws.auto_filter.ref = ws.dimensions
    
    for payment in payments:
        student = students_map.get(payment.estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"
        
        total_cuotas = 0
        enrollment = enrollments_map.get(payment.inscripcion_id)
        if enrollment:
            total_cuotas = enrollment.cantidad_cuotas
        
        from core.timezone_utils import to_bolivia_time
        fecha_bolivia = to_bolivia_time(payment.fecha_subida)

        row = [
            nombre_estudiante,
            fecha_bolivia,
            "Bs",
            payment.cantidad_pago,
            payment.concepto or "",
            total_cuotas,
            payment.numero_transaccion or "",
            payment.estado_pago.value if payment.estado_pago else "",
            ""
        ]
        ws.append(row)
    
    column_widths = [30, 20, 10, 15, 20, 15, 25, 15, 30]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    filename = f"reporte_pagos_{fecha_desde}_{fecha_hasta}.xlsx"
    
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
