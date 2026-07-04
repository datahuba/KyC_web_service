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

    # ISSUE-P-RECALCULO-NOTA: snapshot de la nota mínima exigida por el descuento personal
    # (solo si viene de un Discount vinculado con condición académica; descuento_personalizado libre no aplica)
    nota_minima_snapshot = None
    if descuento_estudiante_id and discount_sel and discount_sel.nota_minima_requerida is not None:
        nota_minima_snapshot = discount_sel.nota_minima_requerida
    
    # 7. Copiar requisitos del curso
    requisitos_enrollment = [template.to_requisito() for template in course.requisitos]
    
    # 8. Clonación y distribución de módulos A PRUEBA DE BALAS
    modulos_enrollment = []
    if course.modulos:
        suma_costo_modulos = sum(mod.costo for mod in course.modulos)
        total_asignado = 0.0
        total_asignado_sin_beca = 0.0  # ISSUE-P-RECALCULO-NOTA
        
        for i, mod in enumerate(course.modulos):
            es_ultimo = i == len(course.modulos) - 1
            if es_ultimo:
                costo_final_mod = max(0.0, round(colegiatura_final - total_asignado, 2))
            else:
                if suma_costo_modulos > 0:
                    costo_final_mod = round((mod.costo / suma_costo_modulos) * colegiatura_final, 2)
                else:
                    costo_final_mod = round(colegiatura_final / len(course.modulos), 2)
                total_asignado += costo_final_mod

            # ISSUE-P-RECALCULO-NOTA: distribución paralela SIN el descuento personal,
            # usando la misma proporción, solo si el descuento tiene condición académica.
            costo_sin_beca_mod = None
            if nota_minima_snapshot is not None:
                if es_ultimo:
                    costo_sin_beca_mod = max(0.0, round(total_con_descuento_curso - total_asignado_sin_beca, 2))
                else:
                    if suma_costo_modulos > 0:
                        costo_sin_beca_mod = round((mod.costo / suma_costo_modulos) * total_con_descuento_curso, 2)
                    else:
                        costo_sin_beca_mod = round(total_con_descuento_curso / len(course.modulos), 2)
                    total_asignado_sin_beca += costo_sin_beca_mod
            
            modulos_enrollment.append(
                ModuloEstado(
                    nombre=mod.nombre,
                    costo=costo_final_mod,
                    costo_sin_beca_personal=costo_sin_beca_mod,
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
        requisitos=requisitos_enrollment,
        nota_minima_beca=nota_minima_snapshot  # ISSUE-P-RECALCULO-NOTA
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
    estudiante_id: Optional[PydanticObjectId] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
) -> tuple[List[Enrollment], int]:
    """
    cursos_permitidos (ISSUE-R-ROLES): si se provee (no None), restringe los resultados
    únicamente a inscripciones de esos cursos. Se usa para segmentar el rol ENCARGADO_CURSO
    (y en el futuro COBRANZA, ISSUE-P-SEGMENTACION) a sus cursos asignados.
    """
    query = Enrollment.find()
    
    if estado:
        query = query.find(Enrollment.estado == estado)
    if curso_id:
        query = query.find(Enrollment.curso_id == curso_id)
    if estudiante_id:
        query = query.find(Enrollment.estudiante_id == estudiante_id)
    if cursos_permitidos is not None:
        query = query.find(In(Enrollment.curso_id, cursos_permitidos))
        
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
# ISSUE-F-PRORRATEO: ALGORITMO FINANCIERO EN CASCADA (V2 - RECONSTRUCCIÓN ABSOLUTA)
# ========================================================================
async def actualizar_saldo_enrollment(
    enrollment_id: PydanticObjectId,
    monto_pago_aprobado: float = 0.0 # Se mantiene la firma por compatibilidad, pero ya no se usa ciegamente
):
    """
    Reconstruye el saldo de la inscripción sumando todos los pagos históricos aprobados.
    Distribuye los fondos en cascada (Waterfall) reparando cualquier inconsistencia de base de datos.
    """
    from models.payment import Payment
    from models.enums import EstadoPago

    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")
    
    # 1. Recolectar la verdad absoluta: ¿Cuánto dinero REALMENTE tiene aprobado este alumno?
    pagos_aprobados = await Payment.find(
        Payment.inscripcion_id == enrollment_id,
        Payment.estado_pago == EstadoPago.APROBADO
    ).to_list()

    dinero_historico_total = sum(p.cantidad_pago for p in pagos_aprobados)
    tanque_de_agua = round(dinero_historico_total, 2)

    # 2. Reiniciar los contadores de la inscripción a cero para reconstruirlos
    enrollment.matricula_pagada = False
    for mod in enrollment.modulos:
        mod.monto_pagado = 0.0
        mod.estado = "Pendiente"

    # 3. PASO 1: Cubrir la matrícula administrativa obligatoria
    if tanque_de_agua >= enrollment.costo_matricula:
        tanque_de_agua = round(tanque_de_agua - enrollment.costo_matricula, 2)
        enrollment.matricula_pagada = True
        
        # REGLA DE NEGOCIO UAGRM: Al pagar matrícula, el alumno pasa a ser "Activo"
        if enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO:
            enrollment.estado = EstadoInscripcion.ACTIVO
    else:
        # El dinero no alcanzó ni para la matrícula
        enrollment.matricula_pagada = False
        tanque_de_agua = 0.0

    # 4. PASO 2: Cascada sobre los módulos académicos
    if tanque_de_agua > 0:
        for mod in enrollment.modulos:
            if tanque_de_agua <= 0.01:
                break # Se acabó el dinero

            costo_modulo = round(mod.costo, 2)
            
            if tanque_de_agua >= costo_modulo:
                # El dinero cubre este módulo completamente
                mod.monto_pagado = costo_modulo
                mod.estado = "Pagado"
                tanque_de_agua = round(tanque_de_agua - costo_modulo, 2)
            else:
                # El dinero restante se vierte en este módulo (Pago parcial)
                mod.monto_pagado = round(tanque_de_agua, 2)
                mod.estado = "Parcial"
                tanque_de_agua = 0.0

    # 5. Actualizar los totales globales (Total Pagado y Saldo Pendiente)
    enrollment.total_pagado = round(dinero_historico_total, 2)
    enrollment.saldo_pendiente = max(0.0, round(enrollment.total_a_pagar - dinero_historico_total, 2))
    
    # 6. Evolución a "Completado" si la deuda llegó a cero
    if enrollment.esta_completamente_pagado() and enrollment.matricula_pagada:
        enrollment.estado = EstadoInscripcion.COMPLETADO
    elif not enrollment.esta_completamente_pagado() and enrollment.matricula_pagada:
        # Prevención de retroceso en caso de reversión de pagos
        enrollment.estado = EstadoInscripcion.ACTIVO
    
    enrollment.updated_at = datetime.utcnow()
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
        
    modulo = enrollment.modulos[modulo_index]
    modulo.nota = round(nota, 2)
    
    if nota >= 64.0:
        modulo.estado_academico = "Aprobado"
    else:
        modulo.estado_academico = "Reprobado"

    # ========================================================================
    # ISSUE-P-RECALCULO-NOTA: pérdida de beca por módulo si no se mantiene la nota mínima
    # ========================================================================
    recalculo_necesario = False
    if (
        enrollment.nota_minima_beca is not None
        and modulo.costo_sin_beca_personal is not None
        and nota < enrollment.nota_minima_beca
        and modulo.costo != modulo.costo_sin_beca_personal
    ):
        modulo.costo = modulo.costo_sin_beca_personal
        recalculo_necesario = True

    notas_evaluadas = [m.nota for m in enrollment.modulos if m.nota is not None]
    if notas_evaluadas:
        promedio = sum(notas_evaluadas) / len(notas_evaluadas)
        enrollment.nota_final = round(promedio, 2)

    if recalculo_necesario:
        # El módulo afectado ya no vale lo mismo: recalculamos el total a pagar
        # (matrícula + costos de módulo actualizados). saldo_pendiente se actualiza
        # aquí también (aunque sea una aproximación) para no violar el validador del
        # modelo; el valor definitivo lo recompone actualizar_saldo_enrollment justo debajo.
        enrollment.total_a_pagar = round(
            enrollment.costo_matricula + sum(m.costo for m in enrollment.modulos), 2
        )
        enrollment.saldo_pendiente = round(max(0.0, enrollment.total_a_pagar - enrollment.total_pagado), 2)

    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()

    if recalculo_necesario:
        # Reconstruye monto_pagado/estado por módulo y saldo_pendiente global a partir
        # de los pagos históricos aprobados (misma cascada de ISSUE-F-PRORRATEO).
        # No modifica ni elimina ningún registro de Payment.
        await actualizar_saldo_enrollment(enrollment_id)
        enrollment = await Enrollment.get(enrollment_id)
    
    return enrollment


# ========================================================================
# ISSUE-Q-NOTA-BORRADOR: Notas de docente como borrador validado por CPD
# ========================================================================
async def subir_nota_borrador(
    enrollment_id: PydanticObjectId,
    modulo_index: int,
    nota_borrador: float
) -> Enrollment:
    """
    El docente propone una nota que queda como BORRADOR hasta que CPD la valide.
    No afecta nota_final ni la lógica de pérdida de beca (ISSUE-P-RECALCULO-NOTA).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")
    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise ValueError(f"Índice de módulo {modulo_index} fuera de rango")

    modulo = enrollment.modulos[modulo_index]
    modulo.nota_borrador = round(nota_borrador, 2)
    modulo.estado_validacion_nota = "pendiente_validacion"
    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()
    return enrollment


async def validar_nota_borrador(
    enrollment_id: PydanticObjectId,
    modulo_index: int,
    evaluador_username: str
) -> Enrollment:
    """
    CPD/Admin/Superadmin validan el borrador: lo convierte en nota oficial
    reutilizando actualizar_nota_modulo (mismo recálculo de promedio y beca).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")
    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise ValueError(f"Índice de módulo {modulo_index} fuera de rango")

    modulo = enrollment.modulos[modulo_index]
    if modulo.estado_validacion_nota != "pendiente_validacion" or modulo.nota_borrador is None:
        raise ValueError("Este módulo no tiene un borrador pendiente de validación")

    nota_a_oficializar = modulo.nota_borrador

    enrollment_actualizado = await actualizar_nota_modulo(
        enrollment_id=enrollment_id,
        modulo_index=modulo_index,
        nota=nota_a_oficializar,
        evaluador_username=evaluador_username
    )

    # actualizar_nota_modulo no toca nota_borrador/estado_validacion_nota; lo hacemos aquí
    enrollment_actualizado.modulos[modulo_index].estado_validacion_nota = "validada"
    enrollment_actualizado.modulos[modulo_index].nota_borrador = None
    await enrollment_actualizado.save()
    return enrollment_actualizado


async def rechazar_nota_borrador(
    enrollment_id: PydanticObjectId,
    modulo_index: int
) -> Enrollment:
    """
    CPD rechaza el borrador propuesto por el docente. No toca la nota oficial
    (que puede mantener un valor validado previamente, si existía).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")
    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise ValueError(f"Índice de módulo {modulo_index} fuera de rango")

    modulo = enrollment.modulos[modulo_index]
    if modulo.estado_validacion_nota != "pendiente_validacion":
        raise ValueError("Este módulo no tiene un borrador pendiente de validación")

    modulo.nota_borrador = None
    modulo.estado_validacion_nota = "sin_borrador"
    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()
    return enrollment
