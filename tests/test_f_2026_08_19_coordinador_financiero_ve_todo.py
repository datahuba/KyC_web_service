"""
F-FIX-COORD-FINANCIERO-VE-TODO (2026-08-19)
=============================================

Kevin, creando un coordinador financiero desde cero: "el coordinador
deberia poder ver todo lo economico (...) los coordinadores ven los
resumenes de todo dependientes de su area, en este caso hablamos de
finanzas".

El bug: `filtro_cursos_por_rol()` segmentaba a CUALQUIER coordinador por
`cursos_asignados`, sin excepcion de subtipo. Un coordinador financiero
recien creado (cursos_asignados vacio, que es el estado normal al alta —
el financiero no administra un conjunto de cursos, ve TODO) generaba un
filtro Mongo `{"curso_id": {"$in": []}}`, que no matchea nada: pagos,
inscripciones, certificados y estudiantes le habrian salido en blanco.
Mismo sintoma que F-FIX-PAGOS-EC-EN-BLANCO (el bug del encargado, un dia
antes), pero con causa distinta.

Decision de Kevin, confirmada explicitamente el 2026-08-19:
- Coordinador FINANCIERO: ve TODO siempre, sin excepcion (no como
  Cobranza, que solo ve todo si cursos_asignados esta vacio — el
  financiero nunca se segmenta, tenga o no cursos cargados).
- Coordinador ACADEMICO e INVESTIGACION: siguen acotados a sus
  cursos_asignados, sin cambios — supervisan encargados de curso
  puntuales.
"""

import pytest

from api.dependencies import filtro_cursos_por_rol
from models.enums import UserRole, SubtipoCoordinador


class _UserFake:
    def __init__(self, rol, cursos_asignados=None, subtipo_coordinador=None):
        self.rol = rol
        self.cursos_asignados = cursos_asignados or []
        self.subtipo_coordinador = subtipo_coordinador


class TestCoordinadorFinancieroVeTodo:
    def test_financiero_sin_cursos_asignados_ve_todo(self):
        """
        El caso exacto del bug: un financiero recien creado, sin
        cursos_asignados. Antes esto devolvia $in: [] (no ve nada).
        """
        user = _UserFake(
            UserRole.COORDINADOR,
            cursos_asignados=[],
            subtipo_coordinador=SubtipoCoordinador.FINANCIERO,
        )
        assert filtro_cursos_por_rol(user) is None

    def test_financiero_CON_cursos_asignados_tambien_ve_todo(self):
        """
        A diferencia de Cobranza, el financiero NO se segmenta ni aunque
        tenga cursos_asignados cargados por accidente o historia previa.
        Confirmado explicitamente por Kevin: "siempre TODO, sin excepcion".
        """
        user = _UserFake(
            UserRole.COORDINADOR,
            cursos_asignados=["curso_1", "curso_2"],
            subtipo_coordinador=SubtipoCoordinador.FINANCIERO,
        )
        assert filtro_cursos_por_rol(user) is None


class TestCoordinadorAcademicoEInvestigacionSiguenAcotados:
    def test_academico_sin_cursos_ve_nada(self):
        user = _UserFake(
            UserRole.COORDINADOR,
            cursos_asignados=[],
            subtipo_coordinador=SubtipoCoordinador.ACADEMICO,
        )
        filtro = filtro_cursos_por_rol(user)
        assert filtro == {"curso_id": {"$in": []}}

    def test_academico_con_cursos_queda_acotado(self):
        user = _UserFake(
            UserRole.COORDINADOR,
            cursos_asignados=["curso_1"],
            subtipo_coordinador=SubtipoCoordinador.ACADEMICO,
        )
        filtro = filtro_cursos_por_rol(user)
        assert filtro == {"curso_id": {"$in": ["curso_1"]}}

    def test_investigacion_queda_acotado_igual_que_academico(self):
        user = _UserFake(
            UserRole.COORDINADOR,
            cursos_asignados=["curso_1"],
            subtipo_coordinador=SubtipoCoordinador.INVESTIGACION,
        )
        filtro = filtro_cursos_por_rol(user)
        assert filtro == {"curso_id": {"$in": ["curso_1"]}}

    def test_coordinador_sin_subtipo_definido_queda_acotado(self):
        """
        Caso borde: subtipo_coordinador=None (cuenta mal configurada o
        legada). No debe caer accidentalmente en la excepcion de
        financiero — el default seguro es acotar, no abrir todo.
        """
        user = _UserFake(
            UserRole.COORDINADOR, cursos_asignados=["curso_1"], subtipo_coordinador=None
        )
        filtro = filtro_cursos_por_rol(user)
        assert filtro == {"curso_id": {"$in": ["curso_1"]}}


class TestNoRompeElRestoDeRoles:
    def test_encargado_curso_sigue_igual(self):
        user = _UserFake(UserRole.ENCARGADO_CURSO, cursos_asignados=["c1"])
        assert filtro_cursos_por_rol(user) == {"curso_id": {"$in": ["c1"]}}

    def test_cobranza_sin_cursos_ve_todo_como_antes(self):
        user = _UserFake(UserRole.COBRANZA, cursos_asignados=[])
        assert filtro_cursos_por_rol(user) is None

    def test_cobranza_con_cursos_queda_acotado_como_antes(self):
        user = _UserFake(UserRole.COBRANZA, cursos_asignados=["c1"])
        assert filtro_cursos_por_rol(user) == {"curso_id": {"$in": ["c1"]}}

    def test_superadmin_ve_todo(self):
        user = _UserFake(UserRole.SUPERADMIN)
        assert filtro_cursos_por_rol(user) is None
