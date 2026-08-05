"""
Servicio de Cursos
==================

Lógica de negocio para cursos (Funciones).
"""

from datetime import datetime
from typing import List, Optional, Dict, Any, Union
from models.course import Course, calcular_estado_actual
from models.enrollment import Enrollment
from models.student import Student
from models.discount import Discount
from schemas.course import CourseCreate, CourseUpdate, CourseEnrolledStudent
from beanie import PydanticObjectId


async def _validate_active_discount(discount_id: Optional[PydanticObjectId]) -> None:
    """Valida que el descuento exista y esté activo cuando se usa en cursos."""
    if not discount_id:
        return

    discount = await Discount.get(discount_id)
    if not discount:
        raise ValueError("El descuento seleccionado no existe")

    if not discount.activo:
        raise ValueError("El descuento seleccionado está inactivo y no puede aplicarse al curso")

async def get_course(id: PydanticObjectId) -> Optional[Course]:
    """Obtiene un curso por su ID"""
    return await Course.get(id)

from models.enums import TipoCurso, Modalidad, EstadoRequisito
from beanie.operators import Or

async def get_courses(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    activo: Optional[bool] = None,
    tipo_curso: Optional[TipoCurso] = None,
    modalidad: Optional[Modalidad] = None,
    estado: Optional[str] = None,
) -> tuple[List[Course], int]:
    """
    Obtiene múltiples cursos con paginación y filtros

    Args:
        page: Número de página
        per_page: Elementos por página
        q: Búsqueda por nombre o código
        activo: Filtrar por estado activo/inactivo
        tipo_curso: Filtrar por tipo de curso
        modalidad: Filtrar por modalidad
        estado: F-080 — filtrar por estado calculado del programa
            (programado | en_ejecucion | cerrado). Como el estado se
            calcula en runtime según fechas, se trae un set más amplio
            y se filtra en memoria (es aceptable hasta ~500 cursos).
    """
    query = Course.find()

    # 1. Búsqueda por texto (q)
    if q:
        regex_pattern = {"$regex": q, "$options": "i"}
        query = query.find(
            Or(
                Course.nombre_programa == regex_pattern,
                Course.codigo == regex_pattern
            )
        )

    # 2. Filtro Activo
    if activo is not None:
        query = query.find(Course.activo == activo)

    # 3. Filtro Tipo Curso
    if tipo_curso:
        query = query.find(Course.tipo_curso == tipo_curso)

    # 4. Filtro Modalidad
    if modalidad:
        query = query.find(Course.modalidad == modalidad)

    total_count = await query.count()
    skip = (page - 1) * per_page
    courses = await query.sort("-created_at").skip(skip).limit(per_page).to_list()

    # F-080: filtro en memoria por estado calculado
    if estado:
        courses = [c for c in courses if c.get_estado_actual() == estado]

    return courses, total_count

async def create_course(course_in: CourseCreate) -> Course:
    """Crea un nuevo curso"""
    payload = course_in.dict()

    # Seguridad de negocio: impedir asociar descuentos inactivos
    await _validate_active_discount(payload.get("descuento_id"))

    course = Course(**payload)
    await course.create()
    return course

async def update_course(
    course: Course, 
    course_in: Union[CourseUpdate, Dict[str, Any]]
) -> Course:
    """Actualiza un curso existente"""
    if isinstance(course_in, dict):
        update_data = course_in
    else:
        update_data = course_in.dict(exclude_unset=True)

    # Seguridad de negocio: impedir asociar descuentos inactivos
    if "descuento_id" in update_data:
        await _validate_active_discount(update_data.get("descuento_id"))

    # ISSUE-Q-DOCUMENTOS-KYC (2026-07-09): detectar si se están cambiando los
    # requisitos/documentos del curso para propagarlos a las inscripciones ya
    # existentes (los requisitos se copian al inscribirse, así que sin esto los
    # estudiantes ya inscritos nunca verían los documentos definidos después).
    requisitos_actualizados = "requisitos" in update_data

    for field, value in update_data.items():
        setattr(course, field, value)
        
    await course.save()

    if requisitos_actualizados:
        await _sincronizar_requisitos_inscripciones(course)

    return course


async def _sincronizar_requisitos_inscripciones(course: Course) -> None:
    """
    Propaga la plantilla de requisitos del curso a las inscripciones existentes.

    - AGREGA a cada inscripción los requisitos del curso que aún no tenga
      (comparando por descripción), con estado "pendiente".
    - PRESERVA los requisitos ya subidos/aprobados/rechazados por el estudiante
      (nunca pisa un documento existente ni su estado).
    - QUITA de la inscripción los requisitos que el curso ya no exige, SOLO si
      el estudiante todavía no subió nada para ellos (estado "pendiente"); si ya
      había subido algo, se conserva para no perder su documento.
    """
    from models.enums import EstadoInscripcion

    descripciones_curso = [r.descripcion for r in course.requisitos]
    enrollments = await Enrollment.find(
        Enrollment.curso_id == course.id,
        Enrollment.estado != EstadoInscripcion.CANCELADO
    ).to_list()

    for enr in enrollments:
        existentes = {r.descripcion: r for r in enr.requisitos}
        nuevos_requisitos = []

        # Conservar los que siguen exigidos + los que el estudiante ya trabajó
        for req in enr.requisitos:
            if req.descripcion in descripciones_curso:
                nuevos_requisitos.append(req)
            elif req.estado != EstadoRequisito.PENDIENTE:
                # El curso ya no lo exige, pero el estudiante ya subió algo: se conserva.
                nuevos_requisitos.append(req)

        # Agregar los nuevos requisitos del curso que la inscripción no tenía
        for template in course.requisitos:
            if template.descripcion not in existentes:
                nuevos_requisitos.append(template.to_requisito())

        enr.requisitos = nuevos_requisitos
        await enr.save()

