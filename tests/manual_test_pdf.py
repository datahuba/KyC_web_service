"""
Test funcional standalone del PDF
=================================

Script de validación manual (NO se commitea al repo) que importa las
funciones puras del certificate_service con mocks ligeros y verifica
que el PDF se genera correctamente.

Uso: python.exe tests/manual_test_pdf.py
"""

import sys
import types
from datetime import datetime, timezone

sys.path.insert(0, ".")

# Mock mínimo de los modelos Beanie para que el import del service funcione
m = types.ModuleType("models")
sys.modules["models"] = m
for sub in [
    "certificate",
    "certificate_counter",
    "course",
    "enrollment",
    "enums",
    "student",
    "user",
]:
    sm = types.ModuleType(f"models.{sub}")
    sys.modules[f"models.{sub}"] = sm
    setattr(m, sub, sm)


class _Stub:
    pass


# Stubs de los tipos que usa el service
m.certificate.Certificate = _Stub
m.certificate.ModuloCertificado = _Stub
m.certificate_counter.CertificateCounter = _Stub
m.course.Course = _Stub
m.enrollment.Enrollment = _Stub
m.enrollment.ModuloEstado = _Stub
m.student.Student = _Stub
m.user.User = _Stub
m.enums.TipoCertificado = _Stub
m.enums.EstadoPago = _Stub
m.enums.EstadoInscripcion = _Stub
m.enums.UserRole = _Stub
m.enums.EstadoTitulo = _Stub
m.enums.TipoCurso = _Stub
m.enums.Modalidad = _Stub
m.enums.TipoPago = _Stub
m.enums.Sexo = _Stub
m.enums.EstadoCivil = _Stub
m.enums.TipoSangre = _Stub
m.enums.EstadoRequisito = _Stub
m.enums.SubtipoCoordinador = _Stub
m.enums.AssignmentType = _Stub
m.enums.SubmissionStatus = _Stub
m.enums.TipoTitulo = _Stub

# Stubs de las funciones que el service importa
m.cloudinary_utils = types.ModuleType("core.cloudinary_utils")
m.cloudinary_utils.upload_pdf = lambda *a, **k: None
m.cloudinary_utils.upload_image = lambda *a, **k: None
m.cloudinary_utils.delete_cloudinary_asset = lambda *a, **k: None
sys.modules["core.cloudinary_utils"] = m.cloudinary_utils

# Cargar solo las funciones puras que quiero testear
# (render_pdf_* y los helpers no necesitan acceso real a Mongo)
from services.certificate_service import (  # type: ignore
    _numero_a_literal_es,
    _format_fecha_dd_mm_yyyy,
    _format_ci_full,
    _format_fecha_larga_es,
    _format_rango_modulo,
    _slug_nombre,
    _format_folio,
    render_pdf_notas,
    render_pdf_no_deudor,
    UAGRM_FACULTAD,
    UAGRM_UNIVERSIDAD,
)


# Mock de Student y Course y Enrollment
class FakeStudent:
    nombre = "SANGUINO RIBERA ERLINDA KAORI"
    registro = "214138348"
    carnet = "10781482"
    extension = "BEN"
    complemento_carnet = None


class FakeModulo:
    def __init__(self, nombre, costo, estado, monto_pagado, nota=None, estado_academico="Cursando", fecha_inicio=None, fecha_fin=None):
        self.nombre = nombre
        self.costo = costo
        self.estado = estado
        self.monto_pagado = monto_pagado
        self.nota = nota
        self.estado_academico = estado_academico
        self.fecha_inicio = fecha_inicio
        self.fecha_fin = fecha_fin


class FakeEnrollment:
    modulos = []
    saldo_pendiente = 0


class FakeCourse:
    nombre_programa = "EDUCACION CONTINUA EN GESTION TRIBUTARIA"
    codigo = "DIPL-2026-001"
    modulos = []


def run_tests():
    print("=" * 70)
    print("TEST FUNCIONAL: certificate_service.py (helpers + render PDF)")
    print("=" * 70)

    # === HELPERS ===
    print("\n[HELPERS]")

    # número a literal
    cases_num = [(0, "Cero"), (1, "Uno"), (15, "Quince"), (29, "Veintinueve"),
                 (30, "Treinta"), (93, "Noventa y tres"), (100, "Cien")]
    for n, expected in cases_num:
        actual = _numero_a_literal_es(n)
        assert actual == expected, f"_numero_a_literal_es({n}) = {actual!r}, esperaba {expected!r}"
        print(f"  ✓ _numero_a_literal_es({n}) = {actual!r}")

    # formato fecha
    dt = datetime(2026, 3, 15)
    assert _format_fecha_dd_mm_yyyy(dt) == "15/03/2026"
    assert _format_fecha_dd_mm_yyyy(None) == "—"
    print(f"  ✓ _format_fecha_dd_mm_yyyy(15/03/2026) = '15/03/2026'")
    print(f"  ✓ _format_fecha_dd_mm_yyyy(None) = '—'")

    # rango módulo
    ini = datetime(2020, 10, 26)
    fin = datetime(2020, 10, 30)
    assert _format_rango_modulo(ini, fin) == "26/10/2020 al 30/10/2020"
    print(f"  ✓ _format_rango_modulo(26-30 oct 2020) = '26/10/2020 al 30/10/2020'")

    # formato CI
    assert _format_ci_full("10781482", "BEN", None) == "10781482 BEN"
    assert _format_ci_full("1234567", "SC", "1D") == "1234567-1D SC"
    assert _format_ci_full(None, None, None) == "—"
    print(f"  ✓ _format_ci_full: 3 casos OK")

    # slug
    assert _slug_nombre("SANGUINO RIBERA ERLINDA KAORI") == "SANGUINO_RIBERA_ERLINDA_KAORI"
    assert _slug_nombre("Sánchez Liceras") == "SANCHEZ_LICERAS"
    print(f"  ✓ _slug_nombre: casos con/sin acentos OK")

    # folio
    assert _format_folio(42, 2026) == "N° 042/2026"
    assert _format_folio(1, 2026) == "N° 001/2026"
    print(f"  ✓ _format_folio(42, 2026) = 'N° 042/2026'")

    # fecha larga
    assert _format_fecha_larga_es(datetime(2026, 1, 20)) == "20 de enero de 2026"
    assert _format_fecha_larga_es(datetime(2026, 7, 29)) == "29 de julio de 2026"
    print(f"  ✓ _format_fecha_larga_es: '20 de enero de 2026' / '29 de julio de 2026'")

    # === RENDER PDF: Notas ===
    print("\n[PDF RENDER: Certificado de Notas]")
    student = FakeStudent()
    course = FakeCourse()
    enrollment = FakeEnrollment()
    enrollment.modulos = [
        FakeModulo("Módulo 1: Fundamentos del Derecho Tributario", 500, "Pagado", 500,
                   nota=93, estado_academico="Aprobado",
                   fecha_inicio=datetime(2020, 10, 26), fecha_fin=datetime(2020, 10, 30)),
        FakeModulo("Módulo 2: Sistema Tributario en Bolivia", 500, "Pagado", 500,
                   nota=96, estado_academico="Aprobado",
                   fecha_inicio=datetime(2020, 11, 3), fecha_fin=datetime(2020, 11, 7)),
        FakeModulo("Módulo 3: Taller I - Análisis de Casos Prácticos", 500, "Pagado", 500,
                   nota=100, estado_academico="Aprobado",
                   fecha_inicio=datetime(2020, 11, 30), fecha_fin=datetime(2020, 12, 4)),
        FakeModulo("Módulo 4: Taller II - Determinación del IUE", 500, "Pagado", 500,
                   nota=95, estado_academico="Aprobado",
                   fecha_inicio=datetime(2020, 12, 7), fecha_fin=datetime(2020, 12, 11)),
    ]

    pdf_bytes = render_pdf_notas(
        student=student,
        course=course,
        enrollment=enrollment,
        folio="N° 042/2026",
        emitido_en=datetime(2026, 1, 20, tzinfo=timezone.utc),
    )
    assert isinstance(pdf_bytes, bytes), f"PDF no es bytes: {type(pdf_bytes)}"
    assert len(pdf_bytes) > 1000, f"PDF muy chico: {len(pdf_bytes)} bytes"
    assert pdf_bytes[:4] == b"%PDF", f"PDF no empieza con magic number"
    print(f"  ✓ render_pdf_notas: {len(pdf_bytes):,} bytes, magic %PDF OK")

    # Guardar a archivo para inspección visual
    out_path = "tests/_pdf_test_notas.pdf"
    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    print(f"  ✓ PDF guardado en: {out_path}")

    # === RENDER PDF: No Deudor (cobertura total) ===
    print("\n[PDF RENDER: Certificado de No Deudor - cobertura total]")
    enrollment2 = FakeEnrollment()
    enrollment2.modulos = [
        FakeModulo("Módulo 1", 500, "Pagado", 500, fecha_inicio=datetime(2020, 10, 26), fecha_fin=datetime(2020, 10, 30)),
        FakeModulo("Módulo 2", 500, "Pagado", 500, fecha_inicio=datetime(2020, 11, 3), fecha_fin=datetime(2020, 11, 7)),
    ]
    pdf_bytes2 = render_pdf_no_deudor(
        student=student,
        course=course,
        enrollment=enrollment2,
        hasta_modulo_n=2,  # == total
        folio="N° 043/2026",
        emitido_en=datetime(2026, 1, 21, tzinfo=timezone.utc),
    )
    assert isinstance(pdf_bytes2, bytes)
    assert len(pdf_bytes2) > 1000
    assert pdf_bytes2[:4] == b"%PDF"
    print(f"  ✓ render_pdf_no_deudor (cobertura total): {len(pdf_bytes2):,} bytes OK")

    out_path2 = "tests/_pdf_test_nodeudor_total.pdf"
    with open(out_path2, "wb") as f:
        f.write(pdf_bytes2)
    print(f"  ✓ PDF guardado en: {out_path2}")

    # === RENDER PDF: No Deudor (alcance parcial) ===
    print("\n[PDF RENDER: Certificado de No Deudor - alcance parcial (Módulo 2 de 3)]")
    enrollment3 = FakeEnrollment()
    enrollment3.modulos = [
        FakeModulo("Módulo 1", 500, "Pagado", 500, fecha_inicio=datetime(2020, 10, 26), fecha_fin=datetime(2020, 10, 30)),
        FakeModulo("Módulo 2", 500, "Pagado", 500, fecha_inicio=datetime(2020, 11, 3), fecha_fin=datetime(2020, 11, 7)),
        FakeModulo("Módulo 3", 500, "Pendiente", 0, fecha_inicio=datetime(2020, 11, 30), fecha_fin=datetime(2020, 12, 4)),
    ]
    pdf_bytes3 = render_pdf_no_deudor(
        student=student,
        course=course,
        enrollment=enrollment3,
        hasta_modulo_n=2,  # < total
        folio="N° 044/2026",
        emitido_en=datetime(2026, 1, 22, tzinfo=timezone.utc),
    )
    assert isinstance(pdf_bytes3, bytes)
    assert len(pdf_bytes3) > 1000
    print(f"  ✓ render_pdf_no_deudor (alcance parcial): {len(pdf_bytes3):,} bytes OK")

    out_path3 = "tests/_pdf_test_nodeudor_parcial.pdf"
    with open(out_path3, "wb") as f:
        f.write(pdf_bytes3)
    print(f"  ✓ PDF guardado en: {out_path3}")

    print("\n" + "=" * 70)
    print("✅ TODOS LOS TESTS PASARON")
    print("=" * 70)
    print(f"\nArchivos generados para inspección visual:")
    print(f"  - {out_path}")
    print(f"  - {out_path2}")
    print(f"  - {out_path3}")


if __name__ == "__main__":
    run_tests()
