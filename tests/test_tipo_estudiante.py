"""
Tests para discriminación de tipo_estudiante (pregrado vs posgrado)
=================================================================
"""
import pytest
from models.student import Student
from schemas.student import StudentResponse, StudentCreate


def test_student_response_tipo_estudiante_pregrado_por_datos_ec():
    """Estudiante con registro_universitario o avance debe computar como 'pregrado'."""
    data = {
        "_id": "507f1f77bcf86cd799439011",
        "registro": "220005958",
        "nombre": "Juan Pérez",
        "carnet": "12345678",
        "activo": True,
        "registro_universitario": "220005958",
        "created_at": "2024-03-20T10:00:00",
        "updated_at": "2024-03-20T10:00:00",
    }
    resp = StudentResponse(**data)
    assert resp.tipo_estudiante == "pregrado"


def test_student_response_tipo_estudiante_posgrado_por_titulo():
    """Estudiante con título profesional o no primer carrera debe computar como 'posgrado'."""
    data = {
        "_id": "507f1f77bcf86cd799439012",
        "registro": "PROF-001",
        "nombre": "Lic. María Lopez",
        "carnet": "87654321",
        "activo": True,
        "es_primer_carrera": False,
        "titulo": {
            "titulo": "Licenciada en Auditoría",
            "numero_titulo": "TIT-9988",
            "año_expedicion": "2020",
            "universidad": "UAGRM",
            "estado": "verificado"
        },
        "created_at": "2024-03-20T10:00:00",
        "updated_at": "2024-03-20T10:00:00",
    }
    resp = StudentResponse(**data)
    assert resp.tipo_estudiante == "posgrado"


def test_student_response_tipo_estudiante_explicito():
    """Si viene tipo_estudiante explícito, se respeta."""
    data = {
        "_id": "507f1f77bcf86cd799439013",
        "registro": "TEST-001",
        "nombre": "Pedro Gomez",
        "carnet": "5555555",
        "activo": True,
        "tipo_estudiante": "posgrado",
        "created_at": "2024-03-20T10:00:00",
        "updated_at": "2024-03-20T10:00:00",
    }
    resp = StudentResponse(**data)
    assert resp.tipo_estudiante == "posgrado"


def test_student_response_posgrado_default_sin_ru():
    """Un estudiante de postgrado sin RU ni formulario debe computar como 'posgrado' por defecto."""
    data = {
        "_id": "507f1f77bcf86cd799439014",
        "registro": "5384101",
        "nombre": "Luis Rafael Valdez Bustillo",
        "carnet": "5384101",
        "activo": True,
        "created_at": "2024-03-20T10:00:00",
        "updated_at": "2024-03-20T10:00:00",
    }
    resp = StudentResponse(**data)
    assert resp.tipo_estudiante == "posgrado"

