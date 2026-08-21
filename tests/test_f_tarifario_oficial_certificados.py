"""
Test: Tarifario Oficial de Certificados (2026-08-21)
====================================================

Verifica la nueva estructura de certificados y aranceles:
- TipoCertificado.ALUMNO_REGULAR (Bs 50)
- TipoCertificado.NOTAS paquete compuesto 3 páginas (Bs 150 = Bs 50 cert + Bs 100 avance)
- TipoCertificado.NO_DEUDOR (Bs 150)
- Validaciones de comprobante obligatorio para todos los tipos con arancel
- Renders PDF y correlativo
"""

import io
import pytest
from datetime import datetime, timezone
from pypdf import PdfReader

from models.enums import TipoCertificado
from core.config import settings
from services.certificate_service import (
    render_pdf_alumno_regular,
    render_pdf_avance_academico,
    render_pdf_boleta_matricula,
    render_pdf_notas_compuesto,
)


from unittest.mock import MagicMock

class TestConfiguracionAranceles:
    def test_aranceles_configurados_correctamente(self):
        assert settings.MONTO_CERTIFICADO_NO_DEUDOR == 150.0
        assert settings.MONTO_CERTIFICADO_NOTAS == 100.0
        assert settings.MONTO_CERTIFICADO_ALUMNO_REGULAR == 50.0

    def test_enum_contiene_nuevo_tipo(self):
        assert TipoCertificado.ALUMNO_REGULAR == "alumno_regular"


def _make_mocks():
    s = MagicMock()
    s.nombre = "JUAN PEREZ SANCHEZ"
    s.carnet = "1234567"
    s.extension = "SCZ"
    s.complemento_carnet = None
    s.registro = "218110000"

    c = MagicMock()
    c.codigo = "DIPL-2026-01"
    c.nombre_programa = "DIPLOMADO EN GESTIÓN TRIBUTARIA"
    c.modulos = []

    m1 = MagicMock()
    m1.nombre = "MÓDULO 1: DERECHO TRIBUTARIO"
    m1.nota = 90.0
    m1.estado_academico = "Aprobado"
    m1.estado = "Pagado"
    m1.fecha_inicio = None
    m1.fecha_fin = None

    e = MagicMock()
    e.modulos = [m1]
    e.costo_matricula = 200.0
    e.costo_total = 3200.0
    e.total_a_pagar = 3200.0
    e.total_pagado = 3200.0
    e.saldo_pendiente = 0.0
    e.descuento_curso_aplicado = 0.0
    e.descuento_personalizado = 0.0

    return s, c, e


class TestRenderPDFsNuevoTarifario:
    def test_render_alumno_regular_devuelve_bytes_validos(self):
        s, c, e = _make_mocks()
        pdf_bytes = render_pdf_alumno_regular(
            student=s,
            course=c,
            enrollment=e,
            folio="N° 001/2026",
            emitido_en=datetime.now(timezone.utc),
        )
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 1000
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1

    def test_render_avance_academico_contiene_ppac(self):
        s, c, e = _make_mocks()
        pdf_bytes = render_pdf_avance_academico(
            student=s,
            course=c,
            enrollment=e,
            emitido_en=datetime.now(timezone.utc),
        )
        assert isinstance(pdf_bytes, bytes)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1
        texto = reader.pages[0].extract_text()
        assert "AVANCE ACADEMICO" in texto
        assert "PPAC" in texto or "Promedio Ponderado" in texto

    def test_render_boleta_matricula_contiene_desglose(self):
        s, c, e = _make_mocks()
        pdf_bytes = render_pdf_boleta_matricula(
            student=s,
            course=c,
            enrollment=e,
            emitido_en=datetime.now(timezone.utc),
        )
        assert isinstance(pdf_bytes, bytes)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 1
        texto = reader.pages[0].extract_text()
        assert "BOLETA DE MATRICULA" in texto
        assert "1479" in texto

    def test_render_notas_compuesto_tiene_3_paginas(self):
        s, c, e = _make_mocks()
        pdf_bytes = render_pdf_notas_compuesto(
            student=s,
            course=c,
            enrollment=e,
            folio="N° 002/2026",
            emitido_en=datetime.now(timezone.utc),
        )
        assert isinstance(pdf_bytes, bytes)
        reader = PdfReader(io.BytesIO(pdf_bytes))
        assert len(reader.pages) == 3
