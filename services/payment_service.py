"""
Servicio de Pagos (Payments)
============================

Lógica de negocio para pagos, incluyendo soporte de métodos en Caja,
Auditoría y Algoritmo de Prorrateo.
"""

from typing import List, Optional
import asyncio
from datetime import datetime, timedelta
from models.payment import Payment
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.enums import EstadoPago
from schemas.payment import PaymentCreate
from beanie import PydanticObjectId
from beanie.operators import In, Or
from beanie.exceptions import RevisionIdWasChanged
from services import enrollment_service

# ISSUE-P-REVERSION: ventana en la que el banco puede revertir una transferencia ya aprobada
VENTANA_REVERSION_HORAS = 48


def _calcular_en_ventana_reversion(payment: Payment) -> bool:
    """
    True si el pago fue aprobado por transferencia y todavía está dentro de las
    48h en que el banco podría revertir la operación. Es un valor calculado en
    tiempo de respuesta (depende de "ahora"), nunca se persiste en base de datos.
    """
    if payment.estado_pago != EstadoPago.APROBADO:
        return False
    if "transferencia" not in (payment.metodo_pago or "").lower():
        return False
    if not payment.fecha_verificacion:
        return False
    limite = payment.fecha_verificacion + timedelta(hours=VENTANA_REVERSION_HORAS)
    return datetime.utcnow() < limite

# ========================================================================
# MOTOR DE AUDITORÍA FINANCIERA
# ========================================================================
async def _registrar_auditoria_financiera(
    accion: str,
    payment_id: PydanticObjectId,
    estudiante_id: PydanticObjectId,
    monto: float,
    admin_username: str,
    detalles: str
):
    """
    Función auxiliar para registrar los movimientos financieros en un log inmutable.
    """
    try:
        print(
            f"[AUDIT TRAIL] [{datetime.utcnow()}] ACCIÓN: {accion} | "
            f"ADMIN: {admin_username} | PAGO_ID: {payment_id} | "
            f"ESTUDIANTE_ID: {estudiante_id} | MONTO: Bs. {monto} | "
            f"DETALLE: {detalles}"
        )
    except Exception as e:
        print(f"Error guardando auditoría: {str(e)}")


async def enrich_payment_with_details(payment: Payment) -> dict:
    payment_dict = payment.model_dump(by_alias=True)
    
    student = await Student.get(payment.estudiante_id)
    nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"
    
    from core.timezone_utils import to_bolivia_time
    fecha = to_bolivia_time(payment.fecha_subida)
    created_at_bolivia = to_bolivia_time(payment.created_at)
    updated_at_bolivia = to_bolivia_time(payment.updated_at)
    
    total_cuotas = 0
    try:
        enrollment = await enrollment_service.get_enrollment(payment.inscripcion_id)
        if enrollment:
            total_cuotas = enrollment.cantidad_cuotas
    except:
        total_cuotas = 0
    
    payment_dict.update({
        "nombre_estudiante": nombre_estudiante,
        "fecha": fecha,
        "moneda": "Bs",
        "monto": payment.cantidad_pago,
        "estado": payment.estado_pago.value if payment.estado_pago else "",
        "total_cuotas": total_cuotas,
        "created_at": created_at_bolivia,
        "updated_at": updated_at_bolivia,
        "en_ventana_reversion": _calcular_en_ventana_reversion(payment)  # ISSUE-P-REVERSION
    })
    
    return payment_dict


