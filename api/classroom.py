"""
Classroom Router
================

Endpoints del módulo Classroom (FASE 2 — persistencia real).

Convención de roles:
    - User (admin/superadmin) actúa como DOCENTE.
    - Student actúa como ESTUDIANTE.
"""

from typing import Any, List, Optional, Union
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from beanie import PydanticObjectId

from api.dependencies import get_current_user, require_admin
from models.user import User
from models.student import Student
from models.enums import AssignmentType
from schemas.classroom import (
    AssignmentCreate,
    AssignmentResponse,
    AssignmentUpdate,
    ClassroomCreate,
    ClassroomMaterialResponse,
    ClassroomResponse,
    ClassroomStudentResponse,
    ClassroomUpdate,
    EnrollStudentRequest,
    GradeRequest,
    GradeResponse,
    SubmissionResponse,
)
from services import (
    classroom_service,
    classroom_material_service,
    assignment_service,
    submission_service,
)

router = APIRouter()


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _require_teacher(current_user: Union[User, Student]) -> User:
    """Solo User (admin/superadmin) puede actuar como docente."""
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo docentes pueden realizar esta acción.")
    return current_user


def _require_student(current_user: Union[User, Student]) -> Student:
    """Solo Student puede realizar acciones de estudiante."""
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo estudiantes pueden realizar esta acción.")
    return current_user


