"""
Servicio de Inscripciones
=========================

Lógica de negocio para inscripciones (Funciones).
Calcula montos automáticamente al crear una inscripción.
"""

from typing import List, Optional, Dict, Any, Union
from models.enrollment import Enrollment
from models.course import Course
from models.student import Student
from models.enums import TipoEstudiante
from schemas.enrollment import EnrollmentCreate, EnrollmentUpdate
from beanie import PydanticObjectId
from fastapi import HTTPException

async def get_enrollment(id: PydanticObjectId) -> Optional[Enrollment]:
    """Obtiene una inscripción por su ID"""
    return await Enrollment.get(id)

async def get_enrollments(skip: int = 0, limit: int = 100) -> List[Enrollment]:
    """Obtiene múltiples inscripciones con paginación"""
    return await Enrollment.find_all().skip(skip).limit(limit).to_list()

async def create_enrollment(enrollment_in: EnrollmentCreate) -> Enrollment:
    """
    Crea una inscripción validando y calculando montos
    """
    # 1. Obtener curso para precios
    course = await Course.get(enrollment_in.curso_id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
        
    # 2. Calcular montos según tipo de estudiante
    es_interno = enrollment_in.es_estudiante_interno == TipoEstudiante.INTERNO
    
    costo_total = course.costo_total_interno if es_interno else course.costo_total_externo
    
    # 3. Aplicar descuento personalizado si existe
    if enrollment_in.descuento_personalizado:
        descuento = costo_total * (enrollment_in.descuento_personalizado / 100)
        costo_total -= descuento
        
    # 4. Crear objeto
    enrollment_data = enrollment_in.dict()
    enrollment_data["total_a_pagar"] = costo_total
    enrollment_data["total_pagado"] = 0.0
    enrollment_data["saldo_pendiente"] = costo_total
    
    enrollment = Enrollment(**enrollment_data)
    await enrollment.create()
    
    # 5. Actualizar lista de inscritos en el curso
    if course.inscritos is None:
        course.inscritos = []
    course.inscritos.append(enrollment.id)
    await course.save()
    
    # 6. Actualizar lista de cursos en el estudiante
    student = await Student.get(enrollment_in.estudiante_id)
    if student:
        if student.lista_cursos_ids is None:
            student.lista_cursos_ids = []
        student.lista_cursos_ids.append(course.id)
        await student.save()
        
    return enrollment

async def update_enrollment(
    enrollment: Enrollment, 
    enrollment_in: Union[EnrollmentUpdate, Dict[str, Any]]
) -> Enrollment:
    """Actualiza una inscripción existente"""
    if isinstance(enrollment_in, dict):
        update_data = enrollment_in
    else:
        update_data = enrollment_in.dict(exclude_unset=True)
        
    for field, value in update_data.items():
        setattr(enrollment, field, value)
        
    await enrollment.save()
    return enrollment

async def delete_enrollment(id: PydanticObjectId) -> Optional[Enrollment]:
    """Elimina una inscripción"""
    enrollment = await Enrollment.get(id)
    if enrollment:
        await enrollment.delete()
    return enrollment
