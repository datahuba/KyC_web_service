"""
P-AMBITO-FORMACION (2026-08-18)
===============================

Separa educacion continua de programas profesionales, y de paso arregla un
bug de PLATA que estaba activo en produccion.

EL BUG
------
Convivian dos sistemas de matricula y el campo que se veia NO era el que
cobraba:

- `Course.matricula_interno` es el campo "Matricula" del formulario, marcado
  como obligatorio. Es el que el encargado completa.
- Pero `enrollment_service.create_enrollment` calcula el costo con
  `get_matricula_for_student()`, que lee `matricula_primer_carrera` /
  `matricula_profesional` — los del bloque secundario "matricula
  diferenciada", que son OPCIONALES.
- Y esos campos en None no significan "sin matricula": significan "cobra el
  default global" (200 / 500 Bs).

Resultado, en la capacitacion del 2026-08-18: se creo un programa
profesional con "Matricula = 0" y el bloque diferenciado vacio. Cada
estudiante quedaba con 200 o 500 Bs de matricula inexistente y, por la Regla
de Matricula, no pasaba a "Activo" hasta pagarla.

Estos tests fijan la tabla de comportamiento para que no vuelva a pasar.
"""

import pytest

from models.enums import AmbitoFormacion, TipoCurso
from services.matricula_helper import (
    get_matricula_for_student,
    normalizar_matriculas,
    resolver_ambito,
)
from core.config import settings


class _CursoFake:
    """Doble minimo: get_matricula_for_student solo lee estos atributos."""

    def __init__(self, ambito=None, primer_carrera=None, profesional=None,
                 matricula_interno=0.0):
        self.ambito = ambito
        self.matricula_primer_carrera = primer_carrera
        self.matricula_profesional = profesional
        self.matricula_interno = matricula_interno


class _EstudianteFake:
    def __init__(self, es_primer_carrera):
        self.es_primer_carrera = es_primer_carrera


# ============================================================================
# resolver_ambito
# ============================================================================
class TestResolverAmbito:
    def test_maestria_siempre_profesional(self):
        """Kevin: "maestrias, doctorados, todos son profesionales"."""
        assert resolver_ambito("maestría") == AmbitoFormacion.PROFESIONAL
        assert resolver_ambito("doctorado") == AmbitoFormacion.PROFESIONAL

    def test_el_tipo_de_curso_gana_sobre_lo_que_pidan(self):
        """
        Una maestria no puede marcarse como educacion continua ni aunque el
        formulario lo mande: seria cobrarle matricula a un postgrado.
        """
        assert resolver_ambito(
            "maestría", ambito_explicito="educacion_continua"
        ) == AmbitoFormacion.PROFESIONAL

    def test_diplomado_no_se_adivina(self):
        """
        Kevin confirmo que "hay diplomados uno educacion continua y el otro
        profesional". Se resuelve por lo explicito o por el creador, nunca
        deduciendolo del tipo.
        """
        assert resolver_ambito(
            "diplomado", ambito_explicito="profesional"
        ) == AmbitoFormacion.PROFESIONAL
        assert resolver_ambito(
            "diplomado", ambito_del_creador="profesional"
        ) == AmbitoFormacion.PROFESIONAL

    def test_el_encargado_define_el_ambito_de_su_diplomado(self):
        """
        Cada encargado es de un solo tipo, asi que al crear no se le pregunta:
        el programa hereda su ambito.
        """
        assert resolver_ambito(
            "diplomado", ambito_del_creador="educacion_continua"
        ) == AmbitoFormacion.EDUCACION_CONTINUA

    def test_lo_explicito_gana_sobre_el_creador(self):
        assert resolver_ambito(
            "diplomado",
            ambito_explicito="profesional",
            ambito_del_creador="educacion_continua",
        ) == AmbitoFormacion.PROFESIONAL

    def test_curso_y_taller_son_continua_por_defecto(self):
        assert resolver_ambito("curso") == AmbitoFormacion.EDUCACION_CONTINUA
        assert resolver_ambito("taller") == AmbitoFormacion.EDUCACION_CONTINUA

    def test_sin_datos_cae_en_continua(self):
        """
        El caso conservador es cobrar: un cobro de mas es visible y alguien lo
        corrige; uno de menos pasa desapercibido y el programa cierra con
        menos ingresos.
        """
        assert resolver_ambito(None) == AmbitoFormacion.EDUCACION_CONTINUA
        assert resolver_ambito("otro") == AmbitoFormacion.EDUCACION_CONTINUA


