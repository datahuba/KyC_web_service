"""
Servicio de Classroom
=====================

Lógica de negocio para aulas virtuales e inscripción de estudiantes.
"""

from typing import List, Optional
from beanie import PydanticObjectId
from beanie.operators import In

from models.classroom import Classroom, ClassroomStudent
from models.student import Student
from schemas.classroom import ClassroomCreate, ClassroomUpdate


async def get_classroom(classroom_id: PydanticObjectId) -> Optional[Classroom]:
    return await Classroom.get(classroom_id)


async def get_classrooms_as_teacher(teacher_id: PydanticObjectId) -> List[Classroom]:
    """Clases donde el User es docente."""
    return await Classroom.find(
        Classroom.teacher_user_id == teacher_id,
        Classroom.activo == True,
    ).sort("-created_at").to_list()


async def get_classrooms_as_student(student_id: PydanticObjectId) -> List[Classroom]:
    """Clases en las que el Student está inscrito."""
    enrollments = await ClassroomStudent.find(
        ClassroomStudent.student_id == student_id,
        ClassroomStudent.active == True,
    ).to_list()

    if not enrollments:
        return []

    classroom_ids = [e.classroom_id for e in enrollments]
    return await Classroom.find(
        In(Classroom.id, classroom_ids),
        Classroom.activo == True,
    ).sort("-created_at").to_list()


async def get_enrolled_students(classroom_id: PydanticObjectId) -> List[Student]:
    """Estudiantes activos inscritos en una clase."""
    enrollments = await ClassroomStudent.find(
        ClassroomStudent.classroom_id == classroom_id,
        ClassroomStudent.active == True,
    ).to_list()

    if not enrollments:
        return []

    student_ids = [e.student_id for e in enrollments]
    return await Student.find(
        In(Student.id, student_ids),
        Student.activo == True,
    ).sort("nombre").to_list()


async def create_classroom(
    data: ClassroomCreate,
    teacher_user_id: PydanticObjectId,
) -> Classroom:
    classroom = Classroom(
        **data.model_dump(),
        teacher_user_id=teacher_user_id,
    )
    await classroom.create()
    return classroom


async def update_classroom(classroom: Classroom, data: ClassroomUpdate) -> Classroom:
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(classroom, field, value)
    await classroom.save()
    return classroom


async def deactivate_classroom(classroom: Classroom) -> Classroom:
    classroom.activo = False
    await classroom.save()
    return classroom


async def enroll_student(
    classroom_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> ClassroomStudent:
    """Inscribe un estudiante; reactiva si ya existía inactivo."""
    existing = await ClassroomStudent.find_one(
        ClassroomStudent.classroom_id == classroom_id,
        ClassroomStudent.student_id == student_id,
    )
    if existing:
        if not existing.active:
            existing.active = True
            await existing.save()
        return existing

    enrollment = ClassroomStudent(
        classroom_id=classroom_id,
        student_id=student_id,
    )
    await enrollment.create()
    return enrollment


async def unenroll_student(
    classroom_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> bool:
    enrollment = await ClassroomStudent.find_one(
        ClassroomStudent.classroom_id == classroom_id,
        ClassroomStudent.student_id == student_id,
    )
    if not enrollment:
        return False
    enrollment.active = False
    await enrollment.save()
    return True


async def is_student_enrolled(
    classroom_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> bool:
    return await ClassroomStudent.find_one(
        ClassroomStudent.classroom_id == classroom_id,
        ClassroomStudent.student_id == student_id,
        ClassroomStudent.active == True,
    ) is not None
