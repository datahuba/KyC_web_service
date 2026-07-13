# -*- coding: utf-8 -*-
"""
API de Pagos (Payments)
=======================

Endpoints para gestionar pagos de estudiantes, incluyendo 
rollback financiero y control de Caja/Bancos.
"""

from typing import List, Any, Optional
import asyncio
import re
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status
from pydantic import BaseModel, Field # IMPORTACIÓN REQUERIDA
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
    PaymentReversion,
    PaymentWithDetails
)
from services import payment_service
from beanie import PydanticObjectId
from beanie.operators import In
from bson import ObjectId
from fastapi.encoders import jsonable_encoder

from api.dependencies import require_cobranza, require_staff, require_superadmin, get_current_user, filtro_cursos_por_rol, puede_ver_economico
from schemas.common import PaginatedResponse, PaginationMeta
import math

router = APIRouter()


@router.post(
    "/",
    response_model=PaymentResponse,
    status_code=201,
    summary="Registrar Pago"
)
async def create_payment(
    *,
    inscripcion_id: str = Form(..., description="ID de la inscripción"),
    metodo_pago: str = Form(default="Transferencia", description="Transferencia, Depósito o Caja"),
    monto_comprobante: float = Form(...),
    concepto: Optional[str] = Form(None),
    
    # Datos opcionales según el método de pago
    numero_transaccion: Optional[str] = Form(None),
    remitente: Optional[str] = Form(None),
    banco: Optional[str] = Form(None),
    fecha_comprobante: Optional[str] = Form(None),
    cuenta_destino: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None, description="Comprobante (Opcional si es en Caja)"),
    
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Registrar un nuevo pago.
    Soporta pagos digitales (exige voucher/número) y pagos físicos (Caja).
    """
    from core.cloudinary_utils import upload_image, upload_pdf
    from schemas.payment import PaymentCreate
    
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )
    
    # 1. Validaciones rígidas según el Método de Pago
    if metodo_pago != "Caja":
        if not file:
            raise HTTPException(status_code=400, detail="El comprobante es obligatorio para transferencias y depósitos.")
        if not numero_transaccion:
            raise HTTPException(status_code=400, detail="El número de transacción es obligatorio para este método de pago.")
        if not banco:
            raise HTTPException(status_code=400, detail="Debe especificar el banco emisor.")
    
    comprobante_url = None
    
    try:
        # 2. Subida de Archivo a la Nube (si existe)
        if file:
            folder = f"payments/{current_user.id}"
            safe_transaction = (numero_transaccion or "caja_pago").replace(' ', '_').replace('/', '_')
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
        
        # 3. Ensamblaje del Payload Relajado
        payment_in = PaymentCreate(
            inscripcion_id=inscripcion_id,
            metodo_pago=metodo_pago,
            monto_comprobante=monto_comprobante,
            concepto=concepto,
            cantidad_pago=monto_comprobante, # Aseguramos que la cantidad refleje el monto
            numero_transaccion=numero_transaccion,
            remitente=remitente,
            banco=banco,
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
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Curso ID"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por Estudiante ID"),
    tipo_concepto: Optional[str] = Query(None, description="Filtrar por tipo de concepto (matricula, colegiatura)"),
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    
    if isinstance(current_user, User):
        # AUDITORÍA (CRÍTICO #1): sin este guard, cualquier rol autenticado
        # (docente, encargado_curso, coordinador) caía en ningún filtro y veía
        # TODOS los pagos/comprobantes del sistema. Solo el personal financiero
        # y de gestión académica tiene algún tipo de acceso a esta vista.
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado para ver pagos")

        # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve pagos de esos cursos.
        filtro_rol = filtro_cursos_por_rol(current_user)
        cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

        payments, total_count = await payment_service.get_all_payments(
            page=page,
            per_page=per_page,
            q=q,
            estado=estado,
            curso_id=curso_id,
            estudiante_id=estudiante_id,
            cursos_permitidos=cursos_permitidos,
            tipo_concepto=tipo_concepto
        )
        
        # Filtrado de RBAC (CPD vs Cobranza)
        filtered_payments = []
        for p in payments:
            concepto_lower = (p.concepto or "").lower().strip()
            is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
            if current_user.rol == "cpd" and not is_matricula:
                continue
            filtered_payments.append(p)
            
        payments = filtered_payments
        total_count = len(filtered_payments)
        
    elif isinstance(current_user, Student):
        all_payments = await payment_service.get_payments_by_student(
            student_id=current_user.id
        )
        if estado and estado != "Todos los estados":
            all_payments = [p for p in all_payments if p.estado_pago.value == estado]
            
        if tipo_concepto:
            if tipo_concepto == "matricula":
                all_payments = [p for p in all_payments if "matricula" in (p.concepto or "").lower() or "matrícula" in (p.concepto or "").lower()]
            elif tipo_concepto == "colegiatura":
                all_payments = [p for p in all_payments if "matricula" not in (p.concepto or "").lower() and "matrícula" not in (p.concepto or "").lower()]
            
        total_count = len(all_payments)
        start = (page - 1) * per_page
        end = start + per_page
        payments = all_payments[start:end]
    else:
        raise HTTPException(status_code=403, detail="No autorizado")
    
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    has_next = page < total_pages
    has_prev = page > 1
    
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
        # AUDITORÍA (CRÍTICO #1): mismo guard general que en list_payments.
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado para ver este pago")

        # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede ver pagos de otros cursos.
        filtro_rol = filtro_cursos_por_rol(current_user)
        if filtro_rol and payment.curso_id not in filtro_rol["curso_id"]["$in"]:
            raise HTTPException(status_code=403, detail="No tienes asignado el curso de este pago")

        concepto_lower = (payment.concepto or "").lower().strip()
        is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
        
        if current_user.rol == "cpd" and not is_matricula:
            raise HTTPException(status_code=403, detail="El rol CPD solo tiene acceso a pagos de concepto Matrícula")
    
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
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="Su rol no tiene permisos para aprobar pagos")
        
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede aprobar pagos de otros cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol and payment.curso_id not in filtro_rol["curso_id"]["$in"]:
        raise HTTPException(status_code=403, detail="No tienes asignado el curso de este pago")
        
    concepto_lower = (payment.concepto or "").lower().strip()
    is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
    
    if current_user.rol == "cpd" and not is_matricula:
        raise HTTPException(status_code=403, detail="El rol CPD solo puede aprobar pagos con concepto de Matrícula.")
        
    try:
        payment = await payment_service.aprobar_pago(
            payment_id=id,
            # ISSUE-R-PERFIL-GENERICO: nombre_visible en vez de username, para
            # que Cobranza (rol rotativo) quede identificado por función.
            admin_username=current_user.nombre_visible
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
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="Su rol no tiene permisos para rechazar pagos")
        
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede rechazar pagos de otros cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol and payment.curso_id not in filtro_rol["curso_id"]["$in"]:
        raise HTTPException(status_code=403, detail="No tienes asignado el curso de este pago")
        
    concepto_lower = (payment.concepto or "").lower().strip()
    is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
    
    if current_user.rol == "cpd" and not is_matricula:
        raise HTTPException(status_code=403, detail="El rol CPD solo puede rechazar pagos con concepto de Matrícula.")
        
    try:
        payment = await payment_service.rechazar_pago(
            payment_id=id,
            admin_username=current_user.nombre_visible,  # ISSUE-R-PERFIL-GENERICO
            motivo=rejection.motivo
        )
        return await payment_service.enrich_payment_with_details(payment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/{id}/anular",
    response_model=PaymentResponse,
    summary="Anular Pago (Rollback Financiero)"
)
async def anular_pago(
    *,
    id: PydanticObjectId,
    reversion: PaymentReversion,
    current_user: User = Depends(require_staff)
) -> Any:
    """
    ISSUE-P-CANALES: Anula un pago previamente aprobado y restaura las deudas del estudiante.
    Solo disponible para Cobranzas, Admin y SuperAdmin. El CPD no maneja flujos de caja.
    """
    if current_user.rol not in ["superadmin", "admin", "cobranza"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, 
            detail="Solo el personal financiero (Cobranzas/Administrador) puede realizar reversiones de caja."
        )

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede anular pagos de otros cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol:
        target_payment = await payment_service.get_payment(id)
        if not target_payment or target_payment.curso_id not in filtro_rol["curso_id"]["$in"]:
            raise HTTPException(status_code=403, detail="No tienes asignado el curso de este pago")
        
    try:
        payment = await payment_service.anular_pago(
            payment_id=id,
            admin_username=current_user.nombre_visible,  # ISSUE-R-PERFIL-GENERICO
            motivo=reversion.motivo
        )
        return await payment_service.enrich_payment_with_details(payment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete(
    "/{id}",
    summary="Eliminar Pago (Borrado Definitivo)"
)
async def eliminar_pago(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Elimina físicamente un pago de la base de datos. Operación destructiva y
    financiera, restringida a SUPERADMIN (mismo criterio que eliminar usuarios
    o cursos). Pensado para limpiar pagos de prueba o registros erróneos que no
    deben computar en la contabilidad.

    Tras el borrado se recalcula el saldo/estado de la inscripción desde los
    pagos APROBADOS restantes, para que los totales económicos queden
    consistentes.
    """
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    try:
        resultado = await payment_service.eliminar_pago(
            payment_id=id,
            admin_username=current_user.nombre_visible  # ISSUE-R-PERFIL-GENERICO
        )
        return resultado
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/enrollment/{enrollment_id}", response_model=List[PaymentResponse])
async def get_payments_by_enrollment(
    *,
    enrollment_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
            
    if isinstance(current_user, User):
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado para ver los pagos de esta inscripción")

        # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve inscripciones de esos cursos.
        filtro_rol = filtro_cursos_por_rol(current_user)
        if filtro_rol:
            from services import enrollment_service
            target_enrollment = await enrollment_service.get_enrollment(enrollment_id)
            if not target_enrollment or target_enrollment.curso_id not in filtro_rol["curso_id"]["$in"]:
                raise HTTPException(status_code=403, detail="No tienes asignado el curso de esta inscripción")
    
    payments = await payment_service.get_payments_by_enrollment(enrollment_id)
    
    filtered_payments = []
    for p in payments:
        if isinstance(current_user, User):
            concepto_lower = (p.concepto or "").lower().strip()
            is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
            if current_user.rol == "cpd" and not is_matricula:
                continue
        filtered_payments.append(p)
        
    return await payment_service.enrich_payments_with_details_bulk(filtered_payments)


@router.get("/enrollment/{enrollment_id}/resumen")
async def get_resumen_pagos(
    *,
    enrollment_id: PydanticObjectId,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    if isinstance(current_user, Student):
        from services import enrollment_service
        enrollment = await enrollment_service.get_enrollment(enrollment_id)
        if not enrollment:
            raise HTTPException(status_code=404, detail="Inscripción no encontrada")
        if enrollment.estudiante_id != current_user.id:
            raise HTTPException(status_code=403, detail="No tienes permiso")
            
    if isinstance(current_user, User):
        # AUDITORÍA (CRÍTICO #1): mismo guard general, además de la restricción específica de CPD.
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado para ver el resumen de pagos")

        if current_user.rol == "cpd":
            raise HTTPException(
                status_code=403,
                detail="El rol CPD tiene estrictamente prohibido visualizar flujos de caja y estados financieros"
            )

        # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve inscripciones de esos cursos.
        filtro_rol = filtro_cursos_por_rol(current_user)
        if filtro_rol:
            from services import enrollment_service
            target_enrollment = await enrollment_service.get_enrollment(enrollment_id)
            if not target_enrollment or target_enrollment.curso_id not in filtro_rol["curso_id"]["$in"]:
                raise HTTPException(status_code=403, detail="No tienes asignado el curso de esta inscripción")
    
    resumen = await payment_service.get_resumen_pagos_enrollment(enrollment_id)
    return resumen


@router.get("/pendientes/list", response_model=List[PaymentResponse])
async def get_payments_pendientes(
    *,
    current_user: User = Depends(require_staff)
) -> Any:
    if current_user.rol not in ["superadmin", "admin", "cpd", "cobranza"]:
        raise HTTPException(status_code=403, detail="No autorizado para listar pagos pendientes")

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve pendientes de esos cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    payments = await payment_service.get_payments_pendientes(cursos_permitidos=cursos_permitidos)
    
    filtered_payments = []
    for p in payments:
        concepto_lower = (p.concepto or "").lower().strip()
        is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
        
        if current_user.rol == "cpd":
            if is_matricula:
                filtered_payments.append(p)
        else:
            filtered_payments.append(p)
            
    return await payment_service.enrich_payments_with_details_bulk(filtered_payments)


def _parse_rango_fechas(fecha_desde: Optional[str], fecha_hasta: Optional[str]):
    from datetime import datetime, date
    if not fecha_desde:
        fecha_desde = date.today().isoformat()
    if not fecha_hasta:
        fecha_hasta = fecha_desde
    try:
        fecha_desde_dt = datetime.fromisoformat(fecha_desde)
        fecha_hasta_dt = datetime.fromisoformat(fecha_hasta).replace(hour=23, minute=59, second=59)
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato de fecha inválido. Usar YYYY-MM-DD")
    return fecha_desde, fecha_hasta, fecha_desde_dt, fecha_hasta_dt


@router.get(
    "/dashboard/resumen-economico",
    summary="Resumen Económico del Dashboard (Cobranza / Coordinador Financiero)"
)
async def get_resumen_economico_endpoint(
    *,
    current_user: User = Depends(require_staff)
) -> Any:
    """
    ISSUE-P-DASHBOARD-COBRANZA: tarjetas de resumen económico del dashboard.
    Incluye el ingreso por matrícula como dato contable (aunque Cobranza no
    apruebe matrículas, sí debe verlas recaudadas porque genera los informes
    económicos). Mismo conjunto de roles económicos que los reportes de caja.
    """
    # ISSUE-R-PERFIL-GENERICO: económico = superadmin/admin/cobranza/mae + coordinador FINANCIERO.
    if not puede_ver_economico(current_user):
        raise HTTPException(status_code=403, detail="No autorizado para ver el resumen económico")

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve su(s) curso(s).
    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    return await payment_service.get_resumen_economico(cursos_permitidos=cursos_permitidos)


@router.get(
    "/reportes/caja",
    summary="Reporte de Caja por Fechas (Tabla Interactiva)"
)
async def get_reporte_caja_endpoint(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso"),
    estado: Optional[str] = Query(None, description="Filtrar por estado del pago"),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=200),
    current_user: User = Depends(require_staff)
) -> Any:
    """
    ISSUE-P-REPORTE: tabla interactiva de ingresos filtrable por rango de
    fechas (fecha real del pago), curso y edición de programa. Devuelve la
    página solicitada + totales agregados de TODO el rango filtrado (no solo
    la página actual) para el resumen visual encima de la tabla.
    """
    # CPD excluido: los reportes de caja son económicos (regla del usuario:
    # "económico solo cobranza y el coordinador financiero"; CPD solo audita la
    # matrícula desde Gestión de Pagos, no ve reportes de caja).
    if not puede_ver_economico(current_user):
        raise HTTPException(status_code=403, detail="No autorizado para ver reportes de caja")

    _, _, fecha_desde_dt, fecha_hasta_dt = _parse_rango_fechas(fecha_desde, fecha_hasta)

    concepto_regex = None
    if current_user.rol == "cpd":
        concepto_regex = {"concepto": {"$regex": r"^matr[ií]cula$", "$options": "i"}}

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo ve su(s) curso(s).
    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    resultado = await payment_service.get_reporte_caja(
        fecha_desde_dt=fecha_desde_dt,
        fecha_hasta_dt=fecha_hasta_dt,
        page=page,
        per_page=per_page,
        curso_id=curso_id,
        estado=estado,
        concepto_regex=concepto_regex,
        cursos_permitidos=cursos_permitidos
    )

    total_pages = math.ceil(resultado["total_count"] / per_page) if resultado["total_count"] > 0 else 0
    enriched = await payment_service.enrich_payments_with_details_bulk(resultado["payments"])

    # Los pagos enriquecidos vienen de model_dump() y conservan campos PyObjectId
    # (inscripcion_id, estudiante_id, curso_id, _id) como objetos ObjectId. Este
    # endpoint devuelve un dict crudo (sin response_model que los coaccione, a
    # diferencia de list_payments), por lo que hay que serializarlos a string
    # explícitamente o FastAPI falla con PydanticSerializationError.
    return jsonable_encoder(
        {
            "data": enriched,
            "resumen": resultado["resumen"],
            "meta": PaginationMeta(
                page=page, limit=per_page, totalItems=resultado["total_count"], totalPages=total_pages,
                hasNextPage=(page < total_pages), hasPrevPage=(page > 1)
            )
        },
        custom_encoder={ObjectId: str}
    )


@router.get(
    "/reportes/excel",
    summary="Generar Reporte Excel de Pagos"
)
async def generar_reporte_excel_pagos(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso"),
    estado: Optional[str] = Query(None, description="Filtrar por estado del pago"),
    current_user: User = Depends(require_staff)
):
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from io import BytesIO
    from models.enrollment import Enrollment
    
    if not puede_ver_economico(current_user):
        raise HTTPException(status_code=403, detail="No autorizado para generar reportes")

    fecha_desde, fecha_hasta, fecha_desde_dt, fecha_hasta_dt = _parse_rango_fechas(fecha_desde, fecha_hasta)

    concepto_regex = None
    if current_user.rol == "cpd":
        concepto_regex = {"concepto": {"$regex": r"^matr[ií]cula$", "$options": "i"}}

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados solo exporta pagos de esos cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    criteria = payment_service._construir_filtro_reporte_caja(
        fecha_desde_dt, fecha_hasta_dt, curso_id=curso_id, estado=estado, cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criteria.update(concepto_regex)
    
    payments = await Payment.find(criteria).sort("-fecha_comprobante").to_list()
    
    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})
    curso_ids = list({p.curso_id for p in payments if p.curso_id})
    
    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    courses_task = Course.find(In(Course.id, curso_ids)).to_list()
    
    students, enrollments, courses = await asyncio.gather(students_task, enrollments_task, courses_task)
    
    students_map = {s.id: s for s in students}
    enrollments_map = {e.id: e for e in enrollments}
    courses_map = {c.id: c for c in courses}
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte de Caja"
    
    headers = ["Nombre del Estudiante", "Curso", "Método", "Fecha Comprobante", "Fecha Registro", "Moneda", "Monto", "Concepto", "Total Cuotas", "Nº Transacción", "Estado", "Motivo Reversión"]
    ws.append(headers)
    
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
    
    ws.auto_filter.ref = ws.dimensions
    
    from core.timezone_utils import to_bolivia_time
    for payment in payments:
        student = students_map.get(payment.estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"

        course = courses_map.get(payment.curso_id)
        nombre_curso = course.nombre_programa if course else "Sin curso"
        
        total_cuotas = 0
        enrollment = enrollments_map.get(payment.inscripcion_id)
        if enrollment:
            total_cuotas = enrollment.cantidad_cuotas
        
        fecha_comprobante_bolivia = to_bolivia_time(payment.fecha_comprobante) if payment.fecha_comprobante else "Sin registrar"
        fecha_registro_bolivia = to_bolivia_time(payment.fecha_subida)

        row = [
            nombre_estudiante,
            nombre_curso,
            payment.metodo_pago,
            fecha_comprobante_bolivia,
            fecha_registro_bolivia,
            "Bs",
            payment.cantidad_pago,
            payment.concepto or "",
            total_cuotas,
            payment.numero_transaccion or "Caja / S/N",
            payment.estado_pago.value if payment.estado_pago else "",
            payment.motivo_reversion or ""
        ]
        ws.append(row)
    
    column_widths = [30, 30, 15, 20, 20, 10, 15, 20, 15, 25, 15, 30]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)
    
    filename = f"reporte_caja_{fecha_desde}_{fecha_hasta}.xlsx"
    
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


