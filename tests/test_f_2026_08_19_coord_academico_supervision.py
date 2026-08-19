"""
F-COORD-ACADEMICO-SUPERVISION (2026-08-19)
============================================

Kevin, sobre la tabla del coordinador academico: "me parece bien lo de que
deberia hacer hazlo" -- aprobando: "Falta: pantalla de 'mis Encargados de
Curso supervisados' + estado academico consolidado de sus programas (notas
cargadas, modulos ejecutados, etc.)".

Nuevo endpoint GET /courses/supervision-academica: por cada programa que el
coordinador supervisa, quien lo administra (encargados) y si el estado
academico esta al dia (modulos ejecutados, cobertura de notas).

La "cobertura de notas" es deliberada: es exactamente el numero que habria
detectado en el momento el problema real de la sesion del 2026-08-18 (38 de
54 inscripciones de DIPL-IA-2026 sin nota del modulo 1).
"""

import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


def _cuerpo_endpoint():
    src = _fuente("api", "courses.py")
    ini = src.index("async def get_supervision_academica")
    fin = src.find("\n@router.", ini + 10)
    return src[ini: fin if fin != -1 else len(src)]


class TestSegmentacionReutilizaElFiltroCentral:
    def test_usa_filtro_cursos_por_rol(self):
        """
        No debe reinventar la segmentacion: reusa filtro_cursos_por_rol, el
        mismo que ya distingue financiero (ve todo) de academico/investigacion
        (acotado a cursos_asignados) desde el fix anterior de esta sesion.
        """
        cuerpo = _cuerpo_endpoint()
        assert "filtro_cursos_por_rol(current_user)" in cuerpo

    def test_devuelve_vacio_si_el_filtro_no_matchea_nada(self):
        cuerpo = _cuerpo_endpoint()
        assert "return []" in cuerpo


class TestLaCoberturaDeNotasSeCalculaPorInscripcion:
    def test_cuenta_inscripciones_con_alguna_nota_no_modulos_sueltos(self):
        """
        El indicador es "esta inscripcion tiene AL MENOS una nota cargada",
        no un promedio de notas sueltas — mas facil de leer de un vistazo
        y evita que un solo modulo con nota tape que el resto esta vacio
        de forma poco clara.
        """
        cuerpo = _cuerpo_endpoint()
        assert "con_nota = sum(" in cuerpo
        assert "m.nota is not None" in cuerpo

    def test_evita_division_por_cero(self):
        cuerpo = _cuerpo_endpoint()
        assert "if inscritos > 0 else 0.0" in cuerpo

    def test_ordena_por_cobertura_ascendente(self):
        """
        Los programas con menos cobertura (los que necesitan atencion)
        deben aparecer primero, no los que ya estan al dia.
        """
        cuerpo = _cuerpo_endpoint()
        assert "resultado.sort(key=lambda r: r.cobertura_notas_pct)" in cuerpo


class TestLosEncargadosSeResuelvenSinNMasUno:
    def test_una_sola_query_de_usuarios_no_una_por_curso(self):
        """
        Si se hiciera un query de encargados POR CADA programa, un
        coordinador con 20 programas dispara 20 queries. Debe ser 1 query
        total, agrupada en memoria.
        """
        cuerpo = _cuerpo_endpoint()
        assert "posibles_encargados = await User.find(" in cuerpo
        assert "encargados_por_curso.setdefault(" in cuerpo

    def test_una_sola_query_de_inscripciones_no_una_por_curso(self):
        cuerpo = _cuerpo_endpoint()
        assert "enrollments = await Enrollment.find(In(Enrollment.curso_id, curso_ids))" in cuerpo
