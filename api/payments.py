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
from datetime import datetime
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
    # F-COBRANZA-026 (2026-07-22): Kevin: "el sistema no debe dejar que se suba
    # una solicitud de pago sin el comprobante no importa que tipo de pago sea
    # caja o todo lo demas". El comprobante es OBLIGATORIO para todos los
    # metodos, incluyendo Caja.
    file: UploadFile = File(..., description="Comprobante obligatorio (imagen o PDF)"),

    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Registrar un nuevo pago.
    Soporta pagos digitales (exige voucher/número) y pagos físicos (Caja).
    F-COBRANZA-026: el comprobante es OBLIGATORIO para todos los metodos.
    """
    from core.cloudinary_utils import upload_image, upload_pdf
    from schemas.payment import PaymentCreate

    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden subir comprobantes de pago"
        )

    # 1. Validaciones rígidas según el Método de Pago
    # F-COBRANZA-026: el comprobante es obligatorio SIEMPRE (no opcional para Caja)
    if not file:
        raise HTTPException(status_code=400, detail="El comprobante es obligatorio (imagen o PDF) para todos los métodos de pago.")
    if metodo_pago != "Caja":
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


@router.post(
    "/by-staff",
    response_model=PaymentResponse,
    summary="Registrar Pago en nombre de Estudiante (Staff: cobranza/admin/superadmin)"
)
async def create_payment_by_staff(
    *,
    inscripcion_id: str = Form(..., description="ID de la inscripción"),
    estudiante_id: str = Form(..., description="ID del estudiante (para asociar el comprobante en Cloudinary)"),
    metodo_pago: str = Form(default="Transferencia", description="Transferencia, Depósito o Caja"),
    monto_comprobante: float = Form(..., gt=0, description="Monto del pago en BOB (>0)"),
    concepto: Optional[str] = Form(None, description="Concepto (opcional; si vacío, backend calcula glosa detallada)"),

    numero_transaccion: Optional[str] = Form(None),
    remitente: Optional[str] = Form(None),
    banco: Optional[str] = Form(None),
    fecha_comprobante: Optional[str] = Form(None),
    cuenta_destino: Optional[str] = Form(None),
    # F-COBRANZA-026 (2026-07-22): comprobante obligatorio para todos los métodos
    file: UploadFile = File(..., description="Comprobante obligatorio (imagen o PDF)"),

    current_user: User = Depends(require_staff)
) -> Any:
    """
    F-COBRANZA-017 (2026-07-22): cuando el estudiante no pudo subir su
    comprobante desde su perfil (por problemas técnicos, falta de acceso,
    etc.), el personal de COBRANZA puede REGISTRAR el pago completo en
    nombre del estudiante desde la gestion de pagos.

    Decisión Joel 2026-07-22 22:25: el botón vive en la parte superior
    derecha de /app/payments (no en el menú de 3 puntos de cada pago).
    Roles permitidos: superadmin, admin, cobranza. NO cpd, NO coordinador,
    NO encargado_curso.

    Diferencias con `create_payment` (estudiante):
    - Acepta `estudiante_id` (no lo toma del current_user).
    - El pago nace APROBADO (auto-aprobación como F-COBRANZA-004).
    - `verificado_por` = nombre del usuario staff.
    - Glosa: si el frontend manda placeholder genérico ("Matrícula" /
      "Módulo"), se regenera con detalle de módulos cubiertos.
    - F-COBRANZA-026: comprobante OBLIGATORIO (no opcional para Caja).
    """
    from core.cloudinary_utils import upload_image, upload_pdf
    from schemas.payment import PaymentCreate

    # RBAC: solo roles económicos (no cpd, no coordinador, no docente)
    if current_user.rol not in ["superadmin", "admin", "cobranza"]:
        raise HTTPException(
            status_code=403,
            detail="Solo cobranza/admin/superadmin pueden registrar pagos en nombre de estudiantes."
        )

    # F-COBRANZA-026: comprobante obligatorio siempre
    if not file:
        raise HTTPException(status_code=400, detail="El comprobante es obligatorio (imagen o PDF) para todos los métodos de pago.")
    if metodo_pago != "Caja":
        if not numero_transaccion:
            raise HTTPException(status_code=400, detail="El número de transacción es obligatorio para este método.")
        if not banco:
            raise HTTPException(status_code=400, detail="Debe especificar el banco emisor.")

    comprobante_url = None
    if file:
        folder = f"payments/{estudiante_id}"
        if numero_transaccion:
            public_id = f"voucher_{numero_transaccion}"
        else:
            public_id = f"staff_upload_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

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
        metodo_pago=metodo_pago,
        monto_comprobante=monto_comprobante,
        concepto=concepto,
        cantidad_pago=monto_comprobante,
        numero_transaccion=numero_transaccion,
        remitente=remitente,
        banco=banco,
        fecha_comprobante=fecha_comprobante,
        cuenta_destino=cuenta_destino,
        comprobante_url=comprobante_url,
    )

    try:
        # F-COBRANZA-017: el pago se crea APROBADO al registrarlo desde
        # cobranza (no pasa por el flujo pendiente → revisar → aprobar).
        # Esto es consistente con F-COBRANZA-004 (auto-aprobación cuando
        # el estudiante sube su comprobante). Joel decidió 22:25 que sea
        # automático para no demorar al estudiante.
        #
        # F-COBRANZA-034 (2026-07-22): skip_ownership_check=True porque el
        # check de "la inscripcion pertenece al estudiante" es solo para
        # el endpoint del estudiante (evitar que un estudiante pague la
        # inscripcion de otro). El staff (cobranza/admin/superadmin) está
        # autorizado a registrar pagos en nombre de cualquier estudiante
        # del sistema. Bug reportado por Lic. Sandra Zabala: el check
        # enrollment.estudiante_id != student_id siempre fallaba porque
        # estudiante_id llega como string del Form y enrollment.estudiante_id
        # es PydanticObjectId.
        from beanie import PydanticObjectId as _POI
        student_oid = estudiante_id if isinstance(estudiante_id, _POI) else _POI(estudiante_id)
        payment = await payment_service.create_payment(
            payment_in=payment_in,
            student_id=student_oid,
            auto_approve=True,
            approved_by=current_user.username,
            skip_ownership_check=True,
        )

        # F-COBRANZA-014: el saldo del enrollment se actualiza dentro de
        # create_payment (vía actualizar_saldo_enrollment). No hace falta
        # hacer nada más aquí.

        return await payment_service.enrich_payment_with_details(payment)

    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al registrar pago por staff: {str(e)}")


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


@router.post(
    "/{id}/upload-by-encargado",
    response_model=PaymentResponse,
    summary="Subir Comprobante de Pago (Encargado de Programa)"
)
async def upload_comprobante_by_encargado(
    *,
    id: PydanticObjectId,
    file: UploadFile = File(..., description="Comprobante de pago (imagen o PDF)"),
    numero_transaccion: Optional[str] = Form(None, description="Número de transacción (opcional)"),
    remitente: Optional[str] = Form(None, description="Remitente del pago (opcional)"),
    fecha_comprobante: Optional[str] = Form(None, description="Fecha del comprobante (YYYY-MM-DD, opcional)"),
    current_user: User = Depends(require_staff)
) -> Any:
    """
    F-COBRANZA-011 (2026-07-21): el personal de COBRANZA puede subir el
    comprobante de pago del estudiante cuando este no puede hacerlo por
    sí mismo (problemas técnicos, falta de acceso, etc.).

    Roles permitidos: SUPERADMIN, ADMIN, COBRANZA.
    Roles NO permitidos: CPD, COORDINADOR, ENCARGADO_CURSO, DOCENTE, ESTUDIANTE.

    Decisión de Joel (2026-07-21 20:30): "debería subirlo el de cobranzas, y
    que esté en el modal de gestión de pagos [...] no esté en el del encargado
    porque sería confuncion por ahora". Encargado de programa NO sube: lo hace
    cobranza. La UI expone este endpoint solo en /app/payments con el botón
    "Subir comprobante del estudiante".

    Diferencias vs `create_payment`:
    - El pago YA EXISTE (creado por el estudiante con o sin comprobante).
    - Solo se actualiza el comprobante_url y datos opcionales.
    - Se registra en auditoría con `subido_por=cobranza_id`.
    - El estudiante ve en su perfil quién subió el comprobante.
    - Al subir, el pago ya estaba APROBADO (F-COBRANZA-004), así que el saldo
      del enrollment NO se vuelve a tocar.
    """
    # 1. Validar rol: SOLO personal financiero (cobranza) y administrativos.
    roles_permitidos = ["superadmin", "admin", "cobranza"]
    if current_user.rol not in roles_permitidos:
        raise HTTPException(
            status_code=403,
            detail=f"Su rol ({current_user.rol}) no puede subir comprobantes en nombre de estudiantes. Solo cobranza, admin y superadmin están autorizados."
        )

    # 2. Obtener el pago
    payment = await payment_service.get_payment(id)
    if not payment:
        raise HTTPException(status_code=404, detail="Pago no encontrado")

    # 3. ISSUE-P-SEGMENTACION: encargado con cursos_asignados solo puede
    #    subir comprobantes de SUS cursos asignados.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol and payment.curso_id not in filtro_rol["curso_id"]["$in"]:
        raise HTTPException(
            status_code=403,
            detail="No tienes asignado el curso de este pago"
        )

    # 4. Validar que el pago no esté anulado
    if payment.estado_pago == EstadoPago.ANULADO:
        raise HTTPException(
            status_code=400,
            detail="No se puede subir comprobante a un pago anulado."
        )

    # 5. Subir el archivo a Cloudinary
    from core.cloudinary_utils import upload_image, upload_pdf
    folder = f"payments/{payment.estudiante_id}"
    safe_transaction = (numero_transaccion or f"encargado_{current_user.id}").replace(' ', '_').replace('/', '_')
    public_id = f"voucher_{safe_transaction}"

    image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    pdf_type = "application/pdf"

    try:
        if file.content_type in image_types:
            comprobante_url = await upload_image(file, folder, public_id)
        elif file.content_type == pdf_type:
            from core.cloudinary_utils import upload_pdf
            comprobante_url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Tipo de archivo no soportado: {file.content_type}. Use JPEG, PNG, WEBP o PDF."
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al subir el archivo: {str(e)}"
        )

    # 6. Actualizar el pago
    from datetime import datetime
    from core.timezone_utils import utcnow_naive
    try:
        update_dict = {
            "comprobante_url": comprobante_url,
            "updated_at": utcnow_naive()
        }
        if numero_transaccion:
            update_dict["numero_transaccion"] = numero_transaccion
        if remitente:
            update_dict["remitente"] = remitente
        if fecha_comprobante:
            try:
                update_dict["fecha_comprobante"] = datetime.strptime(fecha_comprobante, "%Y-%m-%d")
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="fecha_comprobante debe tener formato YYYY-MM-DD"
                )

        await Payment.find_one({"_id": id}).update({"$set": update_dict})

        # Re-leer el pago actualizado
        payment = await payment_service.get_payment(id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar el pago: {str(e)}")

    # 7. Audit log
    await payment_service._registrar_auditoria_financiera(
        accion="UPLOAD COMPROBANTE BY ENCARGADO",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=current_user.nombre_visible,
        detalles=f"Comprobante subido por {current_user.nombre_visible} (rol={current_user.rol}) en nombre del estudiante. URL={comprobante_url[:80]}..."
    )

    # 8. Notificar al estudiante
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Comprobante subido por tu encargado",
            mensaje=f"El encargado {current_user.nombre_visible} subió el comprobante de tu pago de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}'.",
            tipo_alerta="info",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de comprobante subido: {str(e)}")

    return await payment_service.enrich_payment_with_details(payment)


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
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por estudiante (F-COBRANZA-003)"),
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

    F-COBRANZA-003 (2026-07-21): filtro opcional por estudiante_id.
    Permite ver todos los pagos de un estudiante específico en el rango.
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
        estudiante_id=estudiante_id,  # F-COBRANZA-003
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
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por estudiante (F-COBRANZA-003)"),
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
        fecha_desde_dt, fecha_hasta_dt, curso_id=curso_id, estudiante_id=estudiante_id, estado=estado, cursos_permitidos=cursos_permitidos
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
    
    headers = ["Nombre del Estudiante", "C.I.", "Curso", "Método", "Fecha Comprobante", "Fecha Registro", "Moneda", "Monto", "Concepto", "Total Cuotas", "Nº Transacción", "Estado", "Motivo Reversión"]
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
        # F-COBRANZA-042 (2026-07-22): Carnet de Identidad del estudiante.
        # Prioriza `carnet_identidad`, fallback a `registro` (compatibilidad con
        # estudiantes pre-F-027 que no tienen CI separado del registro).
        estudiante_ci = ""
        if student:
            estudiante_ci = (getattr(student, "carnet_identidad", None) or "").strip() or \
                            (getattr(student, "registro", None) or "").strip()

        course = courses_map.get(payment.curso_id)
        # F-COBRANZA-022 (2026-07-22): Joel pidio usar el codigo del programa
        # (DIPL-IA-2026) en vez del nombre largo en el XLSX, para que el reporte
        # sea mas compacto y matchee con el codigo que se ve en el sistema.
        nombre_curso = course.codigo if course and course.codigo else (course.nombre_programa if course else "Sin curso")

        total_cuotas = 0
        enrollment = enrollments_map.get(payment.inscripcion_id)
        if enrollment:
            total_cuotas = enrollment.cantidad_cuotas

        fecha_comprobante_bolivia = to_bolivia_time(payment.fecha_comprobante) if payment.fecha_comprobante else "Sin registrar"
        fecha_registro_bolivia = to_bolivia_time(payment.fecha_subida)

        # F-COBRANZA-005 (2026-07-21): los pagos anulados se exportan con monto
        # negativo en la columna "Monto", de modo que la SUMA al pie del Excel
        # (o la fórmula SUM del usuario) coincida con el extracto bancario
        # sin necesidad de restar manualmente.
        monto_exportar = payment.cantidad_pago
        if payment.estado_pago == EstadoPago.ANULADO and monto_exportar > 0:
            monto_exportar = -monto_exportar

        row = [
            nombre_estudiante,
            estudiante_ci,
            nombre_curso,
            payment.metodo_pago,
            fecha_comprobante_bolivia,
            fecha_registro_bolivia,
            "Bs",
            monto_exportar,
            payment.concepto or "",
            total_cuotas,
            payment.numero_transaccion or "Caja / S/N",
            payment.estado_pago.value if payment.estado_pago else "",
            payment.motivo_reversion or ""
        ]
        ws.append(row)

    column_widths = [30, 12, 18, 15, 20, 20, 10, 15, 20, 15, 25, 15, 30]
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


# ========================================================================
# F-COBRANZA-043 (2026-07-22): Reporte de Caja - Export PDF
# ========================================================================
# Kevin: "se deberia pooder tener esa opcion de descargar como pdf en el mismo
# modelo que creaste me gusto ... obviamente debe ser los mismos datos qu el
# excel que exportas mas lo delc arte que te dije ahorita" (las 4 tarjetas
# KPI: Cantidad, Total Aprobado, Total Pendiente, Total Anulado).
#
# Genera el PDF en el backend con reportlab para mantener consistencia con
# el XLSX que ya se genera acá. Landscape A4 con:
#   1. Encabezado: titulo + rango de fechas + filtros aplicados
#   2. Bloque de 4 tarjetas KPI (Cantidad, Aprobado, Pendiente, Anulado)
#   3. Tabla de pagos (mismas columnas que el XLSX)
#   4. Pie de pagina con totales
@router.get(
    "/reportes/caja/pdf",
    summary="Generar Reporte PDF de Caja (mismos datos que XLSX + tarjetas KPI)",
)
async def generar_reporte_pdf_caja(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por estudiante (F-COBRANZA-003)"),
    estado: Optional[str] = Query(None, description="Filtrar por estado del pago"),
    current_user: User = Depends(require_staff)
):
    from fastapi.responses import StreamingResponse
    from io import BytesIO
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )

    if not puede_ver_economico(current_user):
        raise HTTPException(status_code=403, detail="No autorizado para generar reportes")

    fecha_desde_str, fecha_hasta_str, fecha_desde_dt, fecha_hasta_dt = _parse_rango_fechas(fecha_desde, fecha_hasta)

    concepto_regex = None
    if current_user.rol == "cpd":
        concepto_regex = {"concepto": {"$regex": r"^matr[ií]cula$", "$options": "i"}}

    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    # Traer TODOS los pagos del rango (sin paginar) para el PDF completo.
    criteria = payment_service._construir_filtro_reporte_caja(
        fecha_desde_dt, fecha_hasta_dt, curso_id=curso_id, estudiante_id=estudiante_id, estado=estado, cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criteria.update(concepto_regex)

    # Sin limite: PDF debe incluir todos. Si en el futuro hay miles, agregar
    # parametro de paginacion o limite.
    from models.payment import Payment
    cursor = Payment.find(criteria).sort("-fecha_subida")
    payments_all = await cursor.to_list()

    # Enriquecer (nombre, C.I., curso, etc.) igual que el XLSX
    enriched = await payment_service.enrich_payments_with_details_bulk(payments_all)

    # Calcular resumen (4 tarjetas KPI)
    # enriched viene como list[dict] (de model_dump en enrich_payments_with_details_bulk),
    # así que usamos .get() directamente.
    def _g(p, key, default=None):
        return p.get(key, default) if isinstance(p, dict) else getattr(p, key, default)

    cantidad_pagos = len(enriched)
    total_aprobado = sum(float(_g(p, "cantidad_pago", 0)) for p in enriched if _g(p, "estado_pago") == "aprobado")
    total_pendiente = sum(float(_g(p, "cantidad_pago", 0)) for p in enriched if _g(p, "estado_pago") == "pendiente")
    total_anulado = sum(abs(float(_g(p, "cantidad_pago", 0))) for p in enriched if _g(p, "estado_pago") in ("anulado", "rechazado"))

    # Construir el PDF
    pdf_file = BytesIO()
    doc = SimpleDocTemplate(
        pdf_file,
        pagesize=landscape(A4),
        leftMargin=10*mm, rightMargin=10*mm,
        topMargin=10*mm, bottomMargin=10*mm,
        title="Reporte de Caja - KYC DataHub",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleStyle", parent=styles["Title"], fontSize=18, textColor=colors.HexColor("#0c4a6e"), spaceAfter=2*mm)
    subtitle_style = ParagraphStyle("SubtitleStyle", parent=styles["Normal"], fontSize=10, textColor=colors.HexColor("#475569"), spaceAfter=4*mm)

    elements = []
    elements.append(Paragraph("Reporte de Caja", title_style))
    periodo_texto = f"Período: {fecha_desde_str or 'inicio'} → {fecha_hasta_str or 'hoy'}"
    if curso_id:
        from models.course import Course
        c = await Course.get(curso_id)
        if c:
            periodo_texto += f"  |  Curso: {c.codigo or c.nombre_programa}"
    if estudiante_id:
        from models.student import Student
        s = await Student.get(estudiante_id)
        if s:
            periodo_texto += f"  |  Estudiante: {s.nombre}"
    if estado:
        periodo_texto += f"  |  Estado: {estado}"
    elements.append(Paragraph(periodo_texto, subtitle_style))

    # 4 tarjetas KPI (mismo modelo visual que el dashboard)
    kpi_data = [
        ["CANTIDAD DE PAGOS", "TOTAL APROBADO", "TOTAL PENDIENTE", "TOTAL ANULADO"],
        [str(cantidad_pagos), f"Bs. {total_aprobado:,.2f}", f"Bs. {total_pendiente:,.2f}", f"Bs. {total_anulado:,.2f}"],
    ]
    kpi_table = Table(kpi_data, colWidths=[70*mm]*4, rowHeights=[9*mm, 16*mm])
    kpi_table.setStyle(TableStyle([
        # Header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#f1f5f9")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#64748b")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        # Values
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 1), (0, 1), 28),  # Cantidad
        ("FONTSIZE", (1, 1), (-1, 1), 18),  # Montos
        ("TEXTCOLOR", (0, 1), (0, 1), colors.HexColor("#0f172a")),
        ("TEXTCOLOR", (1, 1), (1, 1), colors.HexColor("#15803d")),  # Aprobado verde
        ("TEXTCOLOR", (2, 1), (2, 1), colors.HexColor("#ca8a04")),  # Pendiente amarillo
        ("TEXTCOLOR", (3, 1), (3, 1), colors.HexColor("#b91c1c")),  # Anulado rojo
        ("ALIGN", (0, 1), (-1, 1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # Borders
        ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
    ]))
    elements.append(kpi_table)
    elements.append(Spacer(1, 5*mm))

    # Tabla de pagos (mismas columnas que el XLSX, sin "Motivo Reversión" para
    # ahorrar espacio; solo se muestra si el filtro de estado es anulado/rechazado)
    headers = ["Nombre del Estudiante", "C.I.", "Curso", "Método", "Fecha", "Monto", "Concepto", "Nº Transacción", "Estado"]
    rows = [headers]
    from core.timezone_utils import to_bolivia_time
    for p in enriched:
        def _g2(key, default=None):
            return p.get(key, default) if isinstance(p, dict) else getattr(p, key, default)
        student = _g2("estudiante") or {}
        course = _g2("course") or {}
        ci = (student.get("carnet_identidad") or student.get("registro") or "").strip()
        # to_bolivia_time retorna STRING ya formateado (ej "22/07/2026 14:30").
        # Si retorna None (no hay fecha), mostrar "Sin fecha".
        fecha = _g2("fecha_subida")
        if fecha:
            fecha_str = to_bolivia_time(fecha) if hasattr(fecha, 'isoformat') else str(fecha)
        else:
            fecha_str = "Sin fecha"
        monto = float(_g2("cantidad_pago", 0))
        estado_pago = _g2("estado_pago", "")
        # Anulados: mostrar como negativo (mismo criterio que el XLSX)
        if estado_pago == "anulado" and monto > 0:
            monto = -monto
        rows.append([
            Paragraph(str(student.get("nombre") or "Sin nombre")[:40], styles["BodyText"]),
            ci or "—",
            course.get("codigo") or course.get("nombre_programa") or "Sin curso",
            _g2("metodo_pago") or "",
            fecha_str,
            f"{monto:,.2f}",
            Paragraph(str(_g2("concepto") or "")[:50], styles["BodyText"]),
            str(_g2("numero_transaccion") or "Caja / S/N")[:18],
            estado_pago,
        ])

    data_table = Table(rows, repeatRows=1, colWidths=[
        50*mm, 18*mm, 25*mm, 20*mm, 22*mm, 18*mm, 55*mm, 25*mm, 18*mm,
    ])
    data_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0c4a6e")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, 0), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#e2e8f0")),
    ]))
    elements.append(data_table)

    # Pie de pagina (lo agrega automaticamente reportlab al render)

    doc.build(elements)
    pdf_file.seek(0)

    filename = f"reporte_caja_{fecha_desde_str or 'inicio'}_{fecha_hasta_str or 'hoy'}.pdf"
    return StreamingResponse(
        pdf_file,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ========================================================================
# F-COBRANZA-023 (2026-07-22): Reporte de Caja - Formato Extracto Bancario
# ========================================================================
# Joel pidio que el reporte de caja tenga formato estilo estado de cuenta
# bancaria (como el Banco Bisa que mando como ejemplo). Estructura:
#   - Encabezado: Banco, Cuenta, Periodo, Saldo Inicial
#   - Tabla: Fecha | Comprobante | Concepto | DEBITOS | CREDITOS | Saldo
#   - Totales: Total Operaciones, Total Debitos, Total Creditos, Saldo Final
#
# Reglas contables (lo que Joel definio):
#   - CREDITOS: pagos APROBADOS (incluye los que abandonan/congelan, porque
#     su dinero SI entro al sistema). NO se filtran por estado del enrollment.
#   - DEBITOS: pagos ANULADOS o RECHAZADOS (salen del sistema).
#   - PENDIENTES: NO se muestran (estan en limbo, no son ingreso ni egreso).
#   - Saldo Final = Saldo Inicial + Total Creditos - Total Debitos
#
# El endpoint NO modifica nada, solo lee y genera XLSX con el formato pedido.

@router.get(
    "/reportes/caja/extracto-bancario",
    summary="Reporte de Caja Formato Extracto Bancario (Debitos/Creditos)",
)
async def get_extracto_bancario(
    *,
    fecha_desde: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso"),
    estudiante_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por estudiante"),
    current_user: User = Depends(require_staff)
):
    """
    F-COBRANZA-023: Genera un XLSX con formato extracto bancario (estilo
    Banco Bisa que Joel paso como ejemplo) para el reporte de caja.

    Reglas contables:
    - CREDITOS = pagos aprobados (incluye abandonos/congelados, su dinero si entro)
    - DEBITOS  = pagos anulados o rechazados (salen del sistema)
    - PENDIENTES NO se muestran (estan en limbo)
    """
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from io import BytesIO
    from models.enrollment import Enrollment
    from core.timezone_utils import to_bolivia_time, format_fecha

    if not puede_ver_economico(current_user):
        raise HTTPException(status_code=403, detail="No autorizado para ver reportes de caja")

    fecha_desde_str, fecha_hasta_str, fecha_desde_dt, fecha_hasta_dt = _parse_rango_fechas(fecha_desde, fecha_hasta)

    concepto_regex = None
    if current_user.rol == "cpd":
        concepto_regex = {"concepto": {"$regex": r"^matr[ií]cula$", "$options": "i"}}

    filtro_rol = filtro_cursos_por_rol(current_user)
    cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

    criteria = payment_service._construir_filtro_reporte_caja(
        fecha_desde_dt, fecha_hasta_dt,
        curso_id=curso_id, estudiante_id=estudiante_id,
        estado=None,  # No filtrar por estado: queremos todos para mostrar debitos y creditos
        cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criteria.update(concepto_regex)

    # Solo nos interesan aprobado, anulado, rechazado (NO pendientes)
    criteria["estado_pago"] = {"$in": ["aprobado", "anulado", "rechazado"]}

    # Ordenar por fecha de comprobante (ascendente para el saldo acumulado)
    payments = await Payment.find(criteria).sort("+fecha_comprobante").to_list()

    # Cargar info relacionada
    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})
    curso_ids = list({p.curso_id for p in payments if p.curso_id})

    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    courses_task = Course.find(In(Course.id, curso_ids)).to_list()

    students, enrollments, courses = await asyncio.gather(students_task, enrollments_task, courses_task)
    students_map = {s.id: s for s in students}
    courses_map = {c.id: c for c in courses}

    # Calcular resumen previo (todos los aprobados sin filtro de fecha, para
    # tener el "Saldo Inicial" = todo lo cobrado ANTES del rango)
    criterios_saldo_inicial = payment_service._construir_filtro_reporte_caja(
        None, fecha_desde_dt,
        curso_id=curso_id, estudiante_id=estudiante_id,
        estado=None, cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criterios_saldo_inicial.update(concepto_regex)
    criterios_saldo_inicial["estado_pago"] = "aprobado"
    pagos_previos_aprobados = await Payment.find(criterios_saldo_inicial).to_list()
    saldo_inicial = sum(p.cantidad_pago for p in pagos_previos_aprobados)

    # Calcular debitos previos (anulados antes del rango)
    criterios_deb_prev = payment_service._construir_filtro_reporte_caja(
        None, fecha_desde_dt,
        curso_id=curso_id, estudiante_id=estudiante_id,
        estado=None, cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criterios_deb_prev.update(concepto_regex)
    criterios_deb_prev["estado_pago"] = {"$in": ["anulado", "rechazado"]}
    pagos_previos_deb = await Payment.find(criterios_deb_prev).to_list()
    debitos_previos = sum(p.cantidad_pago for p in pagos_previos_deb)
    saldo_inicial -= debitos_previos  # ajustar por débitos previos

    # Generar XLSX
    wb = Workbook()
    ws = wb.active
    ws.title = "Extracto Bancario"

    # ======= ESTILOS =======
    title_font = Font(bold=True, size=14, color="1F4E78")
    subtitle_font = Font(bold=True, size=11, color="1F4E78")
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="1F4E78", end_color="1F4E78", fill_type="solid")
    debito_font = Font(color="C00000", bold=True)  # rojo
    credito_font = Font(color="00B050", bold=True)  # verde
    total_font = Font(bold=True, size=11)
    total_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    thin = Side(border_style="thin", color="A0A0A0")
    cell_border = Border(top=thin, left=thin, right=thin, bottom=thin)

    # ======= ENCABEZADO (estilo estado de cuenta) =======
    ws.merge_cells("A1:F1")
    ws["A1"] = "ESTADO DE CUENTA - SISTEMA KyC DataHub"
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")

    ws.merge_cells("A2:F2")
    ws["A2"] = "Banco UAGRM - Postgrado"
    ws["A2"].font = subtitle_font
    ws["A2"].alignment = Alignment(horizontal="center", vertical="center")

    # Info de cuenta
    info_rows = [
        ("Cuenta:", "POSTGRADO-UAGRM"),
        ("Titular:", "UAGRM - Direccion de Posgrado"),
        ("Moneda:", "Bs (Bolivianos)"),
        ("Período:", f"{fecha_desde_str or '(inicio)'} al {fecha_hasta_str or '(hoy)'}"),
        ("Generado:", format_fecha(datetime.now(), "%Y-%m-%d %H:%M", fallback="")),
    ]
    for i, (label, value) in enumerate(info_rows, start=4):
        ws.cell(row=i, column=1, value=label).font = Font(bold=True)
        ws.merge_cells(start_row=i, start_column=2, end_row=i, end_column=6)
        ws.cell(row=i, column=2, value=value)

    # Saldo inicial
    row_saldo = 4 + len(info_rows)
    ws.cell(row=row_saldo, column=1, value="SALDO INICIAL:").font = Font(bold=True, size=11)
    ws.merge_cells(start_row=row_saldo, start_column=2, end_row=row_saldo, end_column=6)
    saldo_cell = ws.cell(row=row_saldo, column=2, value=saldo_inicial)
    saldo_cell.font = Font(bold=True, size=11)
    saldo_cell.number_format = '#,##0.00 "Bs"'

    # ======= TABLA DE MOVIMIENTOS =======
    header_row = row_saldo + 2
    headers = ["Fecha", "Comprobante", "Concepto / Descripción", "Débitos", "Créditos", "Saldo"]
    for col, h in enumerate(headers, start=1):
        cell = ws.cell(row=header_row, column=col, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.border = cell_border

    # Cuerpo: una fila por pago
    saldo = saldo_inicial
    total_creditos = 0.0
    total_debitos = 0.0
    row = header_row + 1
    for p in payments:
        student = students_map.get(p.estudiante_id)
        nombre = student.nombre if student and student.nombre else "Sin nombre"
        course = courses_map.get(p.curso_id)
        codigo_curso = course.codigo if course and course.codigo else (course.nombre_programa if course else "")
        fecha = format_fecha(p.fecha_comprobante, "%Y-%m-%d", fallback="Sin fecha")
        comprobante = p.numero_transaccion or p.id or "S/N"
        # Construir concepto
        if p.estado_pago == EstadoPago.ANULADO:
            tipo_mov = "ANULACIÓN"
        elif p.estado_pago == EstadoPago.RECHAZADO:
            tipo_mov = "RECHAZO"
        else:
            tipo_mov = "PAGO"
        # Concepto: tipo + concepto del pago + nombre estudiante + código curso
        concepto_str = f"{tipo_mov} {p.concepto or 'Pago'} - {nombre}"
        if codigo_curso:
            concepto_str += f" ({codigo_curso})"
        if p.detalle:
            concepto_str += f" | {p.detalle}"
        # Débitos / Créditos
        if p.estado_pago in (EstadoPago.ANULADO, EstadoPago.RECHAZADO):
            debito = p.cantidad_pago
            credito = 0.0
            total_debitos += debito
            saldo -= debito
        else:  # aprobado
            debito = 0.0
            credito = p.cantidad_pago
            total_creditos += credito
            saldo += credito

        # Escribir fila
        ws.cell(row=row, column=1, value=fecha).border = cell_border
        ws.cell(row=row, column=2, value=str(comprobante)[:30]).border = cell_border
        ws.cell(row=row, column=3, value=concepto_str[:120]).border = cell_border
        c4 = ws.cell(row=row, column=4, value=debito if debito > 0 else None)
        c4.border = cell_border
        c4.number_format = '#,##0.00'
        if debito > 0:
            c4.font = debito_font
        c5 = ws.cell(row=row, column=5, value=credito if credito > 0 else None)
        c5.border = cell_border
        c5.number_format = '#,##0.00'
        if credito > 0:
            c5.font = credito_font
        c6 = ws.cell(row=row, column=6, value=saldo)
        c6.border = cell_border
        c6.number_format = '#,##0.00 "Bs"'
        c6.font = Font(bold=True)

        row += 1

    # Fila vacía
    row += 1

    # ======= TOTALES (estilo estado de cuenta) =======
    total_row = row
    ws.cell(row=total_row, column=1, value="TOTAL OPERACIONES:").font = total_font
    ws.merge_cells(start_row=total_row, start_column=1, end_row=total_row, end_column=3)
    ws.cell(row=total_row, column=4, value=len(payments)).font = total_font
    ws.cell(row=total_row, column=4).alignment = Alignment(horizontal="right")
    ws.cell(row=total_row, column=4).fill = total_fill

    row += 1
    ws.cell(row=row, column=1, value="TOTAL DÉBITOS:").font = total_font
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    c = ws.cell(row=row, column=4, value=total_debitos)
    c.font = Font(bold=True, color="C00000")
    c.number_format = '#,##0.00 "Bs"'
    c.fill = total_fill

    row += 1
    ws.cell(row=row, column=1, value="TOTAL CRÉDITOS:").font = total_font
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    c = ws.cell(row=row, column=5, value=total_creditos)
    c.font = Font(bold=True, color="00B050")
    c.number_format = '#,##0.00 "Bs"'
    c.fill = total_fill

    row += 1
    ws.cell(row=row, column=1, value="SALDO FINAL:").font = Font(bold=True, size=12)
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=3)
    c = ws.cell(row=row, column=6, value=saldo)
    c.font = Font(bold=True, size=12)
    c.number_format = '#,##0.00 "Bs"'
    c.fill = total_fill

    # Anchos de columna
    column_widths = [12, 18, 60, 14, 14, 16]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width

    # Pie de pagina
    row += 3
    ws.cell(row=row, column=1, value=(
        "NOTA: Los CREDITOS incluyen todos los pagos aprobados (incluso si el "
        "estudiante abandona o congela despues, su dinero SI entro al sistema). "
        "Los DEBITOS son pagos anulados o rechazados (salen del sistema). "
        "Los pagos PENDIENTES no se muestran (estan en revision)."
    )).font = Font(italic=True, size=9, color="606060")
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=6)
    ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[row].height = 35

    # Guardar
    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    filename = f"extracto_bancario_{fecha_desde_str or 'inicio'}_{fecha_hasta_str or 'hoy'}.xlsx"
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
    summary="Registrar Cobro Directo en Caja (requiere comprobante)"
)
async def registrar_cobro_caja_directo(
    *,
    # F-COBRANZA-026 (2026-07-22): comprobante obligatorio también para caja-directo
    file: UploadFile = File(..., description="Comprobante obligatorio (foto del recibo/factura)"),
    payload: str = Form(..., description="CajaDirectoRequest serializado como JSON string"),
    current_user: User = Depends(require_cobranza)
) -> Any:
    """
    Registrar un cobro físico directo en Caja para cualquier estudiante.
    Se crea directamente como APROBADO sin requerir la intervención o credenciales del estudiante.

    F-COBRANZA-026: ahora requiere comprobante obligatorio (foto del recibo/factura).
    """
    import json
    from core.cloudinary_utils import upload_image, upload_pdf

    # Parsear payload JSON
    try:
        payload_dict = json.loads(payload)
        payload_obj = CajaDirectoRequest(**payload_dict)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Payload inválido: {e}")

    # F-COBRANZA-026: validar comprobante
    if not file:
        raise HTTPException(status_code=400, detail="El comprobante es obligatorio (foto del recibo/factura)")

    # Subir comprobante a Cloudinary
    try:
        from models.student import Student
        estudiante = await Student.get(payload_obj.estudiante_id)
        folder = f"payments/{payload_obj.estudiante_id}"
        public_id = f"caja_{payload_obj.inscripcion_id}_{int(datetime.now().timestamp())}"

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
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al subir comprobante: {e}")

    # ISSUE-P-SEGMENTACION: Cobranza con cursos_asignados no puede cobrar en caja
    # para inscripciones fuera de sus cursos.
    filtro_rol = filtro_cursos_por_rol(current_user)
    if filtro_rol:
        from services import enrollment_service
        target_enrollment = await enrollment_service.get_enrollment(payload_obj.inscripcion_id)
        if not target_enrollment or target_enrollment.curso_id not in filtro_rol["curso_id"]["$in"]:
            raise HTTPException(status_code=403, detail="No tienes asignado el curso de esta inscripción")

    try:
        payment = await payment_service.create_caja_directo_payment(
            estudiante_id=payload_obj.estudiante_id,
            inscripcion_id=payload_obj.inscripcion_id,
            cantidad_pago=payload_obj.cantidad_pago,
            admin_username=current_user.nombre_visible,  # ISSUE-R-PERFIL-GENERICO
            concepto=payload_obj.concepto,
            numero_cuota=payload_obj.numero_cuota,
            remitente=payload_obj.remitente,
            cuenta_destino=payload_obj.cuenta_destino,
            comprobante_url=comprobante_url,  # F-COBRANZA-026
        )
        return await payment_service.enrich_payment_with_details(payment)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al registrar cobro directo: {str(e)}")


# ========================================================================
# F-COBRANZA-016 (2026-07-21): Exportar lista de pagos a XLSX (no CSV)
# ========================================================================
# Joel pidió: "se mejoren todas las exportaciones y sean tablas, no CSV".
# Este endpoint devuelve un Excel formateado con todos los pagos que
# matcheen los filtros. Reemplaza al `downloadCSV()` que el frontend
# generaba manualmente con un Blob.

@router.get(
    "/export/excel",
    summary="Exportar lista de pagos a XLSX (reemplaza al CSV)",
)
async def export_payments_excel(
    *,
    q: Optional[str] = Query(None, description="Búsqueda por transacción o comprobante"),
    estado: Optional[str] = Query(None, description="Filtrar por estado"),
    curso_id: Optional[PydanticObjectId] = Query(None),
    estudiante_id: Optional[PydanticObjectId] = Query(None),
    tipo_concepto: Optional[str] = Query(None),
    current_user: User | Student = Depends(get_current_user)
):
    """
    F-COBRANZA-016: exporta TODOS los pagos que matcheen los filtros como
    un archivo .xlsx con formato de tabla (no CSV). Mismas reglas de RBAC
    que GET /payments/.

    Columnas:
      ID, Fecha Comprobante, Fecha Subida, Estudiante, Registro, Curso,
      Concepto, Módulo, Monto (Bs), Método, Banco, Remitente,
      Nº Transacción, Estado, Comprobante (URL)
    """
    from fastapi.responses import StreamingResponse
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from io import BytesIO
    from models.enrollment import Enrollment
    from core.timezone_utils import format_fecha

    if isinstance(current_user, User):
        if current_user.rol not in ["superadmin", "admin", "mae", "cpd", "cobranza"]:
            raise HTTPException(status_code=403, detail="No autorizado para exportar pagos")

        filtro_rol = filtro_cursos_por_rol(current_user)
        cursos_permitidos = filtro_rol["curso_id"]["$in"] if filtro_rol else None

        # Traemos hasta 5,000 pagos (suficiente para producción; si crece, paginar).
        payments, _ = await payment_service.get_all_payments(
            page=1, per_page=5000, q=q, estado=estado, curso_id=curso_id,
            estudiante_id=estudiante_id, cursos_permitidos=cursos_permitidos,
            tipo_concepto=tipo_concepto,
        )

        # Filtrar RBAC adicional (CPD solo ve matrículas, etc.) — replica
        # la lógica de list_payments.
        filtered = []
        for p in payments:
            concepto_lower = (p.concepto or "").lower().strip()
            is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
            if current_user.rol == "cpd" and not is_matricula:
                continue
            filtered.append(p)
        payments = filtered
    else:
        # Estudiante solo puede exportar SUS pagos
        payments = await payment_service.get_payments_by_student(current_user.id)
        if estado and estado != "Todos los estados":
            payments = [p for p in payments if p.estado_pago.value == estado]
        if tipo_concepto:
            if tipo_concepto == "matricula":
                payments = [p for p in payments if "matricula" in (p.concepto or "").lower() or "matrícula" in (p.concepto or "").lower()]
            elif tipo_concepto == "colegiatura":
                payments = [p for p in payments if "matricula" not in (p.concepto or "").lower() and "matrícula" not in (p.concepto or "").lower()]

    # Enriquecer con estudiante + curso para el Excel
    enriched = await payment_service.enrich_payments_with_details_bulk(payments)
    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})
    curso_ids = list({p.curso_id for p in payments if p.curso_id})

    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    courses_task = Course.find(In(Course.id, curso_ids)).to_list()
    students, enrollments, courses = await asyncio.gather(students_task, enrollments_task, courses_task)
    students_map = {s.id: s for s in students}
    courses_map = {c.id: c for c in courses}

    wb = Workbook()
    ws = wb.active
    ws.title = "Pagos"

    headers = [
        "ID", "Fecha Comprobante", "Fecha Subida", "Estudiante", "C.I.",
        "Curso", "Concepto", "Detalle (Desglose)", "Nº Módulo", "Tipo Movimiento",
        "Débito (Bs)", "Crédito (Bs)", "Monto (Bs)", "Método", "Banco",
        "Remitente", "Nº Transacción", "Estado", "Comprobante URL",
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF")
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for p in enriched:
        student = students_map.get(p.get("estudiante_id"))
        student_name = student.nombre if student and student.nombre else "Sin nombre"
        # F-COBRANZA-036 (2026-07-22): Sandra pidio columna C.I. en el reporte
        # de caja. Usamos el campo `estudiante_ci` que enrich_payments_with_details_bulk
        # ya lleno (prioriza carnet_identidad; si no hay, cae al registro).
        student_ci = p.get("estudiante_ci") or ""
        course = courses_map.get(p.get("curso_id"))
        # F-COBRANZA-022 (2026-07-22): Joel pidio usar el codigo del programa
        # (DIPL-IA-2026) en vez del nombre largo en el XLSX, para que el reporte
        # sea mas compacto y matchee con el codigo que se ve en el sistema.
        course_name = (course.codigo if course and course.codigo else (course.nombre_programa if course and course.nombre_programa else "Sin curso"))
        modulo = p.get("numero_cuota") or "N/A"

        row = [
            str(p.get("_id", "")),
            format_fecha(p.get("fecha_comprobante"), "%Y-%m-%d", fallback="Sin registrar"),
            format_fecha(p.get("fecha_subida"), "%Y-%m-%d %H:%M", fallback=""),
            student_name,
            student_ci,
            course_name,
            p.get("concepto") or "",
            p.get("detalle") or "",  # F-COBRANZA-020: desglose separado
            modulo,
            # F-COBRANZA-037 (2026-07-22): Sandra pidio columnas Debito/Credito
            # para ver la diferencia entre pagos y anulaciones. Los rechazos
            # tambien van a Debito. Los pagos aprobados van a Credito.
            p.get("tipo_movimiento") or "PAGO",
            float(p.get("debito") or 0),
            float(p.get("credito") or 0),
            p.get("cantidad_pago", 0),
            p.get("metodo_pago") or "Transferencia",
            p.get("banco") or "Caja UAGRM",
            p.get("remitente") or "",
            p.get("numero_transaccion") or "S/N",
            # F-COBRANZA-016 fix (2026-07-22): el campo se llama `estado` en
            # el dict enriquecido (devuelto por enrich_payments_with_details_bulk
            # que ya lo convierte a .value del enum). Antes usaba `estado_pago`
            # que devolvía el enum crudo y se mostraba como "EstadoPago.APROBADO"
            # en el XLSX. Bug detectado por Joel al abrir el Excel descargado.
            p.get("estado") or "",
            p.get("comprobante_url") or "",
        ]
        ws.append(row)

    # Auto-width básico
    column_widths = [28, 14, 18, 30, 12, 28, 22, 10, 12, 14, 18, 22, 18, 14, 50]
    for i, width in enumerate(column_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width
    ws.auto_filter.ref = ws.dimensions
    ws.freeze_panes = "A2"

    excel_file = BytesIO()
    wb.save(excel_file)
    excel_file.seek(0)

    filename = f"pagos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        excel_file,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )