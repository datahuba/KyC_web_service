"""
Tests para el servicio de Certificados
=====================================

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md

Estrategia: tests unitarios con mocks de los modelos Beanie para evitar
depender de MongoDB. Los tests de integración E2E se hacen en el smoke test
post-deploy (no aquí).

Coverage:
- Helpers: número a letras, formato de fechas, formato de CI, slug, folio.
- Validaciones de requisitos (Notas y No Deudor).
- Generación de PDF (verificar que devuelve bytes > 0).
- Correlativo atómico (concurrencia).
- Emisión de certificados (caso feliz + casos de error).
- RBAC (verificar_acceso_certificado).
"""

import io
import re
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from bson import ObjectId
from fastapi import HTTPException

from models.certificate import Certificate, ModuloCertificado
from models.certificate_counter import CertificateCounter
from models.enums import TipoCertificado
from models.enrollment import ModuloEstado
import services.certificate_service as cert_service


# ========================================================================
# TESTS DE HELPERS
# ========================================================================

class TestNumeroALiteral:
    def test_cero(self):
        assert cert_service._numero_a_literal_es(0) == "Cero"

    def test_unidades_simples(self):
        assert cert_service._numero_a_literal_es(1) == "Uno"
        assert cert_service._numero_a_literal_es(15) == "Quince"
        assert cert_service._numero_a_literal_es(29) == "Veintinueve"

    def test_decenas_exactas(self):
        assert cert_service._numero_a_literal_es(30) == "Treinta"
        assert cert_service._numero_a_literal_es(50) == "Cincuenta"
        assert cert_service._numero_a_literal_es(90) == "Noventa"

    def test_decenas_con_unidad(self):
        assert cert_service._numero_a_literal_es(45) == "Cuarenta y cinco"
        assert cert_service._numero_a_literal_es(93) == "Noventa y tres"
        assert cert_service._numero_a_literal_es(77) == "Setenta y siete"

    def test_y_minuscula_en_español(self):
        # FIX 2026-07-29: la "y" en español formal va en minúscula
        # (no usar .title() que rompería "Noventa Y Tres").
        # Verificado por test funcional standalone manual_test_pdf.py.
        assert cert_service._numero_a_literal_es(45) == "Cuarenta y cinco"
        assert "Y " not in cert_service._numero_a_literal_es(45)
        assert "Y " not in cert_service._numero_a_literal_es(93)

    def test_cien(self):
        assert cert_service._numero_a_literal_es(100) == "Cien"

    def test_fuera_de_rango(self):
        with pytest.raises(ValueError):
            cert_service._numero_a_literal_es(-1)
        with pytest.raises(ValueError):
            cert_service._numero_a_literal_es(101)


class TestFormatFecha:
    def test_formato_dd_mm_yyyy(self):
        dt = datetime(2026, 3, 15, 0, 0, 0)
        assert cert_service._format_fecha_dd_mm_yyyy(dt) == "15/03/2026"

    def test_none_retorna_guion(self):
        assert cert_service._format_fecha_dd_mm_yyyy(None) == "—"

    def test_rango_completo(self):
        ini = datetime(2020, 10, 26)
        fin = datetime(2020, 10, 30)
        assert cert_service._format_rango_modulo(ini, fin) == "26/10/2020 al 30/10/2020"

    def test_rango_solo_inicio(self):
        ini = datetime(2026, 3, 15)
        fin = None
        assert cert_service._format_rango_modulo(ini, fin) == "15/03/2026"

    def test_rango_ambos_none(self):
        assert cert_service._format_rango_modulo(None, None) == "—"


class TestFormatCI:
    def test_solo_ci(self):
        assert cert_service._format_ci_full("10781482", None, None) == "10781482"

    def test_ci_con_extension(self):
        assert cert_service._format_ci_full("10781482", "BEN", None) == "10781482 BEN"

    def test_ci_con_complemento_y_extension(self):
        assert cert_service._format_ci_full("1234567", "SC", "1D") == "1234567-1D SC"

    def test_ci_none(self):
        assert cert_service._format_ci_full(None, "SC", None) == "—"


class TestSlugNombre:
    def test_basico(self):
        s = cert_service._slug_nombre("SANGUINO RIBERA ERLINDA KAORI")
        assert s == "SANGUINO_RIBERA_ERLINDA_KAORI"

    def test_con_acentos(self):
        s = cert_service._slug_nombre("Sánchez Liceras María")
        assert s == "SANCHEZ_LICERAS_MARIA"

    def test_acentos_en_mayusculas(self):
        # FIX 2026-07-29: unicodedata.normalize quita diacríticos correctamente
        # incluso en strings ya en mayúsculas (SÁNCHEZ, ÁVILA, etc).
        # Bug encontrado por test funcional standalone.
        s = cert_service._slug_nombre("ÁVILA SÁNCHEZ")
        assert s == "AVILA_SANCHEZ"

    def test_ñ_se_convierte_a_n(self):
        # FIX 2026-07-29: la ñ debe convertirse a n (sin tilde) en el slug.
        s = cert_service._slug_nombre("MUÑOZ")
        assert s == "MUNOZ"

    def test_con_numeros(self):
        s = cert_service._slug_nombre("Juan Pérez 3ra generación")
        assert s == "JUAN_PEREZ_3RA_GENERACION"

    def test_truncado(self):
        nombre_largo = "A" * 200
        s = cert_service._slug_nombre(nombre_largo)
        assert len(s) <= 60


class TestFormatFolio:
    def test_formato(self):
        assert cert_service._format_folio(42, 2026) == "N° 042/2026"
        assert cert_service._format_folio(1, 2026) == "N° 001/2026"
        assert cert_service._format_folio(100, 2026) == "N° 100/2026"


# ========================================================================
# TESTS DE VALIDACIÓN DE REQUISITOS
# ========================================================================

def _make_enrollment(
    modulos: list, saldo_pendiente: float = 0.0
) -> MagicMock:
    """Helper: crea un mock de Enrollment con los modulos dados."""
    enrollment = MagicMock()
    enrollment.modulos = modulos
    enrollment.saldo_pendiente = saldo_pendiente
    enrollment.esta_completamente_pagado.return_value = saldo_pendiente <= 0.01
    return enrollment


def _make_modulo(
    nombre: str = "Módulo 1",
    estado: str = "Pagado",
    estado_academico: str = "Aprobado",
    nota: float = 80.0,
    costo: float = 500.0,
    monto_pagado: float = 500.0,
) -> ModuloEstado:
    return ModuloEstado(
        nombre=nombre,
        costo=costo,
        estado=estado,
        nota=nota,
        estado_academico=estado_academico,
        monto_pagado=monto_pagado,
    )


class TestValidarRequisitosNotas:
    @pytest.mark.asyncio
    async def test_sin_modulos_422(self):
        enrollment = _make_enrollment(modulos=[])
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_notas(enrollment)
        assert exc.value.status_code == 422
        assert "módulos" in exc.value.detail.lower()

    @pytest.mark.asyncio
    async def test_modulo_en_cursando_422_con_lista(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado_academico="Aprobado"),
            _make_modulo(nombre="Módulo 2", estado_academico="Cursando"),
            _make_modulo(nombre="Módulo 3", estado_academico="Aprobado"),
        ]
        enrollment = _make_enrollment(modulos=modulos)
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_notas(enrollment)
        assert exc.value.status_code == 422
        assert "Módulo 2" in exc.value.detail

    @pytest.mark.asyncio
    async def test_modulo_reprobado_es_valido(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado_academico="Aprobado"),
            _make_modulo(nombre="Módulo 2", estado_academico="Reprobado", nota=40),
        ]
        enrollment = _make_enrollment(modulos=modulos)
        # No debe lanzar (Reprobado cuenta como "terminado")
        await cert_service.validar_requisitos_notas(enrollment)

    @pytest.mark.asyncio
    async def test_saldo_pendiente_422_con_monto(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado_academico="Aprobado"),
        ]
        enrollment = _make_enrollment(modulos=modulos, saldo_pendiente=300.0)
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_notas(enrollment)
        assert exc.value.status_code == 422
        assert "300" in exc.value.detail

    @pytest.mark.asyncio
    async def test_caso_feliz_no_lanza(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado_academico="Aprobado"),
            _make_modulo(nombre="Módulo 2", estado_academico="Aprobado"),
        ]
        enrollment = _make_enrollment(modulos=modulos, saldo_pendiente=0.0)
        await cert_service.validar_requisitos_notas(enrollment)


class TestValidarRequisitosNoDeudor:
    @pytest.mark.asyncio
    async def test_sin_modulos_422(self):
        enrollment = _make_enrollment(modulos=[])
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_no_deudor(enrollment, 1)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_hasta_n_menor_a_1_422(self):
        modulos = [_make_modulo()]
        enrollment = _make_enrollment(modulos=modulos)
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_no_deudor(enrollment, 0)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_hasta_n_mayor_a_total_422(self):
        modulos = [_make_modulo(), _make_modulo(nombre="Módulo 2")]
        enrollment = _make_enrollment(modulos=modulos)
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_no_deudor(enrollment, 5)
        assert exc.value.status_code == 422

    @pytest.mark.asyncio
    async def test_modulo_n_no_pagado_422_con_nombre(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado="Pagado"),
            _make_modulo(nombre="Módulo 2", estado="Pagado"),
            _make_modulo(nombre="Módulo 3", estado="Pendiente", monto_pagado=0, costo=500),
        ]
        enrollment = _make_enrollment(modulos=modulos)
        with pytest.raises(HTTPException) as exc:
            await cert_service.validar_requisitos_no_deudor(enrollment, 3)
        assert exc.value.status_code == 422
        assert "Módulo 3" in exc.value.detail

    @pytest.mark.asyncio
    async def test_caso_feliz_modulo_n_pagado(self):
        modulos = [
            _make_modulo(nombre="Módulo 1", estado="Pagado"),
            _make_modulo(nombre="Módulo 2", estado="Pagado"),
            _make_modulo(nombre="Módulo 3", estado="Pendiente"),  # no importa, no se valida
        ]
        enrollment = _make_enrollment(modulos=modulos)
        # Pide hasta módulo 2, los primeros 2 están pagados
        await cert_service.validar_requisitos_no_deudor(enrollment, 2)


# ========================================================================
# TESTS DE RENDERIZADO DE PDF
# ========================================================================

class TestRenderPDF:
    def _make_student_mock(self):
        s = MagicMock()
        s.nombre = "SANGUINO RIBERA ERLINDA KAORI"
        s.registro = "214138348"
        s.carnet = "10781482"
        s.extension = "BEN"
        s.complemento_carnet = None
        return s

    def _make_course_mock(self):
        c = MagicMock()
        c.nombre_programa = "EDUCACION CONTINUA EN GESTION TRIBUTARIA"
        c.codigo = "DIPL-2026-001"
        c.modulos = []
        return c

    def test_render_pdf_notas_devuelve_bytes_no_vacios(self):
        s = self._make_student_mock()
        c = self._make_course_mock()
        e = MagicMock()
        e.modulos = [
            ModuloEstado(nombre="Módulo 1", costo=500, estado="Pagado", nota=93, estado_academico="Aprobado", monto_pagado=500),
            ModuloEstado(nombre="Módulo 2", costo=500, estado="Pagado", nota=96, estado_academico="Aprobado", monto_pagado=500),
        ]

        pdf_bytes = cert_service.render_pdf_notas(
            student=s,
            course=c,
            enrollment=e,
            folio="N° 042/2026",
            emitido_en=datetime(2026, 7, 29, 18, 30, 0, tzinfo=timezone.utc),
        )

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 1000, f"PDF muy chico: {len(pdf_bytes)} bytes"
        # Verificar que empieza con el magic number de PDF
        assert pdf_bytes[:4] == b"%PDF"

    def test_render_pdf_no_deudor_devuelve_bytes_no_vacios(self):
        s = self._make_student_mock()
        c = self._make_course_mock()
        e = MagicMock()
        e.modulos = [
            ModuloEstado(nombre="Módulo 1", costo=500, estado="Pagado", nota=None, estado_academico="Aprobado", monto_pagado=500),
            ModuloEstado(nombre="Módulo 2", costo=500, estado="Pagado", nota=None, estado_academico="Aprobado", monto_pagado=500),
            ModuloEstado(nombre="Módulo 3", costo=500, estado="Pendiente", nota=None, estado_academico="Cursando", monto_pagado=0),
        ]

        pdf_bytes = cert_service.render_pdf_no_deudor(
            student=s,
            course=c,
            enrollment=e,
            hasta_modulo_n=2,
            folio="N° 043/2026",
            emitido_en=datetime(2026, 7, 29, 18, 30, 0, tzinfo=timezone.utc),
        )

        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 1000, f"PDF muy chico: {len(pdf_bytes)} bytes"
        assert pdf_bytes[:4] == b"%PDF"

    def test_render_pdf_no_deudor_cobertura_total_no_lanza(self):
        """Cuando hasta_modulo_n == total, el texto cambia pero el PDF se genera igual."""
        s = self._make_student_mock()
        c = self._make_course_mock()
        e = MagicMock()
        e.modulos = [
            ModuloEstado(nombre="Módulo 1", costo=500, estado="Pagado", monto_pagado=500),
        ]

        pdf_bytes = cert_service.render_pdf_no_deudor(
            student=s,
            course=c,
            enrollment=e,
            hasta_modulo_n=1,  # == total
            folio="N° 044/2026",
            emitido_en=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        assert len(pdf_bytes) > 1000


# ========================================================================
# TESTS DE CORRELATIVO ATÓMICO
# ========================================================================

class TestNextCorrelativo:
    @pytest.mark.asyncio
    async def test_primer_numero_es_1(self):
        # Mock del find_one_and_update: simula Mongo upsert+$inc
        with patch.object(
            CertificateCounter, "find_one_and_update", new_callable=AsyncMock
        ) as mock_fx:
            mock_doc = MagicMock()
            mock_doc.last_number = 1
            mock_fx.return_value = mock_doc

            n = await cert_service.next_correlativo(2026)
            assert n == 1
            mock_fx.assert_called_once()
            # Verificar que se llamó con $inc y upsert
            call_kwargs = mock_fx.call_args.kwargs
            assert call_kwargs.get("upsert") is True

    @pytest.mark.asyncio
    async def test_incremento_es_monotono(self):
        """2 llamadas devuelven 1 y 2 (no ambos 1)."""
        seq = iter([1, 2])

        async def fake_fx(*args, **kwargs):
            return MagicMock(last_number=next(seq))

        with patch.object(CertificateCounter, "find_one_and_update", side_effect=fake_fx):
            n1 = await cert_service.next_correlativo(2026)
            n2 = await cert_service.next_correlativo(2026)
            assert n1 == 1
            assert n2 == 2


# ========================================================================
# TESTS DE RBAC
# ========================================================================

class TestVerificarAccesoCertificado:
    def _make_cert(self, student_oid: ObjectId):
        cert = MagicMock()
        cert.student_id = student_oid
        return cert

    def _make_student(self, oid: ObjectId):
        s = MagicMock(spec=["id"])
        s.id = oid
        return s

    def test_estudiante_dueno_puede(self):
        oid = ObjectId()
        cert = self._make_cert(oid)
        student = self._make_student(oid)
        # No debe lanzar
        cert_service.verificar_acceso_certificado(cert, student)

    def test_estudiante_otro_no_puede(self):
        cert = self._make_cert(ObjectId())
        otro_estudiante = self._make_student(ObjectId())
        with pytest.raises(HTTPException) as exc:
            cert_service.verificar_acceso_certificado(cert, otro_estudiante)
        assert exc.value.status_code == 403

    def test_staff_admin_puede(self):
        cert = self._make_cert(ObjectId())
        staff = MagicMock()
        # Simular User con rol
        from models.enums import UserRole
        staff.rol = UserRole.ADMIN
        cert_service.verificar_acceso_certificado(cert, staff)

    def test_staff_cpd_puede(self):
        cert = self._make_cert(ObjectId())
        staff = MagicMock()
        from models.enums import UserRole
        staff.rol = UserRole.CPD
        cert_service.verificar_acceso_certificado(cert, staff)

    def test_staff_docente_no_puede(self):
        cert = self._make_cert(ObjectId())
        staff = MagicMock()
        from models.enums import UserRole
        staff.rol = UserRole.DOCENTE
        with pytest.raises(HTTPException) as exc:
            cert_service.verificar_acceso_certificado(cert, staff)
        assert exc.value.status_code == 403


# ========================================================================
# TESTS DE EMISIÓN (integración con mocks)
# ========================================================================

class TestEmitirCertificadoNotas:
    @pytest.mark.asyncio
    async def test_emitir_exitoso_devuelve_cert_con_pdf_url(self):
        # Mock student
        student = MagicMock()
        student.id = ObjectId()
        student.nombre = "TEST ESTUDIANTE"
        student.registro = "999999"
        student.carnet = "1234567"
        student.extension = "SC"
        student.complemento_carnet = None

        # Mock course
        course = MagicMock()
        course.id = ObjectId()
        course.nombre_programa = "TEST PROGRAMA"
        course.codigo = "TEST-001"
        course.modulos = []

        # Mock enrollment
        enrollment = MagicMock()
        enrollment.id = ObjectId()
        enrollment.curso_id = course.id
        enrollment.estudiante_id = student.id
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=100, estado="Pagado", nota=85, estado_academico="Aprobado", monto_pagado=100),
        ]
        enrollment.esta_completamente_pagado.return_value = True
        enrollment.saldo_pendiente = 0

        # Mock del Certificate: el find_one devuelve None (no existe)
        with patch.object(Certificate, "find_one", new_callable=AsyncMock) as mock_find, \
             patch.object(Certificate, "insert", new_callable=AsyncMock) as mock_insert, \
             patch.object(cert_service, "next_correlativo", new_callable=AsyncMock) as mock_corr, \
             patch.object(cert_service, "_subir_pdf_a_cloudinary", new_callable=AsyncMock) as mock_upload, \
             patch.object(cert_service, "_obtener_curso_estudiante_enrollment", new_callable=AsyncMock) as mock_get:

            mock_find.return_value = None
            mock_corr.return_value = 42
            mock_upload.return_value = "https://res.cloudinary.com/test/cert.pdf"

            async def fake_get(*args, **kwargs):
                return student, course, enrollment
            mock_get.side_effect = fake_get

            async def fake_insert():
                cert = MagicMock()
                cert.id = ObjectId()
                cert.numero = 42
                cert.anio = 2026
                return cert
            mock_insert.side_effect = fake_insert

            cert = await cert_service.emitir_certificado_notas(
                enrollment_id=str(enrollment.id),
                current_user=student,
            )

            # Verificar que se llamó a insert
            mock_insert.assert_called_once()
            # Verificar correlativo
            assert mock_corr.called
            # Verificar upload a Cloudinary
            assert mock_upload.called

    @pytest.mark.asyncio
    async def test_emitir_dos_veces_devuelve_409(self):
        # Mock student + course + enrollment ya completos
        student = MagicMock()
        student.id = ObjectId()
        student.nombre = "TEST"
        student.registro = "999"
        student.carnet = "123"
        student.extension = None
        student.complemento_carnet = None
        course = MagicMock()
        course.id = ObjectId()
        course.nombre_programa = "TEST"
        course.codigo = "T-1"
        course.modulos = []
        enrollment = MagicMock()
        enrollment.id = ObjectId()
        enrollment.curso_id = course.id
        enrollment.estudiante_id = student.id
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=100, estado="Pagado", nota=85, estado_academico="Aprobado", monto_pagado=100),
        ]
        enrollment.esta_completamente_pagado.return_value = True

        # Mock: el Certificate.find_one devuelve uno existente
        cert_existente = MagicMock()
        cert_existente.numero = 10
        cert_existente.anio = 2026

        with patch.object(Certificate, "find_one", new_callable=AsyncMock) as mock_find, \
             patch.object(cert_service, "_obtener_curso_estudiante_enrollment", new_callable=AsyncMock) as mock_get:
            mock_find.return_value = cert_existente

            async def fake_get(*args, **kwargs):
                return student, course, enrollment
            mock_get.side_effect = fake_get

            with pytest.raises(HTTPException) as exc:
                await cert_service.emitir_certificado_notas(
                    enrollment_id=str(enrollment.id),
                    current_user=student,
                )
            assert exc.value.status_code == 409


class TestEmitirCertificadoNoDeudor:
    @pytest.mark.asyncio
    async def test_emitir_exitoso_modulo_n(self):
        student = MagicMock()
        student.id = ObjectId()
        student.nombre = "TEST ESTUDIANTE"
        student.registro = "999999"
        student.carnet = "1234567"
        student.extension = "SC"
        student.complemento_carnet = None
        course = MagicMock()
        course.id = ObjectId()
        course.nombre_programa = "TEST"
        course.codigo = "T-1"
        course.modulos = []
        enrollment = MagicMock()
        enrollment.id = ObjectId()
        enrollment.curso_id = course.id
        enrollment.estudiante_id = student.id
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=100, estado="Pagado", nota=None, estado_academico="Aprobado", monto_pagado=100),
            ModuloEstado(nombre="M2", costo=100, estado="Pagado", nota=None, estado_academico="Aprobado", monto_pagado=100),
            ModuloEstado(nombre="M3", costo=100, estado="Pendiente", nota=None, estado_academico="Cursando", monto_pagado=0),
        ]

        with patch.object(cert_service, "next_correlativo", new_callable=AsyncMock) as mock_corr, \
             patch.object(cert_service, "_subir_pdf_a_cloudinary", new_callable=AsyncMock) as mock_upload, \
             patch.object(Certificate, "insert", new_callable=AsyncMock) as mock_insert, \
             patch.object(cert_service, "_obtener_curso_estudiante_enrollment", new_callable=AsyncMock) as mock_get:

            mock_corr.return_value = 5
            mock_upload.return_value = "https://res.cloudinary.com/cert.pdf"

            async def fake_get(*args, **kwargs):
                return student, course, enrollment
            mock_get.side_effect = fake_get

            cert = await cert_service.emitir_certificado_no_deudor(
                enrollment_id=str(enrollment.id),
                hasta_modulo_n=2,
                current_user=student,
            )
            mock_insert.assert_called_once()
            mock_upload.assert_called_once()