async def enrich_payments_with_details_bulk(payments: List[Payment]) -> List[dict]:
    if not payments:
        return []

    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})

    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    
    students, enrollments = await asyncio.gather(students_task, enrollments_task)

    students_map = {s.id: s for s in students}
    enrollments_map = {e.id: e for e in enrollments}

    from core.timezone_utils import to_bolivia_time

    enriched_list = []
    for payment in payments:
        p_dict = payment.model_dump(by_alias=True)
        
        student = students_map.get(payment.estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"
        
        enrollment = enrollments_map.get(payment.inscripcion_id)
        total_cuotas = enrollment.cantidad_cuotas if enrollment else 0

        p_dict.update({
            "nombre_estudiante": nombre_estudiante,
            "fecha": to_bolivia_time(payment.fecha_subida),
            "moneda": "Bs",
            "monto": payment.cantidad_pago,
            "estado": payment.estado_pago.value if payment.estado_pago else "",
            "total_cuotas": total_cuotas,
            "created_at": to_bolivia_time(payment.created_at),
            "updated_at": to_bolivia_time(payment.updated_at),
            "en_ventana_reversion": _calcular_en_ventana_reversion(payment)  # ISSUE-P-REVERSION
        })
        enriched_list.append(p_dict)

    return enriched_list


async def get_next_pending_payment(enrollment_id: PydanticObjectId) -> dict:
    enrollment = await enrollment_service.get_enrollment(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")

    pagos_activos = await Payment.find(
        Payment.inscripcion_id == enrollment_id,
        Or(
            Payment.estado_pago == EstadoPago.PENDIENTE,
            Payment.estado_pago == EstadoPago.APROBADO
        )
    ).to_list()
    
    conceptos_cubiertos = {
        (p.concepto, p.numero_cuota) for p in pagos_activos
    }
    
    if enrollment.costo_matricula > 0:
        if ("Matrícula", None) not in conceptos_cubiertos:
            return {
                "concepto": "Matrícula",
                "numero_cuota": None,
                "monto_sugerido": enrollment.costo_matricula
            }
    
    if enrollment.cantidad_cuotas > 0:
        monto_cuota = enrollment.calcular_monto_cuota()
        for i in range(1, enrollment.cantidad_cuotas + 1):
            if (f"Cuota {i}", i) not in conceptos_cubiertos:
                return {
                    "concepto": f"Cuota {i}",
                    "numero_cuota": i,
                    "monto_sugerido": monto_cuota
                }
                
    return None


async def create_payment(
    payment_in: PaymentCreate,
    student_id: PydanticObjectId
) -> Payment:
    """
    Crear un nuevo pago. Soporta pagos digitales o pagos físicos en CAJA (sin voucher).
    """
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment_in.inscripcion_id} no encontrada")
    
    if enrollment.estudiante_id != student_id:
        raise ValueError(
            "No puedes crear un pago para una inscripción que no te pertenece"
        )

    if payment_in.metodo_pago != "Caja" and payment_in.numero_transaccion:
        existing_transaction = await Payment.find_one(
            Payment.numero_transaccion == payment_in.numero_transaccion,
            Payment.estado_pago != EstadoPago.RECHAZADO
        )
        
        if existing_transaction:
            raise ValueError(
                f"El número de transacción bancaria '{payment_in.numero_transaccion}' ya "
                f"ha sido registrado en el sistema y se encuentra '{existing_transaction.estado_pago}'. "
                "No se permiten comprobantes duplicados."
            )
    
    next_payment = await get_next_pending_payment(payment_in.inscripcion_id)
    if not next_payment:
         raise ValueError("Esta inscripción ya tiene todos los pagos en proceso o aprobados.")

    concepto_final = payment_in.concepto if payment_in.concepto else next_payment["concepto"]
    cuota_final = payment_in.numero_cuota if payment_in.numero_cuota else next_payment["numero_cuota"]
    monto_real = payment_in.monto_comprobante if payment_in.monto_comprobante else payment_in.cantidad_pago

    # AUDITORÍA (ALTO #4): sin este control, un pago (aún PENDIENTE, antes de
    # que cobranza lo apruebe) podía exceder por completo el saldo pendiente
    # real de la inscripción. actualizar_saldo_enrollment clampa
    # saldo_pendiente a 0 al aprobar, pero total_pagado sigue creciendo sin
    # límite -- "Pagado > Total" quedaba permanente sin ningún mecanismo de
    # crédito/devolución. Se permite un pequeño margen (1 Bs) para redondeos
    # legítimos del estudiante.
    if monto_real > enrollment.saldo_pendiente + 1.0:
        raise ValueError(
            f"El monto reportado (Bs. {monto_real}) supera el saldo pendiente de la inscripción "
            f"(Bs. {enrollment.saldo_pendiente}). Verifica el monto antes de registrar el pago."
        )

    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,
        estudiante_id=enrollment.estudiante_id,
        curso_id=enrollment.curso_id,
        
        metodo_pago=payment_in.metodo_pago,
        concepto=concepto_final,
        cantidad_pago=monto_real,
        numero_cuota=cuota_final,
        
        numero_transaccion=payment_in.numero_transaccion,
        comprobante_url=payment_in.comprobante_url,
        remitente=payment_in.remitente,
        banco=payment_in.banco,
        monto_comprobante=monto_real,
        fecha_comprobante=payment_in.fecha_comprobante,
        cuenta_destino=payment_in.cuenta_destino,
        
        estado_pago=EstadoPago.PENDIENTE
    )
    
    await payment.insert()
    
    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # BUG CORREGIDO (reportado por el usuario: pagos/inscripciones no llegaban
    # a las notificaciones correctas): esto SIEMPRE notificaba solo a
    # COBRANZA, sin importar el concepto. Pero el propio sistema bloquea a
    # Cobranza de aprobar pagos con concepto "Matrícula" (solo CPD puede,
    # ver aprobar_pago en api/payments.py) -- un pago de Matrícula pendiente
    # nunca le llegaba a quien realmente debía aprobarlo (CPD), y Cobranza
    # recibía una notificación de un pago que ni siquiera podía gestionar.
    # Ahora se notifica al rol correcto según el concepto, con el mismo
    # criterio (regex "matr[ií]cula") usado en el resto de endpoints de
    # pagos para mantener consistencia.
    try:
        from models.user import User
        from models.enums import UserRole
        from services.notification_service import create_notification
        
        student_obj = await Student.get(student_id)
        student_name = student_obj.nombre if student_obj and student_obj.nombre else "Estudiante registrado"

        concepto_lower = (concepto_final or "").lower().strip()
        is_matricula = "matricula" in concepto_lower or "matrícula" in concepto_lower
        rol_revisor = UserRole.CPD if is_matricula else UserRole.COBRANZA

        from beanie.operators import Or
        revisores = await User.find(
            User.activo == True,
            Or(
                User.rol == rol_revisor,
                # Admin/Superadmin pueden aprobar cualquier pago sin importar
                # el concepto (ver aprobar_pago en api/payments.py), así que
                # también deben enterarse siempre, no solo el rol específico.
                User.rol == UserRole.ADMIN,
                User.rol == UserRole.SUPERADMIN
            )
        ).to_list()
        
        for revisor in revisores:
            await create_notification(
                destinatario_id=revisor.id,
                tipo_destinatario="user",
                titulo="Nuevo Pago Pendiente",
                mensaje=f"El estudiante {student_name} ({student_obj.registro if student_obj else ''}) ha subido un comprobante de Bs. {monto_real} por el concepto '{concepto_final}'.",
                tipo_alerta="info",
                ruta="/app/payments",
                referencia_tipo="payment",
                referencia_id=payment.id
            )
    except Exception as e:
        print(f"Error al enviar notificación de pago pendiente: {str(e)}")

    return payment