class CajaDirectoRequest(BaseModel):
    estudiante_id: PydanticObjectId
    inscripcion_id: PydanticObjectId
    cantidad_pago: float = Field(..., gt=0, description="Monto cobrado en Caja (Bs)")
    concepto: Optional[str] = None
    numero_cuota: Optional[int] = None
    remitente: Optional[str] = None
    cuenta_destino: Optional[str] = None


@router.post(
    "/caja-directo",
    response_model=PaymentResponse,
    summary="Registrar Cobro Directo en Caja"
)
async def registrar_cobro_caja_directo(
    *,
    payload: CajaDirectoRequest,
    current_user: User = Depends(require_cobranza)
) -> Any:
    """
    Registrar un cobro físico directo en Caja para cualquier estudiante.
    Se crea directamente como APROBADO sin requerir la intervención o credenciales del estudiante.
    """
    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede cobrar en caja
    # para inscripciones fuera de sus cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol:
        from services import enrollment_service
        target_enrollment = await enrollment_service.get_enrollment(payload.inscripcion_id)
        if not target_enrollment or target_enrollment.curso_id not in filtro_rol["curso_id"]["$in"]:
            raise HTTPException(status_code=403, detail="No tienes asignado el curso de esta inscripción")

    try:
        payment = await payment_service.create_caja_directo_payment(
            estudiante_id=payload.estudiante_id,
            inscripcion_id=payload.inscripcion_id,
            cantidad_pago=payload.cantidad_pago,
            admin_username=current_user.nombre_visible,  # ISSUE-R-PERFIL-GENERICO
            concepto=payload.concepto,
            numero_cuota=payload.numero_cuota,
            remitente=payload.remitente,
            cuenta_destino=payload.cuenta_destino
        )
        return await payment_service.enrich_payment_with_details(payment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al registrar cobro directo: {str(e)}")