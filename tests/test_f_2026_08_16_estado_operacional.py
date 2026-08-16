"""
F-FIX-ESTADO-OPERACIONAL (2026-08-16)
=====================================

El frontend (`CourseForm.svelte`) ofrecia desde hacia tiempo un <select>
"Estado del modulo en el cronograma" con 3 valores — Pendiente / En
Ejecucion / Ejecutado — visible al cargar un programa con
`tipo_programa='en_ejecucion'`. Sirve para que el encargado marque que
modulos ya se dictaron cuando carga un programa que arranco antes de
existir en el sistema.

El problema: `estado_operacional` NO existia ni en `models/course.py`
(Modulo) ni en `schemas/course.py` (ModuloCreate). Pydantic v2 descarta
los campos extra, asi que el valor elegido se perdia EN SILENCIO al
guardar y el cronograma del programa quedaba vacio.

Estos tests fijan el contrato para que no vuelva a romperse.
"""

import pytest
from pydantic import ValidationError

from models.course import Modulo
from schemas.course import CourseCreate, ModuloCreate


class TestModuloCreateEstadoOperacional:
    """El schema de entrada acepta, normaliza y valida el campo."""

    @pytest.mark.parametrize(
        "valor", ["Pendiente", "En Ejecucion", "Ejecutado"]
    )
    def test_acepta_los_tres_valores_del_selector(self, valor):
        modulo = ModuloCreate(nombre="Modulo 1", costo=100.0, estado_operacional=valor)
        assert modulo.estado_operacional == valor

    def test_ausente_queda_en_none(self):
        """Retrocompatibilidad: los programas nuevos no mandan el campo."""
        modulo = ModuloCreate(nombre="Modulo 1", costo=100.0)
        assert modulo.estado_operacional is None

    @pytest.mark.parametrize("vacio", ["", "null", "undefined", None])
    def test_valores_vacios_se_normalizan_a_none(self, vacio):
        """El frontend puede mandar el campo vacio; no debe dar 422."""
        modulo = ModuloCreate(nombre="Modulo 1", costo=100.0, estado_operacional=vacio)
        assert modulo.estado_operacional is None

    def test_valor_fuera_del_selector_es_rechazado(self):
        with pytest.raises(ValidationError):
            ModuloCreate(nombre="Modulo 1", costo=100.0, estado_operacional="Cualquiera")


class TestModuloModelEstadoOperacional:
    """El modelo persistido declara el campo (si no, Pydantic lo descarta)."""

    def test_el_modelo_declara_el_campo(self):
        assert "estado_operacional" in Modulo.model_fields

    def test_el_modelo_conserva_el_valor(self):
        modulo = Modulo(nombre="Modulo 1", costo=100.0, estado_operacional="Ejecutado")
        assert modulo.estado_operacional == "Ejecutado"
        assert modulo.model_dump()["estado_operacional"] == "Ejecutado"

    def test_el_modelo_tolera_su_ausencia(self):
        """Los cursos ya guardados no tienen el campo y deben seguir cargando."""
        modulo = Modulo(nombre="Modulo 1", costo=100.0)
        assert modulo.estado_operacional is None


class TestFlujoCompletoDeCreacion:
    """
    Regresion principal: el camino real de `create_course()` es
    `CourseCreate.model_dump()` -> `Course(**payload)`. Si el campo se cae
    en cualquier eslabon, el valor no llega a Mongo. Este test recorre ese
    mismo camino sobre la lista de modulos.
    """

    def test_el_estado_sobrevive_de_schema_a_modelo(self):
        course_in = CourseCreate(
            codigo="TEST-EO-001",
            nombre_programa="Programa cargado en ejecucion",
            tipo_curso="diplomado",
            modalidad="presencial",
            modulos=[
                {"nombre": "Modulo 1", "costo": 100.0, "estado_operacional": "Ejecutado"},
                {"nombre": "Modulo 2", "costo": 100.0, "estado_operacional": "En Ejecucion"},
                {"nombre": "Modulo 3", "costo": 100.0, "estado_operacional": "Pendiente"},
                {"nombre": "Modulo 4", "costo": 100.0},
            ],
        )

        payload = course_in.model_dump()
        modulos = [Modulo(**m) for m in payload["modulos"]]

        assert [m.estado_operacional for m in modulos] == [
            "Ejecutado",
            "En Ejecucion",
            "Pendiente",
            None,
        ]
