"""
F-FIX-MATRICULA-DIFERENCIADA (2026-08-16)
=========================================

`models/course.py` define dos overrides de matricula por tipo de estudiante
desde F-2026-08-12-DESCUENTO-BECA:

    matricula_primer_carrera  -> estudiantes de primera carrera (default 200)
    matricula_profesional     -> estudiantes ya titulados       (default 500)

`services/matricula_helper.py` los consume para decidir cuanto cobrar. Pero
NINGUNO de los tres schemas de Course los declaraba:

    CourseCreate    -> no se podian setear al crear el programa
    CourseUpdate    -> no se podian editar despues
    CourseResponse  -> no se podian leer de vuelta

Como Pydantic v2 descarta los campos extra, lo que el admin cargaba en el
formulario se perdia en silencio y `matricula_helper` siempre encontraba
None, o sea que TODOS los estudiantes pagaban el default global sin importar
lo configurado en el programa. Bug de dinero.

Estos tests fijan el contrato en los tres sentidos.
"""

import pytest
from pydantic import ValidationError

from schemas.course import CourseCreate, CourseResponse, CourseUpdate


def _course_base(**extra):
    datos = dict(
        codigo="TEST-MAT",
        nombre_programa="Programa con matricula diferenciada",
        tipo_curso="diplomado",
        modalidad="presencial",
    )
    datos.update(extra)
    return datos


class TestCourseCreate:
    def test_acepta_los_overrides(self):
        c = CourseCreate(**_course_base(
            matricula_primer_carrera=300.0,
            matricula_profesional=750.0,
        ))
        assert c.matricula_primer_carrera == 300.0
        assert c.matricula_profesional == 750.0

    def test_sin_overrides_quedan_en_none(self):
        """None significa 'usar el default global', no 'cero'."""
        c = CourseCreate(**_course_base())
        assert c.matricula_primer_carrera is None
        assert c.matricula_profesional is None

    def test_los_overrides_sobreviven_al_model_dump(self):
        """`create_course()` hace model_dump() -> Course(**payload)."""
        c = CourseCreate(**_course_base(
            matricula_primer_carrera=300.0,
            matricula_profesional=750.0,
        ))
        payload = c.model_dump()
        assert payload["matricula_primer_carrera"] == 300.0
        assert payload["matricula_profesional"] == 750.0

    def test_rechaza_valores_negativos(self):
        with pytest.raises(ValidationError):
            CourseCreate(**_course_base(matricula_primer_carrera=-1))


class TestCourseUpdate:
    def test_permite_editar_los_overrides(self):
        u = CourseUpdate(matricula_primer_carrera=250.0, matricula_profesional=600.0)
        datos = u.model_dump(exclude_unset=True)
        assert datos["matricula_primer_carrera"] == 250.0
        assert datos["matricula_profesional"] == 600.0

    def test_no_los_toca_si_no_se_mandan(self):
        """exclude_unset debe dejarlos fuera para no pisar lo guardado."""
        u = CourseUpdate(nombre_programa="Otro nombre")
        datos = u.model_dump(exclude_unset=True)
        assert "matricula_primer_carrera" not in datos
        assert "matricula_profesional" not in datos

    def test_permite_volver_al_default_global(self):
        """Mandar null explicito debe poder limpiar el override."""
        u = CourseUpdate(matricula_primer_carrera=None)
        datos = u.model_dump(exclude_unset=True)
        assert "matricula_primer_carrera" in datos
        assert datos["matricula_primer_carrera"] is None


class TestCourseResponse:
    def test_los_declara(self):
        """Sin esto el formulario de edicion los mostraba siempre vacios."""
        assert "matricula_primer_carrera" in CourseResponse.model_fields
        assert "matricula_profesional" in CourseResponse.model_fields

    def test_son_opcionales_para_cursos_viejos(self):
        """Los cursos creados antes del fix no tienen el campo en Mongo."""
        campo = CourseResponse.model_fields["matricula_primer_carrera"]
        assert not campo.is_required()