async def delete_course(id: PydanticObjectId) -> Optional[Course]:
    """Elimina un curso"""
    course = await Course.get(id)
    if course:
        await course.delete()
    return course

async def get_course_students(course_id: PydanticObjectId) -> List[CourseEnrolledStudent]:
    """
    Obtiene la lista detallada de estudiantes inscritos en un curso.
    Combina datos de Enrollment y Student.
    """
    # 1. Obtener todas las inscripciones del curso
    enrollments = await Enrollment.find(Enrollment.curso_id == course_id).to_list()

    if not enrollments:
        return []

    # 2. Obtener IDs de estudiantes
    student_ids = [e.estudiante_id for e in enrollments]

    # 3. Obtener estudiantes en una sola consulta (optimización)
    from beanie.operators import In
    students = await Student.find(In(Student.id, student_ids)).to_list()
    students_map = {s.id: s for s in students}

    # 4. Construir reporte
    report = []
    for enrollment in enrollments:
        student = students_map.get(enrollment.estudiante_id)
        if not student:
            continue  # Skip si no se encuentra el estudiante (caso raro de inconsistencia)

        # Calcular porcentaje de avance
        avance = 0.0
        if enrollment.total_a_pagar > 0:
            avance = (enrollment.total_pagado / enrollment.total_a_pagar) * 100
        elif enrollment.total_a_pagar == 0:
            avance = 100.0

        # Crear objeto de reporte
        item = CourseEnrolledStudent(
            estudiante_id=student.id,
            nombre=student.nombre or "Sin nombre",
            carnet=student.carnet or None,
            contacto={
                "email": student.email or None,
                "celular": student.celular or None
            },
            inscripcion={
                "id": enrollment.id,
                "fecha_inscripcion": enrollment.fecha_inscripcion,
                "estado": enrollment.estado,
                # F-HISTORICO-EXCEL-ESTADO (2026-08-04): exponer el flag
                # matricula_pagada para que el frontend pueda mostrar el
                # badge correcto cuando la UI del modal 'Estudiantes
                # Inscritos' lo necesite.
                "matricula_pagada": enrollment.matricula_pagada,
            },
            financiero={
                "total_a_pagar": enrollment.total_a_pagar,
                "total_pagado": enrollment.total_pagado,
                "saldo_pendiente": enrollment.saldo_pendiente,
                "avance_pago": round(avance, 2)
            }
        )
        report.append(item)

    return report


# ============================================================================
# F-080: Calendario de programas + filtro para estudiantes
# ============================================================================