async def get_payment(id: PydanticObjectId) -> Optional[Payment]:
    return await Payment.get(id)


async def get_payments_by_student(student_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.estudiante_id == student_id).sort("-fecha_subida").to_list()


async def get_payments_by_enrollment(enrollment_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.inscripcion_id == enrollment_id).sort("-fecha_subida").to_list()


async def get_payments_by_course(course_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.curso_id == course_id).sort("-fecha_subida").to_list()


async def get_all_payments(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    curso_id: Optional[PydanticObjectId] = None,
    estudiante_id: Optional[PydanticObjectId] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
) -> tuple[List[Payment], int]:
    """
    cursos_permitidos (ISSUE-P-SEGMENTACION): si se provee (no None), restringe
    los resultados únicamente a pagos de esos cursos. Reutiliza el mismo patrón
    de segmentación que ENCARGADO_CURSO en enrollment_service.get_all_enrollments.
    """
    query_dict = {}
    
    if estado and estado != "Todos los estados":
        query_dict["estado_pago"] = estado

    if estudiante_id:
        query_dict["estudiante_id"] = estudiante_id

    if curso_id:
        enrollments = await Enrollment.find(Enrollment.curso_id == curso_id).to_list()
        enrollment_ids = [e.id for e in enrollments]
        query_dict["inscripcion_id"] = {"$in": enrollment_ids}

    if cursos_permitidos is not None:
        query_dict["curso_id"] = {"$in": cursos_permitidos}
        
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        
        matching_students = await Student.find(
            Or(
                Student.nombre == regex_pattern,
                Student.registro == regex_pattern,
                Student.carnet == regex_pattern,
                Student.email == regex_pattern
            )
        ).to_list()
        
        matching_student_ids = [s.id for s in matching_students]

        query_dict["$or"] = [
            {"numero_transaccion": regex_pattern},
            {"concepto": regex_pattern},
            {"remitente": regex_pattern},
            {"banco": regex_pattern},
            {"estudiante_id": {"$in": matching_student_ids}}
        ]
    
    total_count = await Payment.find(query_dict).count()
    skip = (page - 1) * per_page
    payments = await Payment.find(query_dict).sort("-fecha_subida").skip(skip).limit(per_page).to_list()
    
    return payments, total_count


