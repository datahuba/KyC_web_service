"""
Tests del módulo Classroom
===========================

Tests mínimos para verificar:
- Schemas (validación de datos)
- Lógica básica de enums
- Estructura de las respuestas
"""

import pytest
from datetime import datetime
from beanie import PydanticObjectId

from models.enums import AssignmentType, SubmissionStatus
from schemas.classroom import (
    AssignmentCreate,
    AssignmentResponse,
    ClassroomCreate,
    ClassroomMaterialResponse,
    ClassroomResponse,
    GradeRequest,
    GradeResponse,
    SubmissionResponse,
)


class TestEnums:
    def test_assignment_types(self):
        assert AssignmentType.TASK == "TASK"
        assert AssignmentType.EXAM == "EXAM"

    def test_submission_status(self):
        assert SubmissionStatus.PENDING == "pending"
        assert SubmissionStatus.SUBMITTED == "submitted"
        assert SubmissionStatus.GRADED == "graded"


class TestClassroomCreateSchema:
    def test_valid_create(self):
        data = ClassroomCreate(nombre="Diplomado IA — Grupo A")
        assert data.nombre == "Diplomado IA — Grupo A"
        assert data.descripcion is None
        assert data.course_id is None

    def test_create_with_all_fields(self):
        data = ClassroomCreate(
            nombre="Taller Python",
            descripcion="Taller de introducción a Python",
            course_id="507f1f77bcf86cd799439011",
        )
        assert data.descripcion == "Taller de introducción a Python"
        assert isinstance(data.course_id, PydanticObjectId)
        assert str(data.course_id) == "507f1f77bcf86cd799439011"

    def test_invalid_course_id(self):
        with pytest.raises(Exception):
            ClassroomCreate(nombre="Clase inválida", course_id="curso-123")

    def test_nombre_required(self):
        with pytest.raises(Exception):
            ClassroomCreate(nombre="")


class TestAssignmentCreateSchema:
    def test_valid_task(self):
        data = AssignmentCreate(title="Tarea 1", type=AssignmentType.TASK)
        assert data.type == AssignmentType.TASK
        assert data.max_score == 100.0
        assert data.due_at is None

    def test_valid_exam(self):
        data = AssignmentCreate(
            title="Examen Parcial",
            type=AssignmentType.EXAM,
            max_score=50.0,
        )
        assert data.max_score == 50.0

    def test_max_score_non_negative(self):
        with pytest.raises(Exception):
            AssignmentCreate(title="T", type=AssignmentType.TASK, max_score=-1)


class TestGradeRequestSchema:
    def test_valid_grade(self):
        data = GradeRequest(score=85.0, feedback="Buen trabajo")
        assert data.score == 85.0
        assert data.feedback == "Buen trabajo"

    def test_grade_non_negative(self):
        with pytest.raises(Exception):
            GradeRequest(score=-5)


class TestClassroomResponse:
    def test_response_fields(self):
        resp = ClassroomResponse(
            id="507f1f77bcf86cd799439011",
            nombre="Clase de prueba",
            activo=True,
        )
        assert resp.id == "507f1f77bcf86cd799439011"
        assert resp.activo is True
        assert resp.descripcion is None


class TestGradeResponse:
    def test_pending_grade(self):
        resp = GradeResponse(
            assignment_id="aaa",
            assignment_title="Tarea 1",
            assignment_type=AssignmentType.TASK,
            max_score=100.0,
            status=SubmissionStatus.PENDING,
        )
        assert resp.score is None
        assert resp.status == SubmissionStatus.PENDING

    def test_graded_response(self):
        resp = GradeResponse(
            assignment_id="bbb",
            assignment_title="Examen Final",
            assignment_type=AssignmentType.EXAM,
            max_score=50.0,
            status=SubmissionStatus.GRADED,
            score=42.5,
            feedback="Excelente",
        )
        assert resp.score == 42.5
        assert resp.feedback == "Excelente"
