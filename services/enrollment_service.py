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
from models.enrollment import Enrollment, ModuloEstado
from models.student import Student
from models.course import Course
from models.enums import TipoEstudiante, EstadoInscripcion
from schemas.enrollment import EnrollmentCreate
from beanie import PydanticObjectId
from models.discount import Discount
from beanie.operators import In, Or

async def create_enrollment(enrollment_in: EnrollmentCreate, admin_username: str) -> Enrollment:
    """
    Crear una nueva inscripción (solo admins)
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
    descuento_curso = 0.0
    descuento_curso_id = None
    
    if course.descuento_id:
        discount_obj = await Discount.get(course.descuento_id)
        if discount_obj and discount_obj.activo:
            descuento_curso = discount_obj.porcentaje
            descuento_curso_id = discount_obj.id
    elif course.descuento_curso:
        descuento_curso = course.descuento_curso
        
    total_con_descuento_curso = costo_total - (costo_total * descuento_curso / 100)
    
    # 6. Aplicar descuento del estudiante
    descuento_personal = 0.0
    descuento_estudiante_id = None
    
    if enrollment_in.descuento_id:
        discount_sel = await Discount.get(enrollment_in.descuento_id)
        if discount_sel and discount_sel.activo:
            descuento_personal = discount_sel.porcentaje
            descuento_estudiante_id = discount_sel.id
    elif enrollment_in.descuento_personalizado:
        descuento_personal = enrollment_in.descuento_personalizado
        
    colegiatura_final = total_con_descuento_curso - (total_con_descuento_curso * descuento_personal / 100)
    
    # MATEMÁTICA FINANCIERA CORREGIDA:
    total_final = colegiatura_final + costo_matricula
    
    # 7. Copiar requisitos del curso
    requisitos_enrollment = [template.to_requisito() for template in course.requisitos]
    
    # 8. Clonación y distribución de módulos A PRUEBA DE BALAS
    modulos_enrollment = []
    if course.modulos:
        suma_costo_modulos = sum(mod.costo for mod in course.modulos)
        total_asignado = 0.0
        
        for i, mod in enumerate(course.modulos):
            if i == len(course.modulos) - 1:
                costo_final_mod = max(0.0, round(colegiatura_final - total_asignado, 2))
            else:
                if suma_costo_modulos > 0:
                    costo_final_mod = round((mod.costo / suma_costo_modulos) * colegiatura_final, 2)
                else:
                    costo_final_mod = round(colegiatura_final / len(course.modulos), 2)
                total_asignado += costo_final_mod
            
            modulos_enrollment.append(
                ModuloEstado(
                    nombre=mod.nombre,
                    costo=costo_final_mod,
                    estado="Pendiente",
                    monto_pagado=0.0,
                    nota=None,
                    estado_academico="Cursando"
                )
            )
    
    # 9. Crear inscripción
    enrollment = Enrollment(
        estudiante_id=enrollment_in.estudiante_id,
        curso_id=enrollment_in.curso_id,
        es_estudiante_interno=student.es_estudiante_interno,
        costo_total=costo_total,
        costo_matricula=costo_matricula,
        cantidad_cuotas=course.cantidad_cuotas,
        modulos=modulos_enrollment,
        
        descuento_curso_id=descuento_curso_id,
        descuento_curso_aplicado=descuento_curso,
        descuento_estudiante_id=descuento_estudiante_id,
        descuento_personalizado=descuento_personal,
        
        total_a_pagar=round(total_final, 2),
        saldo_pendiente=round(total_final, 2),
        estado=EstadoInscripcion.PENDIENTE_PAGO,
        matricula_pagada=False,
        requisitos=requisitos_enrollment
    )
    
    await enrollment.insert()
    
    # 10. Agregar estudiante a la lista
    if enrollment_in.estudiante_id not in course.inscritos:
        course.inscritos.append(enrollment_in.estudiante_id)
        await course.save()
    
    # 11. Agregar curso al estudiante
    if enrollment_in.curso_id not in student.lista_cursos_ids:
        student.lista_cursos_ids.append(enrollment_in.curso_id)
        await student.save()
    
    return enrollment


async def enrich_enrollment_dates(enrollment: Enrollment) -> dict:
    from core.timezone_utils import to_bolivia_time
    enrollment_dict = enrollment.model_dump()
    enrollment_dict["fecha_inscripcion"] = to_bolivia_time(enrollment.fecha_inscripcion)
    enrollment_dict["created_at"] = to_bolivia_time(enrollment.created_at)
    enrollment_dict["updated_at"] = to_bolivia_time(enrollment.updated_at)
    return enrollment_dict


async def get_enrollment(id: PydanticObjectId) -> Optional[Enrollment]:
    return await Enrollment.get(id)


async def get_enrollments_by_student(student_id: PydanticObjectId) -> List[Enrollment]:
    return await Enrollment.find(Enrollment.estudiante_id == student_id).to_list()


async def get_enrollments_by_course(course_id: PydanticObjectId) -> List[Enrollment]:
    return await Enrollment.find(Enrollment.curso_id == course_id).to_list()


async def get_all_enrollments(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    estado: Optional[EstadoInscripcion] = None,
    curso_id: Optional[PydanticObjectId] = None,
    estudiante_id: Optional[PydanticObjectId] = None
) -> tuple[List[Enrollment], int]:
    
    query = Enrollment.find()
    
    if estado:
        query = query.find(Enrollment.estado == estado)
    if curso_id:
        query = query.find(Enrollment.curso_id == curso_id)
    if estudiante_id:
        query = query.find(Enrollment.estudiante_id == estudiante_id)
        
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        students = await Student.find(Or(Student.nombre == regex_pattern, Student.carnet == regex_pattern)).to_list()
        student_ids = [s.id for s in students]
        
        courses = await Course.find(Course.nombre_programa == regex_pattern).to_list()
        course_ids = [c.id for c in courses]
        
        query = query.find(Or(In(Enrollment.estudiante_id, student_ids), In(Enrollment.curso_id, course_ids)))
    
    total_count = await query.count()
    skip = (page - 1) * per_page
    
    enrollments = await query.sort("-fecha_inscripcion").skip(skip).limit(per_page).to_list()
    return enrollments, total_count


async def update_enrollment_descuento(
    enrollment_id: PydanticObjectId,
    descuento_personalizado: float,
    admin_username: str
) -> Enrollment:
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    total_con_descuento_curso = enrollment.costo_total - (enrollment.costo_total * enrollment.descuento_curso_aplicado / 100)
    colegiatura_final = total_con_descuento_curso - (total_con_descuento_curso * descuento_personalizado / 100)
    total_final = colegiatura_final + enrollment.costo_matricula
    nuevo_saldo = total_final - enrollment.total_pagado
    
    enrollment.descuento_personalizado = descuento_personalizado
    enrollment.total_a_pagar = round(total_final, 2)
    enrollment.saldo_pendiente = round(max(0.0, nuevo_saldo), 2)
    enrollment.updated_at = datetime.utcnow()
    
    await enrollment.save()
    return enrollment


async def cambiar_estado_enrollment(
    enrollment_id: PydanticObjectId,
    nuevo_estado: EstadoInscripcion,
    admin_username: str
) -> Enrollment:
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    enrollment.estado = nuevo_estado
    enrollment.updated_at = datetime.utcnow()
    
    await enrollment.save()
    return enrollment


# ========================================================================
# ISSUE-F-PRORRATEO: ALGORITMO FINANCIERO EN CASCADA
# ========================================================================
async def actualizar_saldo_enrollment(
    enrollment_id: PydanticObjectId,
    monto_pago_aprobado: float
):
    """
    Actualiza el saldo de la inscripción distribuyendo el dinero en cascada (Waterfall).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    # 1. Sumamos el pago al total histórico
    monto_disponible = round(monto_pago_aprobado, 2)
    
    # 2. Paso 1: Cubrir la matrícula si aún se debe algo de ella
    if not enrollment.matricula_pagada:
        # Asumimos que los primeros pagos siempre van a matrícula hasta cubrir `costo_matricula`
        pagos_historicos = round(enrollment.total_pagado, 2)
        deuda_matricula = round(enrollment.costo_matricula - pagos_historicos, 2)
        
        if deuda_matricula > 0:
            if monto_disponible >= deuda_matricula:
                monto_disponible = round(monto_disponible - deuda_matricula, 2)
                enrollment.matricula_pagada = True
            else:
                # El pago no alcanzó para cubrir la matrícula entera
                monto_disponible = 0.0

    # 3. Paso 2: Cascada sobre los módulos de colegiatura
    if monto_disponible > 0:
        for idx, modulo in enumerate(enrollment.modulos):
            if monto_disponible <= 0.01:
                break # El dinero se agotó

            deuda_modulo = round(modulo.costo - modulo.monto_pagado, 2)
            
            if deuda_modulo > 0.01: # Si el módulo aún no está totalmente pagado
                if monto_disponible >= deuda_modulo:
                    # El dinero cubre este módulo completamente
                    modulo.monto_pagado = modulo.costo
                    modulo.estado = "Pagado"
                    monto_disponible = round(monto_disponible - deuda_modulo, 2)
                else:
                    # El dinero se agota en este módulo (Pago parcial)
                    modulo.monto_pagado = round(modulo.monto_pagado + monto_disponible, 2)
                    modulo.estado = "Parcial"
                    monto_disponible = 0.0

    # 4. Actualizar Totales Globales
    enrollment.actualizar_saldo(monto_pago_aprobado)
    
    # 5. Evolución del Estado Operacional
    if enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO and enrollment.matricula_pagada:
        enrollment.estado = EstadoInscripcion.ACTIVO
    
    if enrollment.esta_completamente_pagado():
        enrollment.estado = EstadoInscripcion.COMPLETADO
    
    await enrollment.save()


# ========================================================================
# LÓGICA ACADÉMICA (ISSUE P)
# ========================================================================
async def actualizar_nota_modulo(
    enrollment_id: PydanticObjectId, 
    modulo_index: int, 
    nota: float, 
    evaluador_username: str
) -> Enrollment:
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción no encontrada")
        
    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise ValueError(f"Índice de módulo {modulo_index} fuera de rango")
        
    enrollment.modulos[modulo_index].nota = round(nota, 2)
    
    if nota >= 64.0:
        enrollment.modulos[modulo_index].estado_academico = "Aprobado"
    else:
        enrollment.modulos[modulo_index].estado_academico = "Reprobado"
        
    notas_evaluadas = [m.nota for m in enrollment.modulos if m.nota is not None]
    if notas_evaluadas:
        promedio = sum(notas_evaluadas) / len(notas_evaluadas)
        enrollment.nota_final = round(promedio, 2)
        
    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()
    
    return enrollment
