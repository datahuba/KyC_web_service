"""
Auditoría completa 2026-08-22 — hallazgos de severidad ALTA, verificados
(los que no requerían una decisión de negocio ambigua).
"""

import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestResolucionExcluyeFinanciero:
    """put_resolucion y upload_resolucion_temp ahora usan
    require_gestion_academica, igual que create_course/update_course."""

    def test_put_resolucion_usa_require_gestion_academica(self):
        src = _fuente("api", "courses.py")
        ini = src.index("async def put_resolucion")
        firma = src[ini: ini + 200]
        assert "Depends(require_gestion_academica)" in firma

    def test_upload_resolucion_temp_usa_require_gestion_academica(self):
        src = _fuente("api", "courses.py")
        ini = src.index("async def upload_resolucion_temp")
        firma = src[ini: ini + 200]
        assert "Depends(require_gestion_academica)" in firma


class TestCertificateServiceEncargadoConsistente:
    def test_encargado_curso_en_staff_roles(self):
        src = _fuente("services", "certificate_service.py")
        ini = src.index("STAFF_ROLES = {")
        fin = src.index("}", ini)
        assert '"encargado_curso"' in src[ini:fin]


class TestComunicadosEscapanHTML:
    """F-FIX-COMUNICADOS-XSS: el texto libre de staff se escapa antes de
    interpolarse en el HTML del correo."""

    def test_build_comunicado_email_escapa_los_campos_libres(self):
        from core.email_utils import build_comunicado_email

        html = build_comunicado_email(
            nombre="Estudiante",
            asunto='<script>alert(1)</script>',
            mensaje='<img src=x onerror=alert(2)>',
            programa="<b>Programa</b>",
            portal_link="https://postgrado.datahuba.com",
        )
        # Lo que importa: '<'/'>' quedan escapados, asi que el navegador
        # nunca interpreta esto como una etiqueta real (aunque el texto
        # "onerror=" siga visible como texto plano inerte).
        assert "<script>" not in html
        assert "<img" not in html
        assert "&lt;script&gt;" in html
        assert "&lt;img" in html

    def test_build_comunicado_email_preserva_saltos_de_linea(self):
        """white-space: pre-line sigue funcionando — escape no toca \\n."""
        from core.email_utils import build_comunicado_email

        html = build_comunicado_email(
            nombre="Estudiante",
            asunto="Aviso",
            mensaje="Línea 1\nLínea 2",
            programa="DIPL-TEST",
            portal_link="https://postgrado.datahuba.com",
        )
        assert "Línea 1\nLínea 2" in html

    def test_build_recordatorio_pago_email_escapa_mensaje(self):
        from core.email_utils import build_recordatorio_pago_email

        html = build_recordatorio_pago_email(
            nombre="Estudiante",
            mensaje='<script>alert(1)</script>',
            portal_link="https://postgrado.datahuba.com",
        )
        assert "<script>" not in html
        assert "&lt;script&gt;" in html
