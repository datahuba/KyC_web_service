"""
Tests para F-FIX-DASHBOARD-CXC-DIFF (2026-08-17)
=================================================

Cubre el bug real detectado en producción: el dashboard mostraba una
cifra de "por cobrar" distinta a la del reporte real de Cuentas por
Cobrar (diferencia de ~Bs 2.200) para el mismo universo de inscripciones.

Causa: `_build_resumen_economico_from_memory` y `_build_cxc_resumen_from_memory`
(api/dashboard.py) calculaban el saldo confiando en el campo cacheado
`enrollment.total_pagado` / `modulos[].monto_pagado`, mientras que
`generar_resumen_cxc` (services/cuentas_por_cobrar_service.py, la fuente de
verdad) siempre recalcula sumando los Payment con estado_pago=APROBADO de
esa inscripción. Si el campo cacheado se desincroniza, las dos cifras
divergen. El fix hace que el dashboard use la misma fuente (pagos reales
agrupados por inscripcion_id) que el reporte real.
"""
from types import SimpleNamespace

from api.dashboard import (
    _build_resumen_economico_from_memory,
    _build_cxc_resumen_from_memory,
)
from models.enums import EstadoInscripcion


def _enrollment(id_, total_a_pagar, estado=EstadoInscripcion.ACTIVO.value, total_pagado=0.0):
    return SimpleNamespace(
        id=id_,
        estado=estado,
        total_a_pagar=total_a_pagar,
        total_pagado=total_pagado,
        modulos=[],
        excluir_por_cobrar=False,
    )


def _payment(inscripcion_id, cantidad_pago, concepto="colegiatura"):
    return SimpleNamespace(
        inscripcion_id=inscripcion_id,
        cantidad_pago=cantidad_pago,
        concepto=concepto,
    )


class TestResumenEconomicoUsaPagosReales:
    def test_por_cobrar_ignora_total_pagado_desincronizado(self):
        # enrollment.total_pagado quedó en 0 (desync), pero SÍ hay un pago
        # aprobado real de 300 para esa inscripción. El cálculo correcto
        # (igual que el reporte real de CxC) debe usar el pago real, no el
        # campo cacheado desincronizado.
        e = _enrollment("e1", total_a_pagar=1000, total_pagado=0.0)
        pagos = [_payment("e1", 300)]
        pagos_por_inscripcion = {"e1": pagos}

        resumen = _build_resumen_economico_from_memory(
            pagos=pagos,
            enrollments=[e],
            pagos_por_inscripcion=pagos_por_inscripcion,
        )

        assert resumen["por_cobrar"] == 700.0

    def test_sin_pagos_por_inscripcion_cae_a_campo_cacheado(self):
        # Compatibilidad hacia atrás: si no se pasa pagos_por_inscripcion,
        # sigue funcionando con el campo cacheado (no debe romper llamadas
        # existentes).
        e = _enrollment("e1", total_a_pagar=1000, total_pagado=400.0)
        resumen = _build_resumen_economico_from_memory(pagos=[], enrollments=[e])
        assert resumen["por_cobrar"] == 600.0


class TestCxcResumenUsaPagosReales:
    def test_por_cobrar_coincide_con_resumen_economico(self):
        # Ambas funciones del dashboard deben dar el MISMO por_cobrar para
        # el mismo universo — que es justamente lo que estaba roto.
        e1 = _enrollment("e1", total_a_pagar=1000, total_pagado=0.0)
        e2 = _enrollment("e2", total_a_pagar=2000, total_pagado=2000.0)  # cacheado dice pagado completo
        pagos = [_payment("e1", 300), _payment("e2", 1500)]  # pero el pago real es solo 1500
        pagos_por_inscripcion = {"e1": [pagos[0]], "e2": [pagos[1]]}

        resumen_eco = _build_resumen_economico_from_memory(
            pagos=pagos, enrollments=[e1, e2], pagos_por_inscripcion=pagos_por_inscripcion,
        )
        resumen_cxc = _build_cxc_resumen_from_memory(
            enrollments=[e1, e2], pagos=pagos, pagos_por_inscripcion=pagos_por_inscripcion,
        )

        # e1: 1000 - 300 = 700 ; e2: 2000 - 1500 = 500 (NO 0, que es lo que
        # daría el campo cacheado total_pagado=2000)
        assert resumen_eco["por_cobrar"] == 1200.0
        assert resumen_cxc["por_cobrar"] == 1200.0

    def test_excluye_estados_no_cobrables(self):
        e = _enrollment("e1", total_a_pagar=1000, estado=EstadoInscripcion.COMPLETADO.value)
        resumen = _build_cxc_resumen_from_memory(
            enrollments=[e], pagos=[], pagos_por_inscripcion={},
        )
        assert resumen["por_cobrar"] == 0.0
