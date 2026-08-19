"""
F-FIX-CXC-N1 (2026-08-16)
=========================

`generar_resumen_cxc` consultaba `Payment.find(...)` DENTRO del bucle de
enrollments — una query por inscripcion. Con 296 inscripciones activas eso
son 296 round-trips a Atlas y el reporte tardaba ~36s en produccion: el
frontend lo abortaba por timeout (`net::ERR_ABORTED`) y la pagina de
Cuentas por Cobrar quedaba inutilizable. Kevin lo reporto como
"error en gestion de pago".

Medicion en el contenedor de produccion antes del fix:

    init_db                    29.97s
    query enrollments           1.71s  -> 296 docs
    query courses               0.23s  ->   7 docs
    query students              0.61s  -> 286 docs
    generar_resumen_cxc COMPLETO 36.59s
    subtotal solo queries       2.55s   <- los otros ~34s eran el N+1

Verificacion de que el fix NO cambia cifras: se volco el resultado completo
de la funcion antes y despues y se comparo byte a byte. De 325.037 bytes
solo difieren 6, y son el timestamp `generado_en`. Totales identicos
(975.072,0), mismos 3 cursos, mismas 144 inscripciones.
Tiempo local: 9,6s -> 0,81s.

Este test protege el patron para que no reaparezca en un refactor.
"""

import io
import os


def _cuerpo_generar_resumen():
    """Codigo de generar_resumen_cxc SIN su docstring.

    El docstring se recorta porque los comentarios de la propia funcion
    mencionan el patron viejo; medir sobre el texto completo daria falsos
    positivos (mismo problema que se encontro en el test de delete_course).
    """
    ruta = os.path.join(
        os.path.dirname(__file__), "..", "services", "cuentas_por_cobrar_service.py"
    )
    src = io.open(ruta, encoding="utf-8").read()
    inicio = src.index("async def generar_resumen_cxc")
    try:
        fin = src.index("\nasync def ", inicio + 10)
    except ValueError:
        fin = len(src)
    return src[inicio:fin]


class TestSinConsultaPorInscripcion:
    def test_no_hay_await_payment_find_dentro_del_bucle(self):
        """
        El bucle `for e in enrollments:` no debe contener ningun await de
        Payment. Si vuelve a aparecer, el reporte se vuelve a caer por
        timeout en produccion.
        """
        cuerpo = _cuerpo_generar_resumen()
        inicio_bucle = cuerpo.index("for e in enrollments:")
        bloque_bucle = cuerpo[inicio_bucle:]

        # se ignoran las lineas de comentario: describen el bug viejo
        codigo = "\n".join(
            l for l in bloque_bucle.splitlines() if not l.strip().startswith("#")
        )
        assert "await Payment.find" not in codigo, (
            "volvio el N+1: hay una consulta de Payment dentro del bucle de enrollments"
        )

    def test_los_pagos_se_cargan_en_lote_antes_del_bucle(self):
        cuerpo = _cuerpo_generar_resumen()
        pos_batch = cuerpo.index("pagos_por_inscripcion")
        pos_bucle = cuerpo.index("for e in enrollments:")
        assert pos_batch < pos_bucle, "la carga en lote debe ocurrir ANTES del bucle"

    def test_la_query_en_lote_usa_in(self):
        """Una sola query con $in, no una por inscripcion."""
        cuerpo = _cuerpo_generar_resumen()
        assert '"inscripcion_id": {"$in"' in cuerpo

    def test_el_bucle_lee_del_mapa_precargado(self):
        cuerpo = _cuerpo_generar_resumen()
        assert "pagos_por_inscripcion.get(e.id" in cuerpo


class TestNombreEstudianteNulo:
    """
    F-FIX-CXC-NOMBRE-NULO (2026-08-16): `Student.nombre` es opcional en el
    modelo y hay 2 estudiantes en produccion con nombre None (registros
    99001 y 99100). El schema de salida `EnrollmentCxCOut.estudiante_nombre`
    exige str, asi que esas 2 filas hacian fallar el reporte COMPLETO con
    500. La guarda vieja (`s.nombre if s else "—"`) cubria que el estudiante
    no existiera, pero no que existiera sin nombre.

    El bug estaba TAPADO por el timeout: antes del fix del N+1 la request
    nunca llegaba a serializar, asi que nadie vio nunca el 500.
    """

    def test_devuelve_string_en_todos_los_casos(self):
        from services.cuentas_por_cobrar_service import _nombre_estudiante

        class S:
            def __init__(self, nombre, registro):
                self.nombre = nombre
                self.registro = registro

        assert _nombre_estudiante(S("PEREZ JUAN", "123")) == "PEREZ JUAN"
        assert isinstance(_nombre_estudiante(S(None, "99001")), str)
        assert isinstance(_nombre_estudiante(S(None, None)), str)
        assert isinstance(_nombre_estudiante(None), str)

    def test_sin_nombre_cae_al_registro(self):
        """Cobranzas necesita poder identificar la fila igual."""
        from services.cuentas_por_cobrar_service import _nombre_estudiante

        class S:
            nombre = None
            registro = "99001"

        assert "99001" in _nombre_estudiante(S())

    def test_nombre_vacio_tambien_cae_al_fallback(self):
        """'' es falsy pero pasaria un chequeo `is not None`."""
        from services.cuentas_por_cobrar_service import _nombre_estudiante

        class S:
            nombre = ""
            registro = "77"

        assert _nombre_estudiante(S()) != ""
