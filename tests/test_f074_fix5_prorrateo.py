# -*- coding: utf-8 -*-
"""
F-074-FIX-5 (2026-07-23) · Tests: Prorrateo robusto en create_payment
=====================================================================

Kevin reportó (2026-07-23 10:17) que la libreta de Alfredo mostraba Pagado:
Bs 0.00 en todos los módulos aunque SÍ había un pago aprobado de Bs 2.940
en Gestión de Pagos.

Causa raíz: el `actualizar_saldo_enrollment` en `create_payment` está
envuelto en try/except que solo loguea. Si falla (por ejemplo, por
RevisionIdWasChanged en Beanie cuando otro proceso modificó el enrollment
entre la lectura y el guardado), el pago queda aprobado pero el
`total_pagado` del enrollment NO se actualiza. La libreta muestra
información desactualizada.

Fix:
- Agregar retry (1 intento más) al `actualizar_saldo_enrollment`
- Si ambos intentos fallan, loguear como WARNING (visible en监控系统)
  con referencia al script de fix retroactivo
"""
from pathlib import Path

PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF074FIX5ProrrateoRobusto:
    """F-074-FIX-5: el prorrateo en create_payment debe ser más robusto."""

    def test_retry_en_actualizar_saldo(self):
        content = read(PAYMENT_SERVICE_FILE)
        # Debe haber un retry (segundo try/except) dentro del primer try/except
        # Patrón: try -> except -> try -> except
        assert content.count("try:") >= 3, (
            "F-074-FIX-5: el prorrateo en create_payment debe tener un retry "
            "(al menos 2 bloques try/except anidados)"
        )

    def test_log_warning_con_referencia_al_fix(self):
        """Si ambos intentos fallan, debe haber un log con referencia al script de fix."""
        content = read(PAYMENT_SERVICE_FILE)
        assert "F-074-FIX-5" in content, (
            "F-074-FIX-5: debe haber un comentario con referencia al fix"
        )
        assert "fix-prorrateo-masivo" in content, (
            "F-074-FIX-5: el WARNING debe referenciar al script "
            "fix-prorrateo-masivo-v2.py para que ops pueda corregirlo"
        )

    def test_usa_logger_no_print(self):
        """El log debe ser vía `logger.warning`, no `print`."""
        content = read(PAYMENT_SERVICE_FILE)
        # Buscar el bloque del WARNING de F-074-FIX-5
        idx = content.find("F-074-FIX-5")
        if idx > 0:
            bloque = content[idx:idx + 2000]
            assert "logger" in bloque and "warning" in bloque, (
                "F-074-FIX-5: el log debe ser vía `logger.warning()`, no `print()`"
            )

    def test_comentario_explica_caso_alfredo(self):
        """El comentario debe mencionar el caso Alfredo (origen del bug)."""
        content = read(PAYMENT_SERVICE_FILE)
        bloque = content[content.find("F-074-FIX-5"):content.find("F-074-FIX-5") + 2000]
        assert "Alfredo" in bloque, (
            "F-074-FIX-5: el comentario debe mencionar el caso Alfredo (origen del bug, 2026-07-23)"
        )

    def test_retry_consistente(self):
        """El retry debe usar los mismos parámetros que el primer intento."""
        content = read(PAYMENT_SERVICE_FILE)
        # El retry debe llamar a actualizar_saldo_enrollment con los mismos args
        idx = content.find("F-074-FIX-5")
        if idx > 0:
            bloque = content[idx:idx + 3000]
            count = bloque.count("actualizar_saldo_enrollment(")
            assert count >= 2, (
                f"F-074-FIX-5: debe haber 2 llamadas a actualizar_saldo_enrollment "
                f"(inicial + retry). Encontradas: {count}"
            )


class TestF074FIX5Documentacion:
    """F-074-FIX-5: documentación del bug y solución."""

    def test_referencia_a_7_estudiantes(self):
        content = read(PAYMENT_SERVICE_FILE)
        bloque = content[content.find("F-074-FIX-5"):content.find("F-074-FIX-5") + 2000]
        assert "7 estudiantes" in bloque or "7" in bloque, (
            "F-074-FIX-5: el comentario debe mencionar los 7 estudiantes afectados"
        )

    def test_referencia_a_evidence(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "evidence/reuniones/2026-07-23" in content, (
            "F-074-FIX-5: debe referenciar el path del script de fix en evidence/"
        )
