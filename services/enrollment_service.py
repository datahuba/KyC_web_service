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
from models.enrollment import Enrollment, ModuloEstado, CargoAdicionalItemSnapshot
from models.student import Student
from models.course import Course
from models.enums import EstadoInscripcion
from schemas.enrollment import EnrollmentCreate
from beanie import PydanticObjectId
from models.discount import Discount
from beanie.operators import In, Or
# F-046 FIX: helpers de tiempo estaban solo importados localmente en
# enrich_enrollment_dates; al refactorizar core/timezone_utils se rompió
# el uso en 9 funciones (subir_nota_borrador, actualizar_saldo_enrollment,
# cambiar_estado_inscripcion, eximir_matricula, rechazar_nota_borrador).
# El síntoma fue 500 al calificar módulo (Sandra, audio 22/7 19:12).
from core.timezone_utils import utcnow_naive

async def create_enrollment(
    enrollment_in: EnrollmentCreate,
    admin_username: str,
    student: Optional[Student] = None,
    course: Optional[Course] = None,
    skip_link_updates: bool = False
) -> Enrollment:
    """
    Crear una nueva inscripción (solo admins)

    OPTIMIZACIÓN DE IMPORTACIÓN MASIVA (2026-07-09, ISSUE-Q-IMPORT-TIMEOUT):
    `student`/`course` permiten pasar objetos ya obtenidos en memoria para
    evitar los round-trips `Student.get()`/`Course.get()` cuando el llamador
    ya los tiene (ej. import_students_from_excel, donde el mismo `course` se
    reutiliza para decenas de estudiantes en una sola importación).

    `skip_link_updates=True` omite los `course.save()`/`student.save()` que
    agregan la referencia cruzada (course.inscritos / student.lista_cursos_ids)
    -- estos dos documentos NO tienen optimistic locking (`use_revision`), por
    lo que mutarlos y guardarlos de forma concurrente (ej. en un
    `asyncio.gather` sobre varios estudiantes) puede perder escrituras
    (last-writer-wins). El llamador que use este flag es responsable de
    actualizar esas referencias por su cuenta, idealmente en un solo batch
    después de que todas las inscripciones individuales ya se crearon.
    """
    # 1. Obtener estudiante y curso (si no se proveyeron ya en memoria)
    if student is None:
        student = await Student.get(enrollment_in.estudiante_id)
        if not student:
            raise ValueError(f"Estudiante {enrollment_in.estudiante_id} no encontrado")

    if course is None:
        course = await Course.get(enrollment_in.curso_id)
        if not course:
            raise ValueError(f"Curso {enrollment_in.curso_id} no encontrado")

    # AUDITORÍA (MEDIO #7): create_enrollment_request (solicitud del propio
    # estudiante) sí valida curso.activo, pero esta vía directa (CPD/Encargado
    # de Curso) no lo hacía -- dos rutas de entrada con validación asimétrica,
    # permitiendo inscribir gente en cursos ya desactivados/cerrados.
    # F-HISTORICO (2026-08-03, Kevin): los programas historicos (es_historico=True)
    # SIEMPRE deben aceptar inscripciones, porque su proposito es cargar
    # retroactivamente estudiantes que cursaron en el pasado. El flag activo
    # puede estar en False (cerrado) pero es_historico=True significa que
    # es solo para carga historica, no operativo.
    if not course.activo and not course.es_historico:
        raise ValueError("Este curso no está activo y no acepta nuevas inscripciones")

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
    
    # 3. ISSUE-P-PRECIO-UNICO (2026-07-08): el precio del programa es el
    # mismo para todos los estudiantes, sin importar procedencia/tipo.
    
    # 4. Obtener precios del curso (precio único)
    costo_total = course.get_costo_total()
    costo_matricula = course.get_matricula()

    # F-HISTORICO-IMPORT (2026-08-03, Kevin): los programas historicos pueden
    # tener cantidad_cuotas=0 (no se exige en historicos). Enrollment requiere
    # >= 1, asi que forzamos a 1 cuando es historico y no tiene cuotas.
    cantidad_cuotas_efectiva = course.cantidad_cuotas
    if course.es_historico and cantidad_cuotas_efectiva < 1:
        cantidad_cuotas_efectiva = 1
    
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

    # Total con SOLO descuento del curso (referencia para distribución de
    # módulos sin beca personal)
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

    # F-LOGICA-DESCUENTOS-MAX (2026-08-05, Kevin): "se queda con el descuento
    # de mayor porcentaje". Si el personal es menor, gana el curso y se
    # descarta el personal (el endpoint avisa al usuario).
    descuento_efectivo = max(descuento_curso, descuento_personal)

    colegiatura_final = costo_total - (costo_total * descuento_efectivo / 100)

    # ISSUE-P-CARGO-MULTIITEM: suma de todos los ítems de cargo adicional/
    # complementario al programa (ej. varios talleres incluidos). NINGÚN
    # ítem recibe descuentos de curso/estudiante -- se cobran íntegros.
    cargo_adicional = course.get_cargo_adicional_total()
    
    # MATEMÁTICA FINANCIERA:
    total_final = colegiatura_final + costo_matricula + cargo_adicional

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
        costo_total=costo_total,
        costo_matricula=costo_matricula,
        cantidad_cuotas=cantidad_cuotas_efectiva,
        modulos=modulos_enrollment,
        
        descuento_curso_id=descuento_curso_id,
        descuento_curso_aplicado=descuento_curso,
        descuento_estudiante_id=descuento_estudiante_id,
        descuento_personalizado=descuento_personal,

        # ISSUE-P-CARGO-MULTIITEM: snapshot de la lista de ítems de cargo
        # adicional al momento de inscribirse (si el curso los tenía
        # definidos en ese momento).
        cargo_adicional_items=[
            CargoAdicionalItemSnapshot(nombre=item.nombre, costo=item.costo)
            for item in course.cargo_adicional_items
        ],
        
        total_a_pagar=round(total_final, 2),
        saldo_pendiente=round(total_final, 2),
        estado=EstadoInscripcion.PENDIENTE_PAGO,
        matricula_pagada=False,
        requisitos=requisitos_enrollment,
        nota_minima_beca=nota_minima_snapshot  # ISSUE-P-RECALCULO-NOTA
    )
    
    await enrollment.insert()
    
    # 10. Agregar estudiante a la lista / 11. Agregar curso al estudiante
    # (omitido si skip_link_updates=True -- ver docstring de esta función)
    if not skip_link_updates:
        if enrollment_in.estudiante_id not in course.inscritos:
            course.inscritos.append(enrollment_in.estudiante_id)
            await course.save()

        if enrollment_in.curso_id not in student.lista_cursos_ids:
            student.lista_cursos_ids.append(enrollment_in.curso_id)
            await student.save()
    
    return enrollment