async def get_payments_pendientes(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
) -> List[Payment]:
    """cursos_permitidos (ISSUE-P-SEGMENTACION): ver nota en get_all_payments."""
    if cursos_permitidos is not None:
        return await Payment.find(
            Payment.estado_pago == EstadoPago.PENDIENTE,
            In(Payment.curso_id, cursos_permitidos)
        ).to_list()
    return await Payment.find(Payment.estado_pago == EstadoPago.PENDIENTE).to_list()


async def aprobar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> Payment:
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede aprobar un pago que está en estado {payment.estado_pago}"
        )
    
    payment.aprobar_pago(admin_username)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): otra request (aprobar/rechazar) ya modificó
        # este pago entre la lectura y este guardado. Se rechaza limpio en
        # vez de sobrescribir a ciegas (evita duplicar/inflar el saldo).
        raise ValueError(
            "Este pago ya fue modificado por otra acción (posible aprobación/rechazo simultáneo). "
            "Actualiza la página e intenta de nuevo."
        )
    
    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=payment.inscripcion_id,
        monto_pago_aprobado=payment.cantidad_pago
    )

    await _registrar_auditoria_financiera(
        accion="APROBAR PAGO",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Aprobado el {payment.concepto}"
    )

    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que su pago ha sido aprobado de manera exitosa
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Aprobado",
            mensaje=f"Tu pago de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}' ha sido conciliado y aprobado de forma exitosa.",
            tipo_alerta="success",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago aprobado: {str(e)}")

    # Correo real al estudiante confirmando la aprobación (no bloqueante: si
    # falla el envío o el estudiante no tiene email, el pago ya quedó aprobado).
    try:
        from models.student import Student as _Student
        from core.email_utils import send_email, build_pago_aprobado_email
        from core.config import settings

        _est = await _Student.get(payment.estudiante_id)
        if _est and _est.email:
            portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/payments"
            html = build_pago_aprobado_email(
                nombre=_est.nombre or _est.registro,
                concepto=payment.concepto,
                monto=payment.cantidad_pago,
                portal_link=portal_link
            )
            await send_email(_est.email, "Pago Aprobado · Postgrado UAGRM", html)
    except Exception as e:
        print(f"Error al enviar correo de pago aprobado: {str(e)}")

    return payment


