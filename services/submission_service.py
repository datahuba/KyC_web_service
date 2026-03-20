"""
Servicio de Submissions (Entregas de Estudiantes)
===================================================

Manejo de entregas y calificaciones.
- Estudiante: crea/actualiza su propia entrega (texto y/o archivo).
- Docente: consulta todas las entregas y califica.
"""

from datetime import datetime
from typing import List, Optional
from fastapi import HTTPException, UploadFile, status
from beanie import PydanticObjectId

from models.submission import Submission
from models.assignment import Assignment
from models.enums import SubmissionStatus
from core.cloudinary_utils import upload_document, delete_file
from schemas.classroom import GradeRequest


async def get_submission(submission_id: PydanticObjectId) -> Optional[Submission]:
    return await Submission.get(submission_id)


async def get_submissions_for_assignment(
    assignment_id: PydanticObjectId,
) -> List[Submission]:
    """Todas las entregas de una actividad (vista docente)."""
    return await Submission.find(
        Submission.assignment_id == assignment_id,
    ).sort("-submitted_at").to_list()


async def get_my_submission(
    assignment_id: PydanticObjectId,
    student_id: PydanticObjectId,
) -> Optional[Submission]:
    return await Submission.find_one(
        Submission.assignment_id == assignment_id,
        Submission.student_id == student_id,
    )


async def get_grades_for_classroom(
    classroom_id: PydanticObjectId,
    student_id: Optional[PydanticObjectId] = None,
) -> List[Submission]:
    """
    Calificaciones de un classroom.
    Si se pasa student_id filtra solo las suyas (vista estudiante).
    """
    query = Submission.find(Submission.classroom_id == classroom_id)
    if student_id is not None:
        query = query.find(Submission.student_id == student_id)
    return await query.sort("-submitted_at").to_list()


MAX_ATTEMPTS = 3


async def submit(
    assignment_id: PydanticObjectId,
    classroom_id: PydanticObjectId,
    student_id: PydanticObjectId,
    text_content: Optional[str] = None,
    file: Optional[UploadFile] = None,
) -> Submission:
    """Crea o actualiza la entrega del estudiante (máximo 3 intentos)."""
    submission = await get_my_submission(assignment_id, student_id)

    # Verificar límite de intentos
    if submission is not None and (submission.attempt_count or 0) >= MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Has alcanzado el límite de {MAX_ATTEMPTS} entregas para esta actividad."
        )

    file_data: dict = {}
    if file and file.filename:
        folder = f"classroom/{str(classroom_id)}/assignments/{str(assignment_id)}/submissions/{str(student_id)}"
        if submission and submission.public_id:
            await delete_file(submission.public_id, submission.resource_type or "raw")
        result = await upload_document(file, folder)
        file_data = {
            "file_url": result["url"],
            "public_id": result["public_id"],
            "resource_type": result["resource_type"],
            "mime_type": result["mime_type"],
            "size_bytes": result["size_bytes"],
        }

    now = datetime.utcnow()

    if submission is None:
        submission = Submission(
            assignment_id=assignment_id,
            classroom_id=classroom_id,
            student_id=student_id,
            text_content=text_content,
            status=SubmissionStatus.SUBMITTED,
            submitted_at=now,
            attempt_count=1,
            **file_data,
        )
        await submission.create()
    else:
        if text_content is not None:
            submission.text_content = text_content
        for k, v in file_data.items():
            setattr(submission, k, v)
        submission.status = SubmissionStatus.SUBMITTED
        submission.submitted_at = now
        submission.attempt_count = (submission.attempt_count or 0) + 1
        await submission.save()

    return submission


async def grade_submission(
    submission: Submission,
    data: GradeRequest,
    graded_by: PydanticObjectId,
) -> Submission:
    submission.score = data.score
    submission.feedback = data.feedback
    submission.status = SubmissionStatus.GRADED
    submission.graded_by = graded_by
    submission.graded_at = datetime.utcnow()
    await submission.save()
    return submission
