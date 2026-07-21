"""
Tests de timezone_utils (TECH-001)
===================================

Tests puros (sin DB) de las funciones de tiempo. La función `utcnow_naive()`
es la base de TODA la lógica de pagos/congelados — un bug aquí rompe
cálculos de mora, fechas de pago, etc.
"""

import pytest
from datetime import datetime, timedelta, timezone

from core.timezone_utils import utcnow_naive, to_bolivia_time, convert_dict_dates_to_bolivia


class TestUtcnowNaive:
    """Tests de `utcnow_naive()` — la base de toda la lógica de tiempo."""

    def test_devuelve_datetime(self):
        result = utcnow_naive()
        assert isinstance(result, datetime)

    def test_no_tiene_tzinfo(self):
        """DEBE ser naive (sin tzinfo) para compatibilidad con MongoDB."""
        result = utcnow_naive()
        assert result.tzinfo is None, f"Esperaba naive, recibí {result.tzinfo}"

    def test_es_aproximadamente_ahora(self):
        """Debe estar dentro de ±5 segundos del momento actual."""
        before = datetime.utcnow()
        result = utcnow_naive()
        after = datetime.utcnow()
        assert before <= result <= after

    def test_no_retorna_futuro_lejano(self):
        """Sanity check: no retorna fechas absurdas."""
        result = utcnow_naive()
        assert result.year >= 2024
        assert result.year <= 2030


class TestToBoliviaTime:
    """Tests de `to_bolivia_time()` — formato de exibição."""

    def test_formato_correcto(self):
        utc_dt = datetime(2026, 7, 18, 20, 0, 0)  # 20:00 UTC = 16:00 Bolivia
        result = to_bolivia_time(utc_dt)
        assert "16:00" in result or "16" in result
        # El formato exacto puede variar, pero debe incluir hora
        assert ":" in result

    def test_none_retorna_string_vacio(self):
        result = to_bolivia_time(None)
        assert result == "" or result == "—"

    def test_resta_4_horas_a_utc(self):
        """Bolivia es UTC-4. Si UTC=20:00, Bolivia=16:00."""
        utc_dt = datetime(2026, 1, 15, 12, 0, 0)
        result = to_bolivia_time(utc_dt)
        # Esperamos que aparezca "08:00" en el resultado
        assert "08:00" in result, f"Esperaba '08:00' en '{result}'"

    def test_cambio_dia_por_atraso_de_4h(self):
        """UTC 02:00 → Bolivia 22:00 del día anterior."""
        utc_dt = datetime(2026, 1, 15, 2, 0, 0)  # UTC 2 AM
        result = to_bolivia_time(utc_dt)
        # Debe ser 22:00 del 14 de enero
        assert "22:00" in result
        assert "14" in result or "/01/14" in result or "ene" in result.lower()


class TestConvertDictDatesToBolivia:
    """Tests de `convert_dict_dates_to_bolivia()` — recibe lista de campos fecha."""

    def test_convierte_campos_especificados(self):
        data = {
            "nombre": "Juan",
            "fecha_pago": datetime(2026, 7, 18, 20, 0, 0),
        }
        result = convert_dict_dates_to_bolivia(data, ["fecha_pago"])
        assert isinstance(result["fecha_pago"], str)
        assert "16:00" in result["fecha_pago"]
        assert result["nombre"] == "Juan"

    def test_preserva_campos_no_listados(self):
        data = {
            "nombre": "Juan",
            "created_at": datetime(2026, 7, 18, 20, 0, 0),
        }
        result = convert_dict_dates_to_bolivia(data, [])  # sin campos a convertir
        # created_at queda como datetime (no se tocó)
        assert isinstance(result["created_at"], datetime)

    def test_ignora_campos_inexistentes(self):
        data = {"nombre": "Juan"}
        result = convert_dict_dates_to_bolivia(data, ["fecha_pago", "created_at"])
        assert result == data

    def test_solo_convierte_los_listados(self):
        data = {
            "fecha_pago": datetime(2026, 7, 18, 20, 0, 0),
            "created_at": datetime(2026, 7, 18, 20, 0, 0),
        }
        result = convert_dict_dates_to_bolivia(data, ["fecha_pago"])
        assert isinstance(result["fecha_pago"], str)
        assert isinstance(result["created_at"], datetime)  # NO se convirtió