async def rechazar_pago(
    payment_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> Payment:
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede rechazar un pago que está en estado {payment.estado_pago}"
        )
    
    payment.rechazar_pago(admin_username, motivo)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): ver nota equivalente en aprobar_pago.
        raise ValueError(
            "Este pago ya fue modificado por otra acción (posible aprobación/rechazo simultáneo). "
            "Actualiza la página e intenta de nuevo."
        )

    await _registrar_auditoria_financiera(
        accion="RECHAZAR PAGO",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Rechazado. Motivo: {motivo}"
    )
    
    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que su pago fue rechazado indicándole el motivo del cajero
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Rechazado",
            mensaje=f"Tu comprobante de pago por Bs. {payment.cantidad_pago} para '{payment.concepto}' ha sido rechazado. Motivo: {motivo}",
            tipo_alerta="error",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago rechazado: {str(e)}")

    return payment


async def anular_pago(
    payment_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> Payment:
    """
    ISSUE-P-CANALES: Realiza un Rollback Financiero (Anulación de pago ya aprobado).
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.APROBADO:
        raise ValueError(
            f"La anulación solo aplica para pagos APROBADOS. "
            f"Este pago se encuentra en estado '{payment.estado_pago}'."
        )
    
    payment.anular_pago(admin_username, motivo)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): ver nota equivalente en aprobar_pago.
        raise ValueError(
            "Este pago ya fue modificado por otra acción simultánea. Actualiza la página e intenta de nuevo."
        )

    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=payment.inscripcion_id,
        monto_pago_aprobado=0.0 
    )

    await _registrar_auditoria_financiera(
        accion="ANULAR PAGO (ROLLBACK)",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Anulación de fondos. Motivo legal: {motivo}"
    )
    
    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que un pago previamente aprobado ha sido anulado (rollback)
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Anulado (Reversión)",
            mensaje=f"Atención: Tu pago aprobado de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}' ha sido anulado. Razón: {motivo}",
            tipo_alerta="warning",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago anulado: {str(e)}")

    return payment


async def eliminar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> dict:
    """
    Elimina FÍSICAMENTE un pago de la base de datos (borrado destructivo,
    exclusivo de superadmin). Pensado para limpiar pagos de prueba/erróneos
    que no deben computar en la contabilidad.

    A diferencia de `anular_pago` (que preserva el registro con estado ANULADO),
    esto borra el documento por completo y luego recalcula el saldo/estado de la
    inscripción desde CERO a partir de los pagos APROBADOS restantes en la base
    de datos, sin importar en qué estado estuviera el pago borrado. De esta forma
    los totales económicos quedan consistentes tras la eliminación.
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")

    # Capturar datos antes de borrar (para auditoría y recálculo)
    enrollment_id = payment.inscripcion_id
    estudiante_id = payment.estudiante_id
    monto = payment.cantidad_pago
    concepto = payment.concepto
    estado_previo = payment.estado_pago.value if payment.estado_pago else "desconocido"

    await payment.delete()

    # Recalcular saldo de la inscripción desde los pagos aprobados que quedan.
    # actualizar_saldo_enrollment recomputa desde cero (suma los pagos APROBADOS
    # actuales en BD), por lo que basta con invocarlo tras el borrado.
    if enrollment_id:
        try:
            await enrollment_service.actualizar_saldo_enrollment(
                enrollment_id=enrollment_id,
                monto_pago_aprobado=0.0
            )
        except Exception as e:
            print(f"Error al recalcular saldo tras eliminar pago {payment_id}: {str(e)}")

    await _registrar_auditoria_financiera(
        accion="ELIMINAR PAGO (BORRADO DEFINITIVO)",
        payment_id=payment_id,
        estudiante_id=estudiante_id,
        monto=monto,
        admin_username=admin_username,
        detalles=f"Borrado físico de pago (estado previo: {estado_previo}, concepto: {concepto})"
    )

    return {
        "success": True,
        "message": "Pago eliminado correctamente",
        "payment_id": str(payment_id)
    }


def _construir_filtro_reporte_caja(
    fecha_desde_dt: datetime,
    fecha_hasta_dt: datetime,
    curso_id: Optional[PydanticObjectId] = None,
    estado: Optional[str] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
) -> dict:
    """
    ISSUE-P-REPORTE: filtro compartido entre la tabla interactiva y el export
    a Excel, para que ambos muestren siempre los mismos datos.

    Filtra por `fecha_comprobante` (fecha REAL de la transacción aportada por
    el usuario) O `fecha_subida` como respaldo si el pago no tiene
    `fecha_comprobante` registrada (defensivo; el flujo real del frontend
    siempre la envía, pero un pago creado por otra vía sin ese campo no debe
    desaparecer silenciosamente del reporte) -- regla de negocio explícita:
    "la contabilidad financiera se rige por la fecha real de la transacción,
    no por la fecha de aprobación/verificación en el panel"
    (steering/structure.md). El endpoint de Excel anterior filtraba solo por
    fecha_subida; se corrige aquí para ambos casos (tabla y export).
    """
    criteria: dict = {
        "$or": [
            {"fecha_comprobante": {"$gte": fecha_desde_dt, "$lte": fecha_hasta_dt}},
            {"fecha_comprobante": None, "fecha_subida": {"$gte": fecha_desde_dt, "$lte": fecha_hasta_dt}},
        ]
    }
    if curso_id:
        criteria["curso_id"] = curso_id
    if estado and estado != "Todos los estados":
        criteria["estado_pago"] = estado
    if cursos_permitidos is not None:
        # Si ya hay un curso_id específico Y además hay segmentación, deben
        # combinarse (AND), no pisarse uno al otro.
        if "curso_id" in criteria:
            if criteria["curso_id"] not in cursos_permitidos:
                # Curso solicitado fuera de los permitidos: forzar 0 resultados
                # en vez de devolver datos de otro curso.
                criteria["curso_id"] = {"$in": []}
        else:
            criteria["curso_id"] = {"$in": cursos_permitidos}
    return criteria


async def get_reporte_caja(
    fecha_desde_dt: datetime,
    fecha_hasta_dt: datetime,
    page: int = 1,
    per_page: int = 20,
    curso_id: Optional[PydanticObjectId] = None,
    estado: Optional[str] = None,
    concepto_regex: Optional[dict] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
) -> dict:
    """
    ISSUE-P-REPORTE: tabla interactiva de ingresos por rango de fechas (fecha
    real del pago), curso y estado, con totales agregados para el resumen
    visual (no solo la lista paginada).
    """
    criteria = _construir_filtro_reporte_caja(
        fecha_desde_dt, fecha_hasta_dt, curso_id=curso_id, estado=estado, cursos_permitidos=cursos_permitidos
    )
    if concepto_regex:
        criteria.update(concepto_regex)

    total_count = await Payment.find(criteria).count()
    skip = (page - 1) * per_page
    payments = await Payment.find(criteria).sort("-fecha_comprobante").skip(skip).limit(per_page).to_list()

    # Totales agregados sobre TODO el rango filtrado (no solo la página actual)
    todos_los_pagos_del_rango = await Payment.find(criteria).to_list()
    total_aprobado = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.APROBADO)
    total_pendiente = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.PENDIENTE)
    total_anulado = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.ANULADO)

    return {
        "payments": payments,
        "total_count": total_count,
        "resumen": {
            "cantidad_pagos": len(todos_los_pagos_del_rango),
            "total_aprobado": round(total_aprobado, 2),
            "total_pendiente": round(total_pendiente, 2),
            "total_anulado": round(total_anulado, 2),
        }
    }


