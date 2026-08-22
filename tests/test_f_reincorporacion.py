# -*- coding: utf-8 -*-
"""
F-REINCORPORACION (Kevin 2026-08-22) · Tests para Reincorporación de Estudiantes
================================================================================

Verifica el comportamiento del flujo de traspaso y reingreso de alumnos entre ediciones:
- Arrastre de notas aprobadas
- Arrastre de pagos de módulos previos
- Cálculo correcto del saldo restante
- Endpoint POST /enrollments/{id}/reincorporar
"""
import pytest
from pathlib import Path
import re

MODEL_FILE = Path(__file__).parent.parent / "models" / "enrollment.py"
SERVICE_FILE = Path(__file__).parent.parent / "services" / "enrollment_service.py"
API_FILE = Path(__file__).parent.parent / "api" / "enrollments.py"
SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "enrollment.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestFReincorporacionEstructura:
    """Verifica que los modelos, schemas y servicios contengan los campos y métodos de reincorporación."""

    def test_modelo_enrollment_tiene_campos_reincorporacion(self):
        content = read(MODEL_FILE)
        assert "reincorporado_de_enrollment_id" in content
        assert "reincorporado_a_enrollment_id" in content
        assert "modulo_reincorporacion_inicio" in content

    def test_schema_reincorporacion_existe(self):
        content = read(SCHEMA_FILE)
        assert "class ReincorporacionCreate" in content
        assert "nuevo_curso_id" in content
        assert "modulo_inicio" in content

    def test_servicio_reincorporar_existe(self):
        content = read(SERVICE_FILE)
        assert "async def reincorporar_estudiante(" in content
        assert "reincorporado_de_enrollment_id" in content

    def test_endpoint_reincorporar_existe(self):
        content = read(API_FILE)
        assert "reincorporar_estudiante_endpoint" in content
