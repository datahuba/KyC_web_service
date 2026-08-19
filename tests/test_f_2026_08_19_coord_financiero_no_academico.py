"""
F-FIX-COORD-FINANCIERO-NO-ACADEMICO (2026-08-19)
==================================================

Kevin, mirando la tabla de permisos del coordinador financiero:

    > Crear/editar programas
    > Cargar estudiantes / notas
    financiero
    no deberia crear programas ni editar
    tampoco estudiantes

El coordinador FINANCIERO gestiona lo economico (ve todo, aprueba No
Deudor). No gestiona contenido academico: no crea ni edita programas, no
carga estudiantes (individual, en lote o por Excel) ni notas.

Se agrega `require_gestion_academica()`, que envuelve a
`require_encargado_curso()` y ademas bloquea especificamente al coordinador
financiero, y se usa en las 5 acciones exactas que Kevin nombro:

- POST /courses (crear programa)
- PUT /courses/{id} (editar programa)
- POST /courses/{id}/initial-enrollments (carga inicial de estudiantes)
- POST /courses/{id}/notas-modulos-excel (carga de notas)
- POST /students/import/excel (importar estudiantes por Excel)
- POST /enrollments/ y /enrollments/bulk (inscripcion individual y en lote)

Deliberadamente NO se toco `require_encargado_curso` en si (usado en mas de
15 endpoints — comunicados, formularios de pre-inscripcion, listados) para
no restringir de mas cosas que Kevin no menciono.
"""

import io
import os

import pytest
from fastapi import HTTPException

from api.dependencies import require_gestion_academica
from models.enums import UserRole, SubtipoCoordinador


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class _UserFake:
    def __init__(self, rol, subtipo_coordinador=None):
        self.rol = rol
        self.subtipo_coordinador = subtipo_coordinador


class TestRequireGestionAcademica:
    def test_bloquea_al_coordinador_financiero(self):
        user = _UserFake(UserRole.COORDINADOR, SubtipoCoordinador.FINANCIERO)
        with pytest.raises(HTTPException) as exc:
            require_gestion_academica(current_user=user)
        assert exc.value.status_code == 403

    def test_permite_al_coordinador_academico(self):
        user = _UserFake(UserRole.COORDINADOR, SubtipoCoordinador.ACADEMICO)
        assert require_gestion_academica(current_user=user) is user

    def test_permite_al_coordinador_investigacion(self):
        user = _UserFake(UserRole.COORDINADOR, SubtipoCoordinador.INVESTIGACION)
        assert require_gestion_academica(current_user=user) is user

    def test_permite_al_coordinador_sin_subtipo(self):
        """Caso borde: cuenta legada sin subtipo definido. No cae en el bloqueo."""
        user = _UserFake(UserRole.COORDINADOR, None)
        assert require_gestion_academica(current_user=user) is user

    def test_permite_a_encargado_curso(self):
        user = _UserFake(UserRole.ENCARGADO_CURSO)
        assert require_gestion_academica(current_user=user) is user

    def test_permite_a_cpd_admin_superadmin(self):
        for rol in (UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN):
            user = _UserFake(rol)
            assert require_gestion_academica(current_user=user) is user


class TestLosCincoEndpointsUsanLaDependenciaCorrecta:
    def _cuerpo(self, ruta, nombre_funcion):
        src = _fuente(*ruta)
        ini = src.index(f"async def {nombre_funcion}")
        fin = src.find("\nasync def ", ini + 10)
        if fin == -1:
            fin = src.find("\n@router.", ini + 10)
        return src[ini: fin if fin != -1 else len(src)]

    def test_create_course(self):
        cuerpo = self._cuerpo(("api", "courses.py"), "create_course")
        assert "require_gestion_academica" in cuerpo

    def test_update_course(self):
        cuerpo = self._cuerpo(("api", "courses.py"), "update_course")
        assert "require_gestion_academica" in cuerpo

    def test_post_initial_enrollments(self):
        """Usa la dependencia local, que ahora tambien bloquea a financiero."""
        src = _fuente("api", "courses.py")
        ini = src.index("def require_cpd_or_encargado_curso_or_coordinador")
        fin = src.index("router = APIRouter()")
        cuerpo = src[ini:fin]
        assert "SubtipoCoordinador.FINANCIERO" in cuerpo

    def test_post_notas_modulos_excel_usa_la_misma_dependencia_local(self):
        cuerpo = self._cuerpo(("api", "courses.py"), "post_notas_modulos_excel")
        assert "require_cpd_or_encargado_curso_or_coordinador" in cuerpo

    def test_import_students_excel(self):
        cuerpo = self._cuerpo(("api", "students.py"), "import_students")
        assert "require_gestion_academica" in cuerpo

    def test_create_enrollment(self):
        cuerpo = self._cuerpo(("api", "enrollments.py"), "create_enrollment")
        assert "require_gestion_academica" in cuerpo

    def test_create_enrollments_bulk(self):
        cuerpo = self._cuerpo(("api", "enrollments.py"), "create_enrollments_bulk")
        assert "require_gestion_academica" in cuerpo

    def test_create_student(self):
        cuerpo = self._cuerpo(("api", "students.py"), "create_student")
        assert "require_gestion_academica" in cuerpo


class TestNoSeTocoLaDependenciaCompartida:
    def test_otros_usos_de_require_encargado_curso_siguen_igual(self):
        """
        require_encargado_curso en si NO debe excluir a financiero: la
        restriccion es solo para las 5 acciones de contenido academico.
        Comunicados, formularios de pre-inscripcion y listados siguen
        abiertos al financiero como antes.
        """
        src = _fuente("api", "dependencies.py")
        ini = src.index("def require_encargado_curso(")
        fin = src.index("def require_gestion_academica(")
        cuerpo = src[ini:fin]
        assert "SubtipoCoordinador" not in cuerpo, (
            "require_encargado_curso no debe excluir al financiero — eso "
            "es responsabilidad de require_gestion_academica"
        )
