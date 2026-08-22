"""
Auditoría completa 2026-08-22 — hallazgos MENORES, verificados.
"""

import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestPreRegistrationsSinDecoradorDuplicado:
    def test_forms_solo_se_registra_una_vez(self):
        src = _fuente("api", "pre_registrations.py")
        assert src.count('"/forms",') == 2  # GET list_forms + otro endpoint distinto (POST/etc)


class TestDiscountConIndices:
    def test_discount_declara_indexes(self):
        src = _fuente("models", "discount.py")
        ini = src.index("class Settings:")
        fin = src.index("class Config:", ini)
        cuerpo = src[ini:fin]
        assert "indexes" in cuerpo
        assert '"curso_id"' in cuerpo
        assert '"lista_estudiantes"' in cuerpo
