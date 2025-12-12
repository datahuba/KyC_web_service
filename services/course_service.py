"""
Servicio de Cursos
==================

Lógica de negocio para cursos (Funciones).
"""

from typing import List, Optional, Dict, Any, Union
from models.course import Course
from models.enrollment import Enrollment
from models.student import Student
from schemas.course import CourseCreate, CourseUpdate, CourseEnrolledStudent
from beanie import PydanticObjectId

async def get_course(id: PydanticObjectId) -> Optional[Course]:
    """Obtiene un curso por su ID"""
    return await Course.get(id)

async def get_courses(skip: int = 0, limit: int = 100) -> List[Course]:
    """Obtiene múltiples cursos con paginación"""
    return await Course.find_all().skip(skip).limit(limit).to_list()

async def create_course(course_in: CourseCreate) -> Course:
    """Crea un nuevo curso"""
    course = Course(**course_in.dict())
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