# ─────────────────────────────────────────────────────────────────────────────
# CLASSROOM CRUD
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/my-classes", response_model=List[ClassroomResponse], summary="Mis Clases")
async def get_my_classes(
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    """
    Clases del usuario autenticado.
    - **Docente**: clases donde es profesor.
    - **Estudiante**: clases en que está inscrito.
    """
    if isinstance(current_user, User):
        classes = await classroom_service.get_classrooms_as_teacher(current_user.id)
    else:
        classes = await classroom_service.get_classrooms_as_student(current_user.id)

    return [ClassroomResponse.from_doc(c) for c in classes]


@router.post("/", response_model=ClassroomResponse, status_code=201, summary="Crear Clase")
async def create_classroom(
    data: ClassroomCreate,
    current_user: User = Depends(require_admin),
) -> Any:
    """Crea un nuevo classroom. **Requiere:** Admin o SuperAdmin."""
    classroom = await classroom_service.create_classroom(data, current_user.id)
    return ClassroomResponse.from_doc(classroom, teacher_name=current_user.username)


@router.get("/{classroom_id}", response_model=ClassroomResponse, summary="Detalle de Clase")
async def get_classroom(
    classroom_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")
    return ClassroomResponse.from_doc(classroom)


@router.put("/{classroom_id}", response_model=ClassroomResponse, summary="Actualizar Clase")
async def update_classroom(
    classroom_id: PydanticObjectId,
    data: ClassroomUpdate,
    current_user: User = Depends(require_admin),
) -> Any:
    """**Requiere:** Admin o SuperAdmin."""
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")
    classroom = await classroom_service.update_classroom(classroom, data)
    return ClassroomResponse.from_doc(classroom)


@router.post(
    "/{classroom_id}/students",
    summary="Inscribir Estudiante",
    status_code=201,
)
async def enroll_student(
    classroom_id: PydanticObjectId,
    body: EnrollStudentRequest,
    current_user: User = Depends(require_admin),
) -> Any:
    """Inscribe un estudiante en el classroom. **Requiere:** Admin."""
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")

    student_id = PydanticObjectId(body.student_id)
    enrollment = await classroom_service.enroll_student(classroom_id, student_id)
    return {"enrolled": True, "classroom_id": str(classroom_id), "student_id": str(student_id)}


@router.get(
    "/{classroom_id}/students",
    response_model=List[ClassroomStudentResponse],
    summary="Estudiantes Inscritos",
)
async def get_enrolled_students(
    classroom_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    """Lista los estudiantes activos inscritos en la clase."""
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")

    if isinstance(current_user, Student):
        enrolled = await classroom_service.is_student_enrolled(classroom_id, current_user.id)
        if not enrolled:
            raise HTTPException(status_code=403, detail="No tienes acceso a esta clase.")

    students = await classroom_service.get_enrolled_students(classroom_id)
    return [ClassroomStudentResponse.from_doc(s) for s in students]


# ─────────────────────────────────────────────────────────────────────────────
# MATERIALS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{classroom_id}/materials",
    response_model=List[ClassroomMaterialResponse],
    summary="Materiales de la Clase",
)
async def get_materials(
    classroom_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    materials = await classroom_material_service.get_materials(classroom_id)
    return [ClassroomMaterialResponse.from_doc(m) for m in materials]


@router.post(
    "/{classroom_id}/materials",
    response_model=ClassroomMaterialResponse,
    status_code=201,
    summary="Subir Material",
)
async def upload_material(
    classroom_id: PydanticObjectId,
    title: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    current_user: User = Depends(require_admin),
) -> Any:
    """
    Sube un archivo (PDF, Word, PPT, Excel, imagen) al classroom.
    **Requiere:** Admin (docente).
    """
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")

    material = await classroom_material_service.upload_material(
        classroom_id=classroom_id,
        file=file,
        title=title,
        uploaded_by=current_user.id,
    )
    return ClassroomMaterialResponse.from_doc(material)


@router.delete(
    "/{classroom_id}/materials/{material_id}",
    summary="Eliminar Material",
)
async def delete_material(
    classroom_id: PydanticObjectId,
    material_id: PydanticObjectId,
    current_user: User = Depends(require_admin),
) -> Any:
    """Elimina material de Cloudinary y lo marca inactivo en MongoDB."""
    material = await classroom_material_service.get_material(material_id)
    if not material or material.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Material no encontrado.")

    deleted = await classroom_material_service.delete_material(material_id)
    return {"deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# ASSIGNMENTS
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{classroom_id}/assignments",
    response_model=List[AssignmentResponse],
    summary="Actividades de la Clase",
)
async def get_assignments(
    classroom_id: PydanticObjectId,
    type: Optional[AssignmentType] = Query(None, description="TASK | EXAM"),
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    assignments = await assignment_service.get_assignments(classroom_id, type)
    return [AssignmentResponse.from_doc(a) for a in assignments]


@router.post(
    "/{classroom_id}/assignments",
    response_model=AssignmentResponse,
    status_code=201,
    summary="Crear Actividad",
)
async def create_assignment(
    classroom_id: PydanticObjectId,
    data: AssignmentCreate,
    current_user: User = Depends(require_admin),
) -> Any:
    """Crea tarea o examen. **Requiere:** Admin (docente)."""
    classroom = await classroom_service.get_classroom(classroom_id)
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom no encontrado.")

    assignment = await assignment_service.create_assignment(data, classroom_id, current_user.id)
    return AssignmentResponse.from_doc(assignment)


@router.put(
    "/{classroom_id}/assignments/{assignment_id}",
    response_model=AssignmentResponse,
    summary="Actualizar Actividad",
)
async def update_assignment(
    classroom_id: PydanticObjectId,
    assignment_id: PydanticObjectId,
    data: AssignmentUpdate,
    current_user: User = Depends(require_admin),
) -> Any:
    assignment = await assignment_service.get_assignment(assignment_id)
    if not assignment or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    assignment = await assignment_service.update_assignment(assignment, data)
    return AssignmentResponse.from_doc(assignment)


@router.delete(
    "/{classroom_id}/assignments/{assignment_id}",
    summary="Eliminar Actividad",
)
async def delete_assignment(
    classroom_id: PydanticObjectId,
    assignment_id: PydanticObjectId,
    current_user: User = Depends(require_admin),
) -> Any:
    assignment = await assignment_service.get_assignment(assignment_id)
    if not assignment or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    deleted = await assignment_service.delete_assignment(assignment_id)
    return {"deleted": deleted}


# ─────────────────────────────────────────────────────────────────────────────
# SUBMISSIONS
# ─────────────────────────────────────────────────────────────────────────────

@router.post(
    "/{classroom_id}/assignments/{assignment_id}/submit",
    response_model=SubmissionResponse,
    summary="Entregar Actividad (Estudiante)",
)
async def submit_assignment(
    classroom_id: PydanticObjectId,
    assignment_id: PydanticObjectId,
    text_content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: Student = Depends(get_current_user),
) -> Any:
    """
    El estudiante entrega texto y/o archivo.
    Permite re-entregar (actualiza la entrega existente).
    """
    student = _require_student(current_user)

    assignment = await assignment_service.get_assignment(assignment_id)
    if not assignment or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if not text_content and (not file or not file.filename):
        raise HTTPException(
            status_code=400,
            detail="Debes incluir texto y/o un archivo en la entrega.",
        )

    submission = await submission_service.submit(
        assignment_id=assignment_id,
        classroom_id=classroom_id,
        student_id=student.id,
        text_content=text_content,
        file=file,
    )
    return SubmissionResponse.from_doc(submission, max_score=assignment.max_score)


@router.get(
    "/{classroom_id}/assignments/{assignment_id}/submissions",
    response_model=List[SubmissionResponse],
    summary="Ver Entregas (Docente)",
)
async def get_submissions(
    classroom_id: PydanticObjectId,
    assignment_id: PydanticObjectId,
    current_user: User = Depends(require_admin),
) -> Any:
    """Todas las entregas de una actividad. **Requiere:** Admin."""
    assignment = await assignment_service.get_assignment(assignment_id)
    if not assignment or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    submissions = await submission_service.get_submissions_for_assignment(assignment_id)
    return [SubmissionResponse.from_doc(s, max_score=assignment.max_score) for s in submissions]


@router.put(
    "/{classroom_id}/assignments/{assignment_id}/submissions/{submission_id}/grade",
    response_model=SubmissionResponse,
    summary="Calificar Entrega (Docente)",
)
async def grade_submission(
    classroom_id: PydanticObjectId,
    assignment_id: PydanticObjectId,
    submission_id: PydanticObjectId,
    data: GradeRequest,
    current_user: User = Depends(require_admin),
) -> Any:
    """Califica la entrega de un estudiante. **Requiere:** Admin (docente)."""
    assignment = await assignment_service.get_assignment(assignment_id)
    if not assignment or assignment.classroom_id != classroom_id:
        raise HTTPException(status_code=404, detail="Actividad no encontrada.")

    if data.score > assignment.max_score:
        raise HTTPException(
            status_code=400,
            detail=f"La nota no puede superar el máximo ({assignment.max_score}).",
        )

    submission = await submission_service.get_submission(submission_id)
    if not submission or submission.assignment_id != assignment_id:
        raise HTTPException(status_code=404, detail="Entrega no encontrada.")

    submission = await submission_service.grade_submission(submission, data, current_user.id)
    return SubmissionResponse.from_doc(submission, max_score=assignment.max_score)


# ─────────────────────────────────────────────────────────────────────────────
# GRADES
# ─────────────────────────────────────────────────────────────────────────────

@router.get(
    "/{classroom_id}/grades",
    response_model=List[GradeResponse],
    summary="Calificaciones de la Clase",
)
async def get_grades(
    classroom_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    """
    Resumen de calificaciones del classroom.
    - **Docente**: todas las entregas calificadas.
    - **Estudiante**: solo las propias.
    """
    student_filter = current_user.id if isinstance(current_user, Student) else None
    submissions = await submission_service.get_grades_for_classroom(classroom_id, student_filter)

    # Enriquecer con datos de la actividad
    grades: List[GradeResponse] = []
    assignment_cache: dict = {}

    for sub in submissions:
        if sub.assignment_id not in assignment_cache:
            a = await assignment_service.get_assignment(sub.assignment_id)
            assignment_cache[sub.assignment_id] = a
        a = assignment_cache.get(sub.assignment_id)
        if not a:
            continue
        grades.append(GradeResponse(
            assignment_id=str(sub.assignment_id),
            assignment_title=a.title,
            assignment_type=a.type,
            due_at=a.due_at.isoformat() if a.due_at else None,
            status=sub.status,
            score=sub.score,
            max_score=a.max_score,
            feedback=sub.feedback,
            submitted_at=sub.submitted_at.isoformat() if sub.submitted_at else None,
            graded_at=sub.graded_at.isoformat() if sub.graded_at else None,
        ))

    return grades