async def get_courses_para_calendario(
    year: Optional[int] = None,
    tipo_curso: Optional[TipoCurso] = None,
    estado: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    F-080: devuelve todos los cursos formateados para mostrar en la vista
    de calendario (Timeline o Lista Cronológica).

    El estado se calcula en runtime (ver `Course.get_estado_actual`) y se
    incluye en cada item.

    Args:
        year: filtrar por año de `fecha_inicio` (o `fecha_fin` si no
            tiene inicio). Si no se pasa, devuelve todos.
        tipo_curso: filtro opcional por tipo.
        estado: filtro opcional por estado calculado.

    Returns:
        Lista de dicts con la metadata del programa + `estado_calculado`.
    """
    query = Course.find()
    if tipo_curso:
        query = query.find(Course.tipo_curso == tipo_curso)

    courses = await query.to_list()

    # F-CALENDARIO-FIX-2 (2026-07-30): contar inscritos REALES (no todos los
    # IDs historicos). El campo Course.inscritos contiene TODOS los IDs
    # que se fueron agregando, incluyendo cancelados/retirados que ya no
    # cuentan como inscritos. Para evitar duplicar la logica de "que es un
    # inscrito" en el frontend y mantener consistencia con la tabla de
    # enrollments, hacemos una query cross-collection aqui.
    #
    # Estados que NO cuentan como inscrito: CANCELADO (nunca curso).
    # Estados que SI cuentan: PENDIENTE_PAGO, ACTIVO, SUSPENDIDO,
    # COMPLETADO, RETIRADO.
    from models.enrollment import Enrollment
    from models.enums import EstadoInscripcion

    # Pre-cargar counts de inscritos por curso en una sola query
    # F-CALENDARIO-FIX-3 (2026-07-30): Beanie 1.30 no soporta
    # `.in_()` con ExpressionField (lanza 'ExpressionField object is not
    # callable'). Usamos find con dict de Mongo directo.
    estados_validos_values = [
        EstadoInscripcion.PENDIENTE_PAGO.value,
        EstadoInscripcion.ACTIVO.value,
        EstadoInscripcion.SUSPENDIDO.value,
        EstadoInscripcion.COMPLETADO.value,
        EstadoInscripcion.RETIRADO.value,
    ]
    course_ids = [c.id for c in courses]
    counts_por_curso: dict = {}
    try:
        # find() con dict de Mongo query directamente
        all_enrollments = await Enrollment.find(
            {"curso_id": {"$in": course_ids}, "estado": {"$in": estados_validos_values}}
        ).to_list()
        for e in all_enrollments:
            cid = str(e.curso_id)
            counts_por_curso[cid] = counts_por_curso.get(cid, 0) + 1
    except Exception as e:
        # Si falla la query, fallback a len(c.inscritos)
        import logging
        logging.warning(f"[calendario] no se pudo contar inscritos via Beanie: {e}")

    items: List[Dict[str, Any]] = []
    for c in courses:
        # Filtro por año: si tiene fecha_inicio usamos esa, sino fecha_fin
        ref_date = c.fecha_inicio or c.fecha_fin
        if year and ref_date and ref_date.year != year:
            continue
        if year and not ref_date:
            # Sin fechas: solo incluir si el año es "todos" (no se pasó)
            continue

        estado_calculado = c.get_estado_actual()
        if estado and estado_calculado != estado:
            continue

        items.append({
            "id": str(c.id),
            "codigo": c.codigo,
            "nombre_programa": c.nombre_programa,
            "tipo_curso": c.tipo_curso.value if hasattr(c.tipo_curso, "value") else c.tipo_curso,
            "modalidad": c.modalidad.value if hasattr(c.modalidad, "value") else c.modalidad,
            "fecha_inicio": c.fecha_inicio,
            "fecha_fin": c.fecha_fin,
            "estado_calculado": estado_calculado,
            "estado_override": c.estado_override,
            "resolucion_pdf_url": c.resolucion_pdf_url,
            "activo": c.activo,
            "costo_total_interno": c.costo_total_interno,
            "matricula_interno": c.matricula_interno,
            "cantidad_modulos": len(c.modulos or []),
            "cantidad_inscritos": counts_por_curso.get(str(c.id), len(c.inscritos or [])),
        })

    # Orden cronológico: cursos sin fecha al final
    def _sort_key(item: Dict[str, Any]) -> datetime:
        d = item.get("fecha_inicio") or item.get("fecha_fin")
        return d if d else datetime(9999, 12, 31)

    items.sort(key=_sort_key)
    return items


async def get_courses_disponibles_para_estudiante() -> List[Course]:
    """
    F-080 + F-US-006-3TIPOS (2026-08-04): devuelve los cursos en los que un
    estudiante PODRÍA pedir inscripción. Tras el cambio de Kevin, solo los
    cursos en estado PROGRAMADO aceptan nuevas inscripciones de estudiantes.
    Un programa en_ejecucion, cerrado o histórico NO aparece en esta lista
    (los ya inscritos lo ven en su "mis programas", pero nadie nuevo puede
    unirse por su cuenta).

    Se delega al helper `Course.acepta_inscripciones()` para que la regla
    viva en un solo lugar.
    """
    from models.enums import EstadoPrograma

    courses = await Course.find(Course.activo == True).to_list()
    return [c for c in courses if c.acepta_inscripciones()]


async def set_estado_override(
    course_id: PydanticObjectId,
    estado_override: Optional[str],
) -> Course:
    """
    F-080: CPD define o limpia el override manual de estado de un curso.
    Si `estado_override` es None, vuelve al cálculo automático por fechas.
    Si es un valor inválido, lanza ValueError.
    """
    from models.enums import EstadoPrograma

    course = await Course.get(course_id)
    if not course:
        raise ValueError("Curso no encontrado")

    if estado_override is not None:
        try:
            EstadoPrograma(estado_override)
        except ValueError:
            raise ValueError(
                f"Estado inválido. Valores permitidos: "
                f"{', '.join(e.value for e in EstadoPrograma)}"
            )

    course.estado_override = estado_override
    # Si el override es None, sincronizamos `estado` al cálculo actual
    # (para que el campo persistido no quede stale).
    course.estado = course.get_estado_actual()
    await course.save()
    return course


async def set_resolucion_pdf_url(
    course_id: PydanticObjectId,
    pdf_url: str,
) -> Course:
    """
    F-080: persiste la URL del PDF de la resolución de respaldo del
    programa. `pdf_url` puede ser una URL de Cloudinary, S3, o local.
    """
    course = await Course.get(course_id)
    if not course:
        raise ValueError("Curso no encontrado")
    course.resolucion_pdf_url = pdf_url
    await course.save()
    return course
