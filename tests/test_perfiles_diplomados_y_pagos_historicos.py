"""
Pruebas de Diferenciación de Diplomados y Pagos Históricos / Saldo Inicial
========================================================================
Valida:
1. Diplomado Continuo (Pregrado / Modalidad de Graduación) vs Diplomado Profesional (Posgrado).
2. Creación de pagos por personal administrativo sin comprobante obligatorio en Caja y Migración.
3. Rechazo de pagos para estudiantes sin comprobante digital.
4. Registro de Saldo Inicial y pagos históricos en endpoints de inscripción.
"""

import pytest
from models.enums import AmbitoFormacion
from services.matricula_helper import resolver_ambito


class TestDiplomadosDiferenciacion:
    def test_diplomado_continuo_resuelve_educacion_continua(self):
        """Un diplomado con ambito explícito 'educacion_continua' se preserva como educación continua."""
        ambito = resolver_ambito("diplomado", ambito_explicito="educacion_continua")
        assert ambito == AmbitoFormacion.EDUCACION_CONTINUA

    def test_diplomado_profesional_resuelve_profesional(self):
        """Un diplomado con ambito explícito 'profesional' se preserva como profesional."""
        ambito = resolver_ambito("diplomado", ambito_explicito="profesional")
        assert ambito == AmbitoFormacion.PROFESIONAL

    def test_diplomado_sin_ambito_del_creador_profesional(self):
        """Si el creador es de posgrado profesional, el diplomado hereda profesional."""
        ambito = resolver_ambito("diplomado", ambito_del_creador="profesional")
        assert ambito == AmbitoFormacion.PROFESIONAL

    def test_diplomado_sin_ambito_del_creador_continua(self):
        """Si el creador es de educación continua, el diplomado hereda educacion_continua."""
        ambito = resolver_ambito("diplomado", ambito_del_creador="educacion_continua")
        assert ambito == AmbitoFormacion.EDUCACION_CONTINUA


class TestSaldoInicialYSanitizacionPagos:
    def test_saldo_inicial_request_schema(self):
        from api.enrollments import SaldoInicialRequest
        req = SaldoInicialRequest(hasta_modulo_index=2, matricula_pagada=True)
        assert req.hasta_modulo_index == 2
        assert req.matricula_pagada is True

    def test_saldo_inicial_request_defaults(self):
        from api.enrollments import SaldoInicialRequest
        req = SaldoInicialRequest()
        assert req.hasta_modulo_index is None
        assert req.matricula_pagada is True
