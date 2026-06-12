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
import asyncio
from datetime import datetime
from models.payment import Payment
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.enums import EstadoPago
from schemas.payment import PaymentCreate
from beanie import PydanticObjectId
from beanie.operators import In, Or
from services import enrollment_service


async def enrich_payment_with_details(payment: Payment) -> dict:
    """
    Enriquecer un pago individual (usado para vistas de un solo ítem)
    """
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
        "updated_at": updated_at_bolivia
    })
    
    return payment_dict


async def enrich_payments_with_details_bulk(payments: List[Payment]) -> List[dict]:
    """
    ¡RESOLUCIÓN DE CUELLO DE BOTELLA CRÍTICO N+1!
    Enriquece una lista de pagos en lote realizando solo 2 consultas agrupadas a la base de datos
    mediante el operador $in, en lugar de 2 * N consultas secuenciales de red.
    """
    if not payments:
        return []

    # 1. Agrupar IDs únicos a buscar
    student_ids = list({p.estudiante_id for p in payments if p.estudiante_id})
    enrollment_ids = list({p.inscripcion_id for p in payments if p.inscripcion_id})

    # 2. Consultas concurrentes en paralelo
    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()
    
    students, enrollments = await asyncio.gather(students_task, enrollments_task)

    # 3. Mapeos O(1) en memoria para resolución ultrarrápida
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
            "updated_at": to_bolivia_time(payment.updated_at)
        })
        enriched_list.append(p_dict)

    return enriched_list


async def get_next_pending_payment(enrollment_id: PydanticObjectId) -> dict:
    """
    Calcula el siguiente pago pendiente.
    """
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
    Crear un nuevo pago.
    """
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment_in.inscripcion_id} no encontrada")
    
    if enrollment.estudiante_id != student_id:
        raise ValueError(
            "No puedes crear un pago para una inscripción que no te pertenece"
        )

    # Validación anti-fraude
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

    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,
        estudiante_id=enrollment.estudiante_id,
        curso_id=enrollment.curso_id,
        concepto=next_payment["concepto"],
        cantidad_pago=next_payment["monto_sugerido"],
        numero_cuota=next_payment["numero_cuota"],
        numero_transaccion=payment_in.numero_transaccion,
        comprobante_url=payment_in.comprobante_url,
        remitente=payment_in.remitente,
        banco=payment_in.banco,
        monto_comprobante=payment_in.monto_comprobante,
        fecha_comprobante=payment_in.fecha_comprobante,
        cuenta_destino=payment_in.cuenta_destino,
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
    ).sort("-fecha_subida").to_list()


async def get_payments_by_enrollment(enrollment_id: PydanticObjectId) -> List[Payment]:
    """Obtener todos los pagos de una inscripción"""
    return await Payment.find(
        Payment.inscripcion_id == enrollment_id
    ).sort("-fecha_subida").to_list()


async def get_payments_by_course(course_id: PydanticObjectId) -> List[Payment]:
    """Obtener todos los pagos de un curso"""
    return await Payment.find(
        Payment.curso_id == course_id
    ).sort("-fecha_subida").to_list()


async def get_all_payments(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    curso_id: Optional[PydanticObjectId] = None,
    estudiante_id: Optional[PydanticObjectId] = None
) -> tuple[List[Payment], int]:
    """
    Obtener todos los pagos con paginación y filtros complejos (Bug 8 Fix).
    """
    # Usamos diccionarios de consulta planos para soportar consultas más robustas en Beanie
    query_dict = {}
    
    # Filtro de Estado exacto
    if estado and estado != "Todos los estados":
        query_dict["estado_pago"] = estado

    # Filtro de Estudiante exacto
    if estudiante_id:
        query_dict["estudiante_id"] = estudiante_id

    # Filtro de Programa Académico (Curso)
    # Buscamos todas las inscripciones (enrollments) que pertenezcan a ese curso
    if curso_id:
        enrollments = await Enrollment.find(Enrollment.curso_id == curso_id).to_list()
        enrollment_ids = [e.id for e in enrollments]
        query_dict["inscripcion_id"] = {"$in": enrollment_ids}
        
    # Filtro Dinámico (Buscador general)
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        
        # Sub-consulta: Encontrar estudiantes que coincidan en nombre, registro o carnet
        matching_students = await Student.find(
            Or(
                Student.nombre == regex_pattern,
                Student.registro == regex_pattern,
                Student.carnet == regex_pattern,
                Student.email == regex_pattern
            )
        ).to_list()
        
        matching_student_ids = [s.id for s in matching_students]

        # Combinar búsquedas de texto: Que coincida en los campos del pago O que sea uno de esos estudiantes
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


async def get_payments_pendientes() -> List[Payment]:
    """
    Obtener todos los pagos pendientes de revisión
    """
    return await Payment.find(
        Payment.estado_pago == EstadoPago.PENDIENTE
    ).to_list()


async def aprobar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> Payment:
    """
    Aprobar un pago
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede aprobar un pago que está en estado {payment.estado_pago}"
        )
    
    existing_approved = await Payment.find_one(
        Payment.id != payment_id,
        Payment.inscripcion_id == payment.inscripcion_id,
        Payment.concepto == payment.concepto,
        Payment.numero_cuota == payment.numero_cuota,
        Payment.estado_pago == EstadoPago.APROBADO
    )
    
    if existing_approved:
        cuota_texto = f" (Cuota {payment.numero_cuota})" if payment.numero_cuota else ""
        raise ValueError(
            f"No se puede aprobar: ya existe un pago aprobado para {payment.concepto}{cuota_texto}. "
            f"Pago aprobado existente: {existing_approved.id}."
        )
    
    enrollment = await Enrollment.get(payment.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment.inscripcion_id} no encontrada")
    
    if payment.concepto == "Matrícula":
        enrollment.matricula_pagada = True
        await enrollment.save()
    
    payment.aprobar_pago(admin_username)
    await payment.save()
    
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
    Rechazar un pago
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede rechazar un pago que está en estado {payment.estado_pago}"
        )
    
    payment.rechazar_pago(admin_username, motivo)
    await payment.save()
    return payment


async def get_resumen_pagos_enrollment(enrollment_id: PydanticObjectId) -> dict:
    """
    Obtener resumen de pagos de una inscripción
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