# ============================================================================
# El bug: None NO es cero
# ============================================================================
class TestMatriculaFantasma:
    def test_asi_se_cobraba_de_mas_antes_del_fix(self):
        """
        Reproduce el estado exacto de un curso creado en la capacitacion:
        matricula_interno=0 y el bloque diferenciado vacio. SIN ambito, el
        sistema cobra los defaults globales.

        Este test documenta el bug; no lo aprueba. Los cursos viejos siguen
        en este estado hasta que se los edite.
        """
        curso_viejo = _CursoFake(ambito=None, matricula_interno=0.0)

        cobro = get_matricula_for_student(curso_viejo, _EstudianteFake(True))

        assert cobro == settings.MATRICULA_PRIMER_CARRERA_DEFAULT
        assert cobro != 0.0, "poner 0 en 'Matricula' no evitaba el cobro"

    def test_un_programa_profesional_no_cobra_matricula(self):
        """
        Con el ambito marcado, el mismo curso mal configurado ya no cobra:
        es la red de seguridad para los programas que ya estan en la base.
        """
        curso = _CursoFake(ambito=AmbitoFormacion.PROFESIONAL)

        assert get_matricula_for_student(curso, _EstudianteFake(True)) == 0.0
        assert get_matricula_for_student(curso, _EstudianteFake(False)) == 0.0
        assert get_matricula_for_student(curso, None) == 0.0

    def test_educacion_continua_sigue_cobrando_diferenciado(self):
        """El comportamiento de educacion continua NO cambia."""
        curso = _CursoFake(
            ambito=AmbitoFormacion.EDUCACION_CONTINUA,
            primer_carrera=200.0,
            profesional=500.0,
        )

        assert get_matricula_for_student(curso, _EstudianteFake(True)) == 200.0
        assert get_matricula_for_student(curso, _EstudianteFake(False)) == 500.0

    def test_el_override_del_curso_sigue_mandando(self):
        curso = _CursoFake(
            ambito=AmbitoFormacion.EDUCACION_CONTINUA,
            primer_carrera=150.0,
            profesional=600.0,
        )
        assert get_matricula_for_student(curso, _EstudianteFake(False)) == 600.0


# ============================================================================
# normalizar_matriculas: despues de esto, ningun None sobrevive
# ============================================================================
class TestNormalizarMatriculas:
    def test_profesional_deja_los_tres_campos_en_cero_explicito(self):
        """
        Ceros explicitos, NO None: None es exactamente lo que dispara los
        defaults de 200/500.
        """
        curso = _CursoFake(
            ambito=AmbitoFormacion.PROFESIONAL,
            primer_carrera=None,
            profesional=None,
            matricula_interno=500.0,
        )

        normalizar_matriculas(curso)

        assert curso.matricula_interno == 0.0
        assert curso.matricula_primer_carrera == 0.0
        assert curso.matricula_profesional == 0.0
        assert curso.matricula_primer_carrera is not None
        assert curso.matricula_profesional is not None

    def test_continua_materializa_los_defaults_en_el_curso(self):
        """
        Se guarda el numero en vez de dejarlo implicito, para que lo que
        muestra la pantalla sea lo que se va a cobrar.
        """
        curso = _CursoFake(ambito=AmbitoFormacion.EDUCACION_CONTINUA)

        normalizar_matriculas(curso)

        assert curso.matricula_primer_carrera == settings.MATRICULA_PRIMER_CARRERA_DEFAULT
        assert curso.matricula_profesional == settings.MATRICULA_PROFESIONAL_DEFAULT

    def test_continua_respeta_los_valores_ya_cargados(self):
        curso = _CursoFake(
            ambito=AmbitoFormacion.EDUCACION_CONTINUA,
            primer_carrera=150.0,
            profesional=450.0,
        )

        normalizar_matriculas(curso)

        assert curso.matricula_primer_carrera == 150.0
        assert curso.matricula_profesional == 450.0

    def test_continua_respeta_un_cero_explicito(self):
        """
        Un 0 puesto a proposito NO se pisa con el default. Es la diferencia
        entre "no cobra" y "no completaron el dato", que es justo lo que el
        sistema no distinguia.
        """
        curso = _CursoFake(
            ambito=AmbitoFormacion.EDUCACION_CONTINUA,
            primer_carrera=0.0,
            profesional=0.0,
        )

        normalizar_matriculas(curso)

        assert curso.matricula_primer_carrera == 0.0
        assert curso.matricula_profesional == 0.0

    def test_el_ciclo_completo_no_cobra_en_profesional(self):
        """
        Extremo a extremo: se resuelve el ambito, se normaliza y se cobra.
        Es el escenario de la capacitacion, ahora correcto.
        """
        curso = _CursoFake(matricula_interno=0.0)
        curso.ambito = resolver_ambito("maestría")
        normalizar_matriculas(curso)

        assert get_matricula_for_student(curso, _EstudianteFake(False)) == 0.0
