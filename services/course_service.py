"""
Servicio de Cursos
==================

Lógica de negocio para cursos (Funciones).
"""

from typing import List, Optional, Dict, Any, Union
from models.course import Course
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

from models.enums import TipoCurso, Modalidad
from beanie.operators import Or

async def get_courses(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    activo: Optional[bool] = None,
    tipo_curso: Optional[TipoCurso] = None,
    modalidad: Optional[Modalidad] = None
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
    return courses, total_count

async def create_course(course_in: CourseCreate) -> Course:
    """Crea un nuevo curso"""
    payload = course_in.dict()

    # Seguridad de negocio: impedir asociar descuentos inactivos
    await _validate_active_discount(payload.get("descuento_id"))

    # Normalización defensiva: costos externos opcionales se persisten en 0
    if payload.get("costo_total_externo") is None:
        payload["costo_total_externo"] = 0
    if payload.get("matricula_externo") is None:
        payload["matricula_externo"] = 0

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
        
    for field, value in update_data.items():
        setattr(course, field, value)
        
    await course.save()
    return course

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
                "tipo_estudiante": enrollment.es_estudiante_interno
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
