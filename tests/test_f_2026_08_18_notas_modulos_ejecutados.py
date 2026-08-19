"""
F-NOTAS-MODULOS-EJECUTADOS (2026-08-18)
========================================

Un programa que arranca a mitad de camino (ej. entra en el modulo 5) tiene
los modulos anteriores ya dictados, con nota. La carga inicial trae pagos
por modulo pero NUNCA trajo notas — eso dejaba a esos estudiantes con el
historial academico en blanco hasta que alguien las cargara a mano, modulo
por modulo, desde la libreta.

Kevin eligio resolverlo con "un Excel aparte, solo de notas", para
estudiantes que YA EXISTEN en el sistema (a diferencia de la carga inicial,
que tambien puede crear estudiantes nuevos).

Esta suite prueba:
1. `_detectar_columnas_notas` a fondo — es la logica de parseo, el mismo
   tipo de heuristica que ya causo el "pago fantasma de 1 Bs" en el Excel de
   carga inicial (una columna "MODULO" con el numero de modulo del alumno
   se leia como un importe). Aca el riesgo equivalente es confundir "Nota
   Modulo 1" con cualquier columna que tenga un numero.
2. Que `cargar_notas_modulos_excel` reutilice `actualizar_nota_modulo` en
   vez de escribir el campo directo (para no perderse el recalculo de
   perdida de beca ni el promedio).
3. Que el endpoint NO cree estudiantes ni inscripciones nuevas — a
   diferencia de la carga inicial, a proposito.
"""

import io
import os

import pytest

from services.enrollment_service import _detectar_columnas_notas


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestDetectarColumnasNotas:
    def test_detecta_ci_y_notas_de_modulos(self):
        headers = ["N", "Nombre Completo", "CI", "Nota Modulo 1", "Nota Modulo 2"]
        col_carnet, columnas = _detectar_columnas_notas(
            [h.lower() for h in headers]
        )
        assert col_carnet == 3
        assert columnas == [(4, 0), (5, 1)]

    def test_sin_espacios_ni_acentos_tambien_matchea(self):
        col_carnet, columnas = _detectar_columnas_notas(
            ["carnetdeidentidad", "notamodulo1", "notamodulo2"]
        )
        assert col_carnet == 1
        assert columnas == [(2, 0), (3, 1)]

    def test_no_confunde_la_columna_modulo_sin_nota_con_una_columna_de_notas(self):
        """
        Mismo tipo de bug que el pago fantasma de 1 Bs en la carga inicial:
        una columna "MODULO" (sin la palabra "nota") no debe interpretarse
        como una nota, aunque tenga un numero en el valor.
        """
        col_carnet, columnas = _detectar_columnas_notas(
            ["ci", "modulo", "modulo actual"]
        )
        assert columnas == []

    def test_reconoce_cedula_e_identidad_como_alias_de_ci(self):
        col_carnet, _ = _detectar_columnas_notas(["cedula de identidad"])
        assert col_carnet == 1
        col_carnet2, _ = _detectar_columnas_notas(["numero de identidad"])
        assert col_carnet2 == 1

    def test_sin_columna_de_notas_devuelve_lista_vacia(self):
        col_carnet, columnas = _detectar_columnas_notas(["ci", "nombre", "celular"])
        assert col_carnet == 1
        assert columnas == []

    def test_sin_columna_de_ci_devuelve_cero(self):
        col_carnet, _ = _detectar_columnas_notas(["nombre", "nota modulo 1"])
        assert col_carnet == 0

    def test_columnas_vacias_se_ignoran(self):
        col_carnet, columnas = _detectar_columnas_notas(["ci", "", None, "nota modulo 1"])
        assert col_carnet == 1
        assert columnas == [(4, 0)]


class TestCargarNotasReutilizaLaLogicaOficial:
    def test_no_escribe_el_campo_nota_directamente(self):
        """
        `modulo.nota = ...` directo se saltearia el recalculo de perdida de
        beca por nota minima y el recalculo del promedio (nota_final). Tiene
        que pasar por actualizar_nota_modulo, igual que el flujo manual desde
        la libreta.
        """
        src = _fuente("services", "enrollment_service.py")
        ini = src.index("async def cargar_notas_modulos_excel")
        fin = src.find("\nasync def ", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]

        assert "await actualizar_nota_modulo(" in cuerpo
        assert "modulo.nota = " not in cuerpo
        assert ".nota = round(" not in cuerpo

    def test_no_crea_estudiantes_ni_inscripciones(self):
        """
        A diferencia de la carga inicial (que SI puede crear estudiantes),
        esta carga es SOLO para quienes ya estan inscritos. Si el CI no
        matchea, se reporta como fallido — no se inventa la inscripcion.
        """
        src = _fuente("services", "enrollment_service.py")
        ini = src.index("async def cargar_notas_modulos_excel")
        fin = src.find("\nasync def ", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]

        assert "create_enrollment" not in cuerpo
        assert "Student(" not in cuerpo
        assert "insert()" not in cuerpo

    def test_reporta_fallidos_por_fila_sin_abortar_el_lote(self):
        """
        Un CI que no matchea a ninguna inscripcion de este curso no debe
        tirar la carga entera: se acumula en `fallidos` y se sigue.
        """
        src = _fuente("services", "enrollment_service.py")
        ini = src.index("async def cargar_notas_modulos_excel")
        fin = src.find("\nasync def ", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]

        assert "fallidos.append(" in cuerpo
        assert "continue" in cuerpo


class TestEndpointRespetaCursosAsignados:
    def test_el_encargado_solo_carga_en_sus_cursos(self):
        src = _fuente("api", "courses.py")
        ini = src.index("async def post_notas_modulos_excel")
        fin = src.find("\n@router.", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]
        codigo = "\n".join(
            l for l in cuerpo.splitlines() if not l.strip().startswith("#")
        )

        assert "UserRole.ENCARGADO_CURSO" in codigo
        assert "UserRole.COORDINADOR" in codigo
        assert "cursos_asignados" in codigo