async def get_resumen_pagos_enrollment(enrollment_id: PydanticObjectId) -> dict:
    payments = await get_payments_by_enrollment(enrollment_id)
    
    resumen = {
        "total_pagos": len(payments),
        "pendientes": len([p for p in payments if p.estado_pago == EstadoPago.PENDIENTE]),
        "aprobados": len([p for p in payments if p.estado_pago == EstadoPago.APROBADO]),
        "rechazados": len([p for p in payments if p.estado_pago == EstadoPago.RECHAZADO]),
        "anulados": len([p for p in payments if p.estado_pago == EstadoPago.ANULADO]),
        "monto_total_aprobado": sum(
            p.cantidad_pago for p in payments if p.estado_pago == EstadoPago.APROBADO
        ),
    }
    return resumen


async def create_caja_directo_payment(
    estudiante_id: PydanticObjectId,
    inscripcion_id: PydanticObjectId,
    cantidad_pago: float,
    admin_username: str,
    concepto: Optional[str] = None,
    numero_cuota: Optional[int] = None,
    remitente: Optional[str] = None,
    cuenta_destino: Optional[str] = None
) -> Payment:
    """
    Registrar un pago físico directo en Caja realizado por cobranzas para un alumno.
    El pago se crea directamente como APROBADO e impacta el saldo del estudiante automáticamente.
    No requiere las credenciales del estudiante para procesar.
    """
    enrollment = await Enrollment.get(inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {inscripcion_id} no encontrada")
        
    if enrollment.estudiante_id != estudiante_id:
        raise ValueError("La inscripción seleccionada no coincide con el estudiante")

    next_payment = await get_next_pending_payment(inscripcion_id)
    if not next_payment:
         raise ValueError("Esta inscripción ya tiene todos los pagos en proceso o aprobados.")

    concepto_final = concepto if concepto else next_payment["concepto"]
    cuota_final = numero_cuota if numero_cuota else next_payment["numero_cuota"]

    # AUDITORÍA (ALTO #4): mismo control de sobrepago que create_payment. El
    # cobro en Caja se crea directamente APROBADO, así que aquí el riesgo es
    # mayor (no hay paso de revisión posterior que lo detecte).
    if cantidad_pago > enrollment.saldo_pendiente + 1.0:
        raise ValueError(
            f"El monto a cobrar (Bs. {cantidad_pago}) supera el saldo pendiente de la inscripción "
            f"(Bs. {enrollment.saldo_pendiente}). Verifica el monto antes de registrar el cobro."
        )

    # Crear pago ya APROBADO naciendo en Caja
    payment = Payment(
        inscripcion_id=inscripcion_id,
        estudiante_id=estudiante_id,
        curso_id=enrollment.curso_id,
        metodo_pago="Caja",
        concepto=concepto_final,
        cantidad_pago=cantidad_pago,
        numero_cuota=cuota_final,
        numero_transaccion="Caja / Directo",
        comprobante_url=None,
        remitente=remitente,
        banco="Caja Física",
        monto_comprobante=cantidad_pago,
        fecha_comprobante=datetime.utcnow(),
        cuenta_destino=cuenta_destino or f"Caja Física - {admin_username}",
        estado_pago=EstadoPago.APROBADO
    )
    
    # Sellar la verificación automática de caja
    payment.fecha_verificacion = datetime.utcnow()
    payment.verificado_por = admin_username
    
    await payment.insert()

    # Reestructuración Financiera (Algoritmo de cascada Waterfall)
    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=inscripcion_id,
        monto_pago_aprobado=cantidad_pago
    )

    # Registrar Auditoría inmutable de caja
    await _registrar_auditoria_financiera(
        accion="COBRO DIRECTO EN CAJA",
        payment_id=payment.id,
        estudiante_id=estudiante_id,
        monto=cantidad_pago,
        admin_username=admin_username,
        detalles=f"Cobro directo en caja procesado por {admin_username}. Concepto: {concepto_final}"
    )

    # Notificar al alumno de inmediato en su buzón transaccional
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Registrado en Caja",
            mensaje=f"Se ha registrado un pago directo en Caja por Bs. {cantidad_pago} para el concepto '{concepto_final}'. El pago ha sido aprobado automáticamente.",
            tipo_alerta="success",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al notificar pago directo en caja: {str(e)}")

    return payment