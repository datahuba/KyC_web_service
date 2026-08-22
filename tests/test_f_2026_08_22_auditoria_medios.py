"""
Auditoría completa 2026-08-22 — hallazgos de severidad MEDIA (deuda
técnica), verificados.
"""

import io
import os

import pytest


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestBugReportsStatsUsaAggregate:
    def test_usa_group_en_vez_de_count_por_estado(self):
        src = _fuente("api", "bug_reports.py")
        ini = src.index('async def stats(')
        fin = src.index("\n\n@router.", ini)
        cuerpo = src[ini:fin]
        assert "aggregate(" in cuerpo
        assert "$group" in cuerpo
        # No debe quedar el loop viejo de un .count() por estado
        assert ".find({**base" not in cuerpo


class TestN1Corregidos:
    def test_assign_course_to_users_usa_bulk_fetch(self):
        src = _fuente("services", "user_service.py")
        ini = src.index("async def assign_course_to_users")
        fin = src.index("\n\nasync def ", ini)
        cuerpo = src[ini:fin]
        assert "In(User.id" in cuerpo
        assert "usuarios_a_agregar" in cuerpo

    def test_anular_duplicados_usa_bulk_fetch(self):
        src = _fuente("api", "admin_data_health.py")
        ini = src.index('elif tipo_accion == "anular_duplicados"')
        fin = src.index("\n\n    elif ", ini)
        cuerpo = src[ini:fin]
        assert "In(Payment.id" in cuerpo

    def test_asistencia_bulk_usa_bulk_fetch(self):
        src = _fuente("api", "asistencia.py")
        ini = src.index("F-2026-08-11-ASISTENCIA: bulk-register")
        cuerpo = src[ini: ini + 2000]
        assert "existentes_por_estudiante" in cuerpo
        assert ".find(\n        AsistenciaRegistro.sesion_id == sesion_id\n    ).to_list()" in cuerpo or "AsistenciaRegistro.find(" in cuerpo

    def test_courses_pagos_historicos_usa_bulk_fetch(self):
        src = _fuente("api", "courses.py")
        idx = src.index("F-FIX-N1-PAGOS-HISTORICOS")
        cuerpo = src[idx: idx + 700]
        assert "pagos_por_cuota" in cuerpo

    def test_enrollments_pagos_historicos_usa_bulk_fetch(self):
        src = _fuente("api", "enrollments.py")
        idx = src.index("F-FIX-N1-PAGOS-HISTORICOS")
        cuerpo = src[idx: idx + 700]
        assert "pagos_por_cuota" in cuerpo


class TestPrintReemplazadoPorLogger:
    """Los print() que tapaban fallas de notificacion en el flujo de
    pagos/inscripciones ahora usan logging.getLogger(...).warning()."""

    def test_payment_service_no_tiene_prints_de_error_swallowing(self):
        src = _fuente("services", "payment_service.py")
        # Los 2 prints de auditoria (intencionales, doble canal) siguen.
        assert 'print(f"Error imprimiendo auditoría' in src
        assert 'print(f"Error guardando auditoría en Mongo' in src
        # El resto de los "Error ..." de notificaciones ya no son print().
        lineas_error_print = [
            l for l in src.splitlines()
            if l.strip().startswith('print(f"Error')
            and "auditoría" not in l
        ]
        assert lineas_error_print == [], f"Quedan print() de error sin migrar: {lineas_error_print}"
        assert 'logging.getLogger("kyc.payment")' in src

    def test_enrollments_no_tiene_prints_de_error_swallowing(self):
        src = _fuente("api", "enrollments.py")
        lineas_error_print = [
            l for l in src.splitlines()
            if l.strip().startswith('print(f"Error')
        ]
        assert lineas_error_print == [], f"Quedan print() de error sin migrar: {lineas_error_print}"
        assert 'logging.getLogger("kyc.enrollments")' in src
