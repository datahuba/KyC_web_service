"""
Servicio de Inscripciones (Enrollments)
=======================================

Lógica de negocio para inscripciones.

Permisos:
---------
- CREAR inscripción: Solo ADMIN/SUPERADMIN
- ACTUALIZAR inscripción: Solo ADMIN/SUPERADMIN
- VER inscripciones: ADMIN (todas), STUDENT (solo las suyas)
"""

from typing import List, Optional
from datetime import datetime
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.enums import TipoEstudiante, EstadoInscripcion
from schemas.enrollment import EnrollmentCreate
from beanie import PydanticObjectId


async def create_enrollment(enrollment_in: EnrollmentCreate, admin_username: str) -> Enrollment:
    """
    Crear una nueva inscripción (solo admins)
    
    Proceso:
    1. Obtener datos del estudiante y curso
    2. Calcular precios según tipo de estudiante
    3. Aplicar descuentos (del curso + personalizado)
    4. Crear inscripción con snapshot de precios
    
    Args:
        enrollment_in: Datos de la inscripción
        admin_username: Username del admin que crea la inscripción
    
    Returns:
        Inscripción creada
    
    Raises:
        ValueError: Si el estudiante o curso no existe
        ValueError: Si el estudiante ya está inscrito en ese curso
    """
    
    # 1. Obtener estudiante y curso
    student = await Student.get(enrollment_in.estudiante_id)
    if not student:
        raise ValueError(f"Estudiante {enrollment_in.estudiante_id} no encontrado")
    
    course = await Course.get(enrollment_in.curso_id)
    if not course:
        raise ValueError(f"Curso {enrollment_in.curso_id} no encontrado")
    
    # 2. Validar que no esté ya inscrito
    existing = await Enrollment.find_one(
        Enrollment.estudiante_id == enrollment_in.estudiante_id,
        Enrollment.curso_id == enrollment_in.curso_id,
        Enrollment.estado != EstadoInscripcion.CANCELADO
    )
    if existing:
        raise ValueError(
            f"El estudiante ya está inscrito en este curso (Inscripción ID: {existing.id})"
        )
    
    # 3. Determinar tipo de estudiante (usar el del Student)
    es_interno = student.es_estudiante_interno == TipoEstudiante.INTERNO
    
    # 4. Obtener precios del curso
    costo_total = course.get_costo_total(es_interno)
    costo_matricula = course.get_matricula(es_interno)
    
    # 5. Aplicar descuento del curso
    descuento_curso = course.descuento_curso or 0.0
    total_con_descuento_curso = costo_total - (costo_total * descuento_curso / 100)
    
    # 6. Aplicar descuento personalizado (si existe)
    descuento_personal = enrollment_in.descuento_personalizado or 0.0
    total_final = total_con_descuento_curso - (total_con_descuento_curso * descuento_personal / 100)
    
    # 7. Crear inscripción con snapshot de precios
    enrollment = Enrollment(
        estudiante_id=enrollment_in.estudiante_id,
        curso_id=enrollment_in.curso_id,
        es_estudiante_interno=student.es_estudiante_interno,
        costo_total=costo_total,
        costo_matricula=costo_matricula,
        cantidad_cuotas=course.cantidad_cuotas,
        descuento_curso_aplicado=descuento_curso,
        descuento_personalizado=descuento_personal,
        total_a_pagar=round(total_final, 2),
        saldo_pendiente=round(total_final, 2),
        estado=EstadoInscripcion.PENDIENTE_PAGO
    )
    
    await enrollment.insert()
    
    # 8. Agregar estudiante a la lista de inscritos del curso
    if enrollment_in.estudiante_id not in course.inscritos:
        course.inscritos.append(enrollment_in.estudiante_id)
        await course.save()
    
    return enrollment


async def get_enrollment(id: PydanticObjectId) -> Optional[Enrollment]:
    """Obtener una inscripción por ID"""
    return await Enrollment.get(id)


async def get_enrollments_by_student(student_id: PydanticObjectId) -> List[Enrollment]:
    """Obtener todas las inscripciones de un estudiante"""
    return await Enrollment.find(
        Enrollment.estudiante_id == student_id
    ).to_list()


async def get_enrollments_by_course(course_id: PydanticObjectId) -> List[Enrollment]:
    """Obtener todas las inscripciones de un curso"""
    return await Enrollment.find(
        Enrollment.curso_id == course_id
    ).to_list()


async def get_all_enrollments(
    skip: int = 0,
    limit: int = 100,
    estado: Optional[EstadoInscripcion] = None
) -> List[Enrollment]:
    """
    Obtener todas las inscripciones (solo admins)
    
    Args:
        skip: Cantidad de registros a saltar (paginación)
        limit: Cantidad máxima de registros a retornar
        estado: Filtrar por estado (opcional)
    """
    query = Enrollment.find()
    
    if estado:
        query = query.find(Enrollment.estado == estado)
    
    return await query.skip(skip).limit(limit).to_list()


async def update_enrollment_descuento(
    enrollment_id: PydanticObjectId,
    descuento_personalizado: float,
    admin_username: str
) -> Enrollment:
    """
    Actualizar descuento personalizado de una inscripción (solo admin)
    
    Recalcula el total_a_pagar y saldo_pendiente.
    
    Args:
        enrollment_id: ID de la inscripción
        descuento_personalizado: Nuevo descuento personalizado (%)
        admin_username: Username del admin
    
    Returns:
        Inscripción actualizada
    
    Raises:
        ValueError: Si la inscripción no existe
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    # Recalcular total con nuevo descuento
    total_con_descuento_curso = enrollment.costo_total - (
        enrollment.costo_total * enrollment.descuento_curso_aplicado / 100
    )
    
    total_final = total_con_descuento_curso - (
        total_con_descuento_curso * descuento_personalizado / 100
    )
    
    # Calcular nuevo saldo pendiente
    nuevo_saldo = total_final - enrollment.total_pagado
    
    # Actualizar
    enrollment.descuento_personalizado = descuento_personalizado
    enrollment.total_a_pagar = round(total_final, 2)
    enrollment.saldo_pendiente = round(max(0, nuevo_saldo), 2)
    enrollment.updated_at = datetime.utcnow()
    
    await enrollment.save()
    return enrollment


async def cambiar_estado_enrollment(
    enrollment_id: PydanticObjectId,
    nuevo_estado: EstadoInscripcion,
    admin_username: str
) -> Enrollment:
    """
    Cambiar el estado de una inscripción (solo admin)
    
    Args:
        enrollment_id: ID de la inscripción
        nuevo_estado: Nuevo estado
        admin_username: Username del admin
    
    Returns:
        Inscripción actualizada
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    enrollment.estado = nuevo_estado
    enrollment.updated_at = datetime.utcnow()
    
    await enrollment.save()
    return enrollment


async def actualizar_saldo_enrollment(
    enrollment_id: PydanticObjectId,
    monto_pago_aprobado: float
):
    """
    Actualizar el saldo de una inscripción cuando se aprueba un pago
    
    Esta función es llamada automáticamente por payment_service
    cuando se aprueba un pago.
    
    Args:
        enrollment_id: ID de la inscripción
        monto_pago_aprobado: Monto del pago que fue aprobado
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    # Actualizar totales
    enrollment.actualizar_saldo(monto_pago_aprobado)
    
    # Cambiar estado si pagó matrícula
    if enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO:
        enrollment.estado = EstadoInscripcion.ACTIVO
    
    # Cambiar a COMPLETADO si pagó todo
    if enrollment.esta_completamente_pagado():
        enrollment.estado = EstadoInscripcion.COMPLETADO
    
    await enrollment.save()