async def enrich_enrollment_dates(enrollment: Enrollment) -> dict:
    from core.timezone_utils import utcnow_naive, to_bolivia_time
    enrollment_dict = enrollment.model_dump()
    enrollment_dict["fecha_inscripcion"] = to_bolivia_time(enrollment.fecha_inscripcion)
    enrollment_dict["created_at"] = to_bolivia_time(enrollment.created_at)
    enrollment_dict["updated_at"] = to_bolivia_time(enrollment.updated_at)

    # F-LOGICA-DESCUENTOS-MAX (2026-08-05, Kevin): exponer al frontend el
    # descuento que REALMENTE se aplicó y de dónde viene, para que pueda
    # mostrar el mensaje "se aplicó el mayor (X%)" cuando corresponda.
    desc_curso = float(enrollment.descuento_curso_aplicado or 0)
    desc_personal = float(enrollment.descuento_personalizado or 0) if enrollment.descuento_personalizado is not None else 0.0
    descuento_efectivo = max(desc_curso, desc_personal)
    if descuento_efectivo > 0 and desc_personal > 0 and desc_curso >= desc_personal:
        # El personal fue menor, se aplicó el curso (se descarta el personal)
        origen = "curso"
        advertencia = (
            f"El descuento personal seleccionado ({desc_personal:.0f}%) es menor al "
            f"descuento del curso ({desc_curso:.0f}%). Se aplicó el descuento de mayor "
            f"porcentaje: el del curso ({desc_curso:.0f}%)."
        )
    elif descuento_efectivo > 0 and desc_personal > desc_curso:
        origen = "personal"
        advertencia = None
    elif descuento_efectivo > 0 and desc_curso > 0:
        origen = "curso"
        advertencia = None
    else:
        origen = "ninguno"
        advertencia = None
    enrollment_dict["descuento_efectivo"] = descuento_efectivo
    enrollment_dict["descuento_efectivo_origen"] = origen
    enrollment_dict["advertencia_descuento"] = advertencia
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
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    con_descuento: Optional[bool] = None,
    descuento_id: Optional[PydanticObjectId] = None,
    requiere_accion_documentos: Optional[bool] = None
) -> tuple[List[Enrollment], int]:
    """
    cursos_permitidos (ISSUE-R-ROLES): si se provee (no None), restringe los resultados
    únicamente a inscripciones de esos cursos. Se usa para segmentar el rol ENCARGADO_CURSO
    (y en el futuro COBRANZA, ISSUE-P-SEGMENTACION) a sus cursos asignados.

    con_descuento/descuento_id (fix 2026-07-09, reportado por el usuario: "no pude
    seleccionar los que están con descuento y cuál descuento"): permiten filtrar
    la tabla de inscripciones por si tienen algún descuento personal aplicado
    (True) o no (False), y opcionalmente por un Discount específico.
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
    if descuento_id:
        query = query.find(Enrollment.descuento_estudiante_id == descuento_id)
    elif con_descuento is True:
        query = query.find(
            Or(
                Enrollment.descuento_estudiante_id != None,
                Enrollment.descuento_personalizado > 0
            )
        )
    elif con_descuento is False:
        query = query.find(
            Enrollment.descuento_estudiante_id == None,
            Or(Enrollment.descuento_personalizado == None, Enrollment.descuento_personalizado <= 0)
        )
        
    if requiere_accion_documentos:
        # ISSUE-Q-DOCUMENTOS-KYC: Filtrar inscripciones que tengan algún documento pendiente de validación o subida
        query = query.find({"requisitos.estado": {"$in": ["pendiente", "en_proceso", "rechazado", "sin_subir"]}})
        
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
    descuento_personalizado: Optional[float],
    admin_username: str,
    descuento_id: Optional[PydanticObjectId] = None
) -> Enrollment:
    """
    AUDITORÍA (CRÍTICO #3): antes solo recalculaba total_a_pagar/saldo_pendiente
    a nivel global, sin tocar el costo de cada módulo individual ni disparar
    actualizar_saldo_enrollment -- el kardex por módulo (usado para el
    prorrateo en cascada) quedaba desincronizado del nuevo total. Ahora se
    redistribuye el costo por módulo con la misma proporción que
    create_enrollment, y se llama a la cascada real al final para que
    monto_pagado/estado por módulo y el estado de la inscripción queden
    consistentes con los pagos históricos ya aprobados.

    BUG ENCONTRADO (2026-07-09, reportado por el usuario: "asigné la beca
    pero no veo el recálculo"): `EnrollmentUpdate.descuento_id` existía en el
    schema desde siempre, pero esta función SOLO leía `descuento_personalizado`
    (el porcentaje libre) -- si el CPD seleccionaba un `Discount` real del
    combo "Descuento Personal (Beca)", ese `descuento_id` se ignoraba en
    silencio y el porcentaje aplicado quedaba en 0 (o en el valor libre
    anterior), sin recalcular nada. Ahora, si se provee `descuento_id`, se
    resuelve el `Discount` real (igual que en `create_enrollment`) y se usa
    su porcentaje; `descuento_personalizado` sigue funcionando como
    porcentaje libre si no se selecciona un `Discount` concreto.
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    descuento_estudiante_id = enrollment.descuento_estudiante_id
    nota_minima_snapshot = enrollment.nota_minima_beca

    if descuento_id is not None:
        discount_sel = await Discount.get(descuento_id)
        if not discount_sel:
            raise ValueError(f"Descuento {descuento_id} no encontrado")
        if not discount_sel.activo:
            raise ValueError(f"El descuento '{discount_sel.nombre}' no está activo")
        descuento_personalizado = discount_sel.porcentaje
        descuento_estudiante_id = discount_sel.id
        nota_minima_snapshot = discount_sel.nota_minima_requerida
    elif descuento_personalizado is not None:
        # Porcentaje libre (sin vincular a un Discount concreto): se limpia
        # la referencia a un Discount anterior, si había, para no dejar un
        # descuento_estudiante_id apuntando a un porcentaje que ya no aplica.
        descuento_estudiante_id = None
        nota_minima_snapshot = None
    else:
        descuento_personalizado = enrollment.descuento_personalizado or 0.0

    total_con_descuento_curso = enrollment.costo_total - (enrollment.costo_total * enrollment.descuento_curso_aplicado / 100)
    # F-LOGICA-DESCUENTOS-MAX (2026-08-05, Kevin): "se queda con el descuento
    # de mayor porcentaje". Si el personal es menor, se descarta y se avisa.
    descuento_efectivo_rec = max(enrollment.descuento_curso_aplicado, descuento_personalizado)
    colegiatura_final = enrollment.costo_total - (enrollment.costo_total * descuento_efectivo_rec / 100)
    # ISSUE-P-CARGO-MULTIITEM: el cargo adicional (snapshot de ítems de esta
    # inscripción) se mantiene fuera del recálculo por descuento -- ningún
    # ítem recibe descuentos de curso/estudiante, se preserva íntegro.
    total_final = colegiatura_final + enrollment.costo_matricula + enrollment.get_cargo_adicional_total()

    # Redistribuir el costo de cada módulo con la misma proporción que tenía
    # el curso original (mismo patrón que create_enrollment), preservando
    # monto_pagado/nota/estado_academico de cada ModuloEstado. También se
    # recalcula costo_sin_beca_personal (ISSUE-P-RECALCULO-NOTA) usando la
    # misma proporción, para que la pérdida de beca por nota siga funcionando
    # correctamente después de reasignar el descuento desde este endpoint.
    if enrollment.modulos:
        suma_costo_modulos_actual = sum(m.costo for m in enrollment.modulos)
        total_asignado = 0.0
        total_asignado_sin_beca = 0.0
        for i, mod in enumerate(enrollment.modulos):
            es_ultimo = i == len(enrollment.modulos) - 1
            if suma_costo_modulos_actual > 0:
                proporcion = mod.costo / suma_costo_modulos_actual
            else:
                proporcion = 1 / len(enrollment.modulos)

            if es_ultimo:
                mod.costo = max(0.0, round(colegiatura_final - total_asignado, 2))
            else:
                mod.costo = round(proporcion * colegiatura_final, 2)
                total_asignado += mod.costo

            if nota_minima_snapshot is not None:
                if es_ultimo:
                    mod.costo_sin_beca_personal = max(0.0, round(total_con_descuento_curso - total_asignado_sin_beca, 2))
                else:
                    mod.costo_sin_beca_personal = round(proporcion * total_con_descuento_curso, 2)
                    total_asignado_sin_beca += mod.costo_sin_beca_personal
            else:
                mod.costo_sin_beca_personal = None

    enrollment.descuento_personalizado = descuento_personalizado
    enrollment.descuento_estudiante_id = descuento_estudiante_id
    enrollment.nota_minima_beca = nota_minima_snapshot
    enrollment.total_a_pagar = round(total_final, 2)
    # Valor provisional para no violar el validador de saldo_pendiente antes
    # del primer save(); actualizar_saldo_enrollment recompone el definitivo
    # justo debajo a partir de los pagos históricos reales.
    enrollment.saldo_pendiente = round(max(0.0, total_final - enrollment.total_pagado), 2)
    enrollment.updated_at = utcnow_naive()
    
    await enrollment.save()

    await actualizar_saldo_enrollment(enrollment_id)
    return await Enrollment.get(enrollment_id)


async def cambiar_estado_enrollment(
    enrollment_id: PydanticObjectId,
    nuevo_estado: EstadoInscripcion,
    admin_username: str
) -> Enrollment:
    """
    AUDITORÍA (CRÍTICO #5): este endpoint genérico (PATCH /enrollments/{id})
    permitía fijar estado=SUSPENDIDO directamente, sin pasar por
    PassiveRequest ni congelado_service -- sin motivo_suspension, sin
    notificar al estudiante, sin cobrar la tasa de congelamiento. También
    permitía "sacar" una inscripción de SUSPENDIDO sin limpiar
    motivo_suspension/fecha_congelamiento/multa_reincorporacion_pendiente,
    dejando esos campos inconsistentes con el nuevo estado. Ambos casos
    ahora se bloquean explícitamente; deben usarse los endpoints dedicados
    (/passive-requests/, /enrollments/{id}/congelar,
    /enrollments/{id}/reactivar-congelado).

    F-083 (2026-07-28): también bloquea ir directo a RETIRADO. El retiro
    requiere registrar motivo_retiro, fecha_retiro, retirado_por, y debe
    usar el endpoint dedicado /enrollments/{id}/retirar.
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    if nuevo_estado == EstadoInscripcion.SUSPENDIDO:
        raise ValueError(
            "No se puede suspender una inscripción directamente. Usa el flujo de "
            "Solicitud de Pasivo o el de Congelamiento, que registran motivo y notifican al estudiante."
        )

    if nuevo_estado == EstadoInscripcion.RETIRADO:
        raise ValueError(
            "F-083: No se puede retirar una inscripción directamente. "
            "Usa el endpoint /enrollments/{id}/retirar que registra motivo_retiro y notifica al estudiante."
        )

    if enrollment.estado == EstadoInscripcion.SUSPENDIDO:
        raise ValueError(
            "Esta inscripción está suspendida (pasivo/congelado/abandono). "
            "Usa el endpoint de reactivación correspondiente en vez de cambiar el estado directamente."
        )

    if enrollment.estado == EstadoInscripcion.RETIRADO:
        raise ValueError(
            "F-083: Esta inscripción está RETIRADA. El retiro es definitivo: no se puede revertir a "
            "un estado anterior. Si el estudiante quiere volver, debe crear una nueva inscripción."
        )

    enrollment.estado = nuevo_estado
    enrollment.updated_at = utcnow_naive()

    await enrollment.save()
    return enrollment


# ========================================================================
# F-083 (2026-07-28): RETIRO VOLUNTARIO DE INSCRIPCIÓN
# ========================================================================
async def retirar_inscripcion(
    enrollment_id: PydanticObjectId,
    motivo_retiro: str,
    retirado_por: str,
    notificar_estudiante: bool = True
) -> Enrollment:
    """
    F-083 (2026-07-28): marca una inscripción como RETIRADO (abandono
    DEFINITIVO, no vuelve). Distinto de SUSPENDIDO+abandono (que es
    automático por inactividad y genera multa de reincorporación).

    Reglas de negocio (definidas con Lic. Sorich Cobranza y Lic. Sandra
    Zabala Cobranza, 2026-07-28 12:50 vía WhatsApp):
    - "retirados ya no vuelven, no son pasivos; pasivo tiene la opción
      de volver luego, y retirados ya no vuelven" (Lic. Sorich)
    - "esos ya no debería sumar sus pagos para cuentas por cobrar,
      solo queda lo que pagaron y se cierra" (Lic. Sorich)
    - El retiro es VOLUNTARIO (decisión del estudiante o del CPD/admin).
      Se diferencia del abandono automático (que es por inactividad y SÍ
      genera multa de reincorporación al volver).
    - El retiro NO es reversible. Si el estudiante se arrepiente, debe
      crear una nueva inscripción.
    - Lo que el estudiante YA pagó SÍ cuenta como ingreso (no se le
      descuenta). Lo que falta NO se cobra (no suma a "Por Cobrar").

    Args:
        enrollment_id: ID de la inscripción a retirar
        motivo_retiro: motivo del retiro (obligatorio, ej: 'cambio de
            ciudad', 'problemas económicos'). Se persiste en enrollment.
        retirado_por: username del usuario que ejecuta el retiro
            (admin/cpd/superadmin) o 'estudiante' si fue autoservicio.
        notificar_estudiante: si True (default), envía notification
            in-app al estudiante confirmando el retiro.

    Raises:
        ValueError: si la inscripción no existe, o si ya está en un
            estado terminal (COMPLETADO, CANCELADO, RETIRADO).

    Returns:
        Enrollment actualizado (estado=RETIRADO, motivo_retiro=...,
        fecha_retiro=now, retirado_por=...).
    """
    from core.timezone_utils import utcnow_naive

    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    # Validar estado actual: NO se puede retirar si ya es terminal
    estados_terminales = {
        EstadoInscripcion.COMPLETADO,
        EstadoInscripcion.CANCELADO,
        EstadoInscripcion.RETIRADO,
    }
    if enrollment.estado in estados_terminales:
        raise ValueError(
            f"F-083: No se puede retirar una inscripción en estado '{enrollment.estado.value}'. "
            f"El retiro es solo para inscripciones activas o suspendidas (pasivo/congelado)."
        )

    if not motivo_retiro or not motivo_retiro.strip():
        raise ValueError("F-083: El motivo del retiro es obligatorio.")

    # Marcar como RETIRADO (mantiene módulos, saldos, pagos históricos)
    estado_anterior = enrollment.estado
    enrollment.estado = EstadoInscripcion.RETIRADO
    enrollment.motivo_retiro = motivo_retiro.strip()
    enrollment.fecha_retiro = utcnow_naive()
    enrollment.retirado_por = retirado_por
    enrollment.updated_at = utcnow_naive()

    # Limpiar campos de suspensión si venía de SUSPENDIDO (porque ya no
    # está "suspendido", está "retirado" definitivo)
    if estado_anterior == EstadoInscripcion.SUSPENDIDO:
        enrollment.motivo_suspension = None
        enrollment.fecha_congelamiento = None
        enrollment.tasa_congelamiento_pagada = False
        enrollment.fecha_abandono = None
        enrollment.multa_reincorporacion_pendiente = False
        enrollment.mora_notificada = False

    await enrollment.save()

    # Notificar al estudiante
    if notificar_estudiante:
        try:
            from services.notification_service import create_notification
            await create_notification(
                destinatario_id=enrollment.estudiante_id,
                tipo_destinatario="student",
                titulo="Tu inscripción fue retirada",
                mensaje=(
                    f"Tu inscripción al curso fue marcada como RETIRADO. "
                    f"Motivo: {motivo_retiro.strip()}. "
                    f"Lo que ya pagaste queda registrado como ingreso a tu favor; "
                    f"no se te cobrará el saldo pendiente. "
                    f"Si tienes dudas, contacta al CPD."
                ),
                tipo_alerta="warning",
                ruta="/app/enrollments",
                referencia_tipo="enrollment",
                referencia_id=enrollment.id
            )
        except Exception as notif_err:
            # Si la notification falla, no rompemos el flujo principal
            import logging
            logging.getLogger("kyc.enrollment").warning(
                f"F-083: no se pudo notificar al estudiante {enrollment.estudiante_id}: {notif_err}"
            )

    return enrollment


# ========================================================================
# ISSUE-F-PRORRATEO: ALGORITMO FINANCIERO EN CASCADA (V2 - RECONSTRUCCIÓN ABSOLUTA)
# ========================================================================
async def actualizar_saldo_enrollment(
    enrollment_id: PydanticObjectId,
    monto_pago_aprobado: float = 0.0, # Se mantiene la firma por compatibilidad, pero ya no se usa ciegamente
    enrollment: Optional[Enrollment] = None,
    pagos_aprobados: Optional[list] = None
):
    """
    Reconstruye el saldo de la inscripción sumando todos los pagos históricos aprobados
    menos los anulados. Distribuye los fondos aprobados en cascada (Waterfall) reparando
    cualquier inconsistencia de base de datos.

    F-COBRANZA-014 (2026-07-21): ahora descuenta los pagos ANULADOS del `total_pagado`
    y `saldo_pendiente`. Antes, esos campos reflejaban solo la suma de aprobados,
    dejando un desfase de 3,534 BOB en producción que Joel detectó. La distribución
    de módulos (waterfall) sigue basándose en aprobados, ya que los módulos
    representan el estado ACADÉMICO histórico (un módulo que se pagó y luego se
    anuló queda en "Pagado" hasta que se reinscribe o se vuelve a pagar).

    F-085 (2026-07-28): REVERTIR la regla F-COBRANZA-014. La fórmula
    `total_pagado = aprobados - anulados` producía números NEGATIVOS en
    cualquier caso donde el monto del pago anulado era mayor que el resto
    aprobado (ej: Luis Fernando con matrícula 300 aprobado + Módulo 2940
    anulado → total_pagado = -2640). Esto rompía 5 endpoints financieros
    con ValidationError `total_pagado >= 0` y dejaba TODAS las páginas
    financieras en blanco.

    REGLA CORRECTA (idempotente, no produce negativos):
      `total_pagado = sum(pagos APROBADOS)`
    Al anular un pago aprobado, NO se resta del total — el pago simplemente
    deja de contar en aprobados. Esto es la misma regla que aplicamos en
    F-082 (Medardo) y F-084 (Anselmo) y es matemáticamente consistente.

    El "desfase" que F-COBRANZA-014 detectó en realidad era un BUG en la
    cascada (falla silenciosa de `actualizar_saldo_enrollment` por
    `RevisionIdWasChanged` que NO actualizaba `total_pagado` al aprobar).
    El fix correcto es el retry + notification (F-082), no la resta
    posterior de anulados.

    OPTIMIZACIÓN DE IMPORTACIÓN MASIVA (2026-07-09, ISSUE-Q-IMPORT-TIMEOUT):
    `enrollment`/`pagos_aprobados` permiten pasar el documento y los pagos ya
    obtenidos en memoria, evitando el `Enrollment.get()` + `Payment.find()`
    redundantes cuando el llamador (ej. import_students_from_excel) acaba de
    crear ambos en el mismo flujo.
    """
    from models.payment import Payment
    from models.enums import EstadoPago

    if enrollment is None:
        enrollment = await Enrollment.get(enrollment_id)
        if not enrollment:
            raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    # 1. Recolectar la verdad absoluta: ¿Cuánto dinero REALMENTE tiene aprobado este alumno?
    if pagos_aprobados is None:
        pagos_aprobados = await Payment.find(
            Payment.inscripcion_id == enrollment_id,
            Payment.estado_pago == EstadoPago.APROBADO
        ).to_list()

    # F-085: NO recolectar anulados ni restarlos. La regla es:
    #   total_pagado = sum(aprobados)
    # Los anulados ya no cuentan en aprobados (cambiaron de estado),
    # restarlos de nuevo = doble resta = números negativos.

    dinero_aprobado_bruto = sum(p.cantidad_pago for p in pagos_aprobados)
    # F-085: total_pagado = sum(aprobados). Sin restar anulados.
    dinero_neto_pagado = round(dinero_aprobado_bruto, 2)
    tanque_de_agua = round(dinero_aprobado_bruto, 2)  # waterfall con aprobados

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
    # F-085 (2026-07-28): `total_pagado = sum(aprobados)`. NO restar anulados
    # (la resta introducida por F-COBRANZA-014 producía números negativos).
    enrollment.total_pagado = dinero_neto_pagado
    enrollment.saldo_pendiente = max(0.0, round(enrollment.total_a_pagar - dinero_neto_pagado, 2))
    
    # 6. Evolución a "Completado" si la deuda llegó a cero
    if enrollment.esta_completamente_pagado() and enrollment.matricula_pagada:
        enrollment.estado = EstadoInscripcion.COMPLETADO
    elif not enrollment.esta_completamente_pagado() and enrollment.matricula_pagada:
        # Prevención de retroceso en caso de reversión de pagos
        enrollment.estado = EstadoInscripcion.ACTIVO
    elif enrollment.matricula_exenta and enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO:
        # ISSUE-M-EXENCION: MAE autorizó cursar sin haber pagado la matrícula.
        # NO se toca matricula_pagada (sigue reflejando la realidad financiera
        # para reportes/caja); solo se desbloquea el estado académico.
        enrollment.estado = EstadoInscripcion.ACTIVO
    
    enrollment.updated_at = utcnow_naive()
    await enrollment.save()


# ========================================================================
# ISSUE-M-EXENCION: BYPASS DE MATRÍCULA (SOLO MAE)
# ========================================================================
async def otorgar_matricula_exenta(enrollment_id: PydanticObjectId, otorgado_por: str) -> Enrollment:
    """
    Autoriza a un estudiante a cursar académicamente SIN haber pagado la
    matrícula institucional. NO condona la deuda: `saldo_pendiente` y
    `matricula_pagada` siguen reflejando la realidad financiera exacta
    (Cobranza sigue viendo y cobrando la deuda con normalidad).

    Solo desbloquea el estado académico (`estado` pasa a ACTIVO) para que
    el estudiante pueda acceder a módulos/aula virtual mientras se resuelve
    su situación de matrícula.
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    if enrollment.estado in (EstadoInscripcion.COMPLETADO, EstadoInscripcion.CANCELADO):
        raise ValueError(f"No se puede otorgar exención sobre una inscripción en estado '{enrollment.estado.value}'")

    enrollment.matricula_exenta = True
    enrollment.matricula_exenta_otorgada_por = otorgado_por
    enrollment.matricula_exenta_fecha = utcnow_naive()

    # Desbloqueo académico inmediato (no depende de que llegue un pago nuevo)
    if enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO:
        enrollment.estado = EstadoInscripcion.ACTIVO

    enrollment.updated_at = utcnow_naive()
    await enrollment.save()
    return enrollment


async def revocar_matricula_exenta(enrollment_id: PydanticObjectId) -> Enrollment:
    """
    Revoca una exención de matrícula previamente otorgada. Si la matrícula
    real sigue sin pagarse, el estado académico vuelve a PENDIENTE_PAGO
    (se re-bloquea el acceso). Si mientras tanto ya se pagó la matrícula de
    forma real, el estado ACTIVO se mantiene por la vía normal.
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError(f"Inscripción {enrollment_id} no encontrada")

    if not enrollment.matricula_exenta:
        raise ValueError("Esta inscripción no tiene una exención de matrícula activa")

    enrollment.matricula_exenta = False

    if not enrollment.matricula_pagada and enrollment.estado == EstadoInscripcion.ACTIVO:
        enrollment.estado = EstadoInscripcion.PENDIENTE_PAGO

    enrollment.updated_at = utcnow_naive()
    await enrollment.save()
    return enrollment


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

    enrollment.updated_at = utcnow_naive()
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
    enrollment.updated_at = utcnow_naive()
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
    nombre_modulo = modulo.nombre

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

    # ISSUE-Q-CORREO-NOTA (2026-07-08, reunión de postgrado contaduría): notificar
    # al estudiante por correo cuando CPD valida su nota. No bloqueante: si el
    # estudiante no tiene email o el envío falla, no revierte la validación.
    try:
        from models.student import Student
        from models.course import Course
        from core.email_utils import send_email, build_nota_validada_email
        from core.config import settings
        from services.notification_service import create_notification

        student = await Student.get(enrollment_actualizado.estudiante_id)
        course = await Course.get(enrollment_actualizado.curso_id)

        if student:
            try:
                await create_notification(
                    destinatario_id=student.id,
                    tipo_destinatario="student",
                    titulo="Calificación Validada",
                    mensaje=f"Tu nota del módulo '{nombre_modulo}' ya fue validada oficialmente por CPD.",
                    tipo_alerta="success",
                    ruta="/app/enrollments",
                    referencia_tipo="enrollment",
                    referencia_id=enrollment_actualizado.id
                )
            except Exception as e:
                print(f"Error notificando validación de nota al estudiante: {str(e)}")

            if student.email and course:
                portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/enrollments"
                html = build_nota_validada_email(
                    nombre=student.nombre or student.registro,
                    curso_nombre=course.nombre_programa,
                    modulo_nombre=nombre_modulo,
                    nota=nota_a_oficializar,
                    portal_link=portal_link
                )
                await send_email(
                    student.email,
                    f"Nota validada: {nombre_modulo} · Posgrado UAGRM",
                    html
                )
    except Exception as e:
        print(f"Error enviando correo de nota validada: {str(e)}")

    return enrollment_actualizado


async def rechazar_nota_borrador(
    enrollment_id: PydanticObjectId,
    modulo_index: int
) -> Enrollment:
    """
    CPD rechaza el borrador propuesto por el docente. No toca la nota oficial
    (que puede mantener un valor validado previamente, si existía).

    F-050 (2026-07-22, audios viejos): antes NO recalculaba `nota_final`
    (promedio) tras rechazar, así que el promedio podía seguir sumando el
    borrador rechazado. Fix: recalcular SIEMPRE el promedio, igual que
    `validar_nota_borrador` y `actualizar_nota_modulo`.
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

    # F-050 FIX: recalcular el promedio igual que en actualizar_nota_modulo
    # y validar_nota_borrador. Sin esto, el promedio podía seguir sumando
    # la nota rechazada en alguna vista de UI / reportes.
    notas_evaluadas = [m.nota for m in enrollment.modulos if m.nota is not None]
    if notas_evaluadas:
        promedio = sum(notas_evaluadas) / len(notas_evaluadas)
        enrollment.nota_final = round(promedio, 2)
    else:
        # Sin notas válidas, no hay promedio. Mantener como None.
        enrollment.nota_final = None

    enrollment.updated_at = utcnow_naive()
    await enrollment.save()
    return enrollment
