"""
F-CUENTAS-HISTORICAS (2026-08-16)
=================================

Kevin: "todo programa historico ya no debe contarse como actual, solo son
datos para tener guardados pero debemos siempre tenerlos en cuenta con
nuevos informes solo de esos programas".

Los historicos salieron del Dashboard y de Cuentas por Cobrar; este
servicio es su contraparte: el expediente economico de esos programas.

Decisiones de criterio que estos tests fijan:

1. COMPLETADO NO se excluye. En CxC si se excluye (es cartera que ya no se
   persigue), pero en un historico ese es el estado ESPERADO de casi todas
   las inscripciones: excluirlo dejaria el informe vacio y sin utilidad
   como expediente. Se siguen excluyendo CANCELADO y RETIRADO, que nunca
   fueron cartera real.

2. El estado se serializa por su `.value`. Detectado probando con datos
   reales: `str(enum)` devuelve "EstadoInscripcion.PENDIENTE_PAGO", que es
   basura para la UI.

3. Los pagos se cargan EN LOTE, no una query por inscripcion — misma
   leccion que F-FIX-CXC-N1, donde ese patron hacia que el reporte tardara
   36s y el frontend lo abortara.
"""

import io
import os

from models.enums import EstadoInscripcion
from services.cuentas_historicas_service import (
    ESTADOS_EXCLUIDOS_HIST,
    _nombre_estudiante,
)


def _fuente():
    ruta = os.path.join(
        os.path.dirname(__file__), "..", "services", "cuentas_historicas_service.py"
    )
    return io.open(ruta, encoding="utf-8").read()


class TestCriterioDeEstados:
    def test_completado_cuenta_en_historicos(self):
        """Es el estado normal de un programa terminado: no puede excluirse."""
        assert EstadoInscripcion.COMPLETADO not in ESTADOS_EXCLUIDOS_HIST

    def test_cancelado_y_retirado_siguen_fuera(self):
        assert EstadoInscripcion.CANCELADO in ESTADOS_EXCLUIDOS_HIST
        assert EstadoInscripcion.RETIRADO in ESTADOS_EXCLUIDOS_HIST

    def test_el_criterio_difiere_del_de_cxc(self):
        """
        Si alguien iguala las dos listas 'por consistencia', rompe el informe
        historico. Este test documenta que la diferencia es intencional.
        """
        from services.cuentas_por_cobrar_service import ESTADOS_EXCLUIDOS_CXC

        assert ESTADOS_EXCLUIDOS_HIST != ESTADOS_EXCLUIDOS_CXC
        assert EstadoInscripcion.COMPLETADO in ESTADOS_EXCLUIDOS_CXC


class TestSerializacionDelEstado:
    def test_usa_value_y_no_el_repr_del_enum(self):
        src = _fuente()
        assert 'getattr(e.estado, "value", None)' in src, (
            "el estado debe serializarse por .value; str(enum) devuelve "
            "'EstadoInscripcion.X' y eso llega asi a la UI"
        )


class TestNombreEstudiante:
    def test_siempre_devuelve_string(self):
        class S:
            def __init__(self, n, r):
                self.nombre, self.registro = n, r

        assert _nombre_estudiante(S("PEREZ JUAN", "1")) == "PEREZ JUAN"
        assert isinstance(_nombre_estudiante(S(None, "99001")), str)
        assert isinstance(_nombre_estudiante(None), str)

    def test_sin_nombre_muestra_el_registro(self):
        class S:
            nombre = None
            registro = "123"

        assert "123" in _nombre_estudiante(S())


class TestSinConsultaPorInscripcion:
    def test_los_pagos_se_cargan_en_lote(self):
        """Regresion de F-FIX-CXC-N1: nada de un Payment.find por enrollment."""
        src = _fuente()
        inicio = src.index("async def generar_resumen_historico")
        cuerpo = src[inicio:]
        bucle = cuerpo.index("for e in enrollments:")
        codigo_bucle = "\n".join(
            l for l in cuerpo[bucle:].splitlines() if not l.strip().startswith("#")
        )
        assert "await Payment.find" not in codigo_bucle
        assert '"inscripcion_id": {"$in"' in cuerpo


class TestAlcancePorRol:
    def test_respeta_cursos_asignados(self):
        """Un encargado segmentado solo debe ver sus propios historicos."""
        src = _fuente()
        assert "current_user.cursos_asignados" in src
