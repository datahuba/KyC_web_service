"""
F-REPORTE-BUGS (2026-08-17)
===========================

Kevin: "crear un nuevo modulo en el sidebar para todos los perfiles excepto
docentes y estudiantes, solo perfiles adm, que puedan reportar bugs o
errores con un detalle del error mas una captura o imagen cargada o pdf".

Decisiones que estos tests fijan:

1. RBAC: se usa `require_staff`, que cubre los 7 perfiles administrativos y
   bloquea docentes y estudiantes — exactamente lo pedido.
2. Ver los reportes de TODOS y cambiarles el estado queda para
   admin/superadmin. Si no, cualquiera del staff podria cerrar el reporte
   de otro. El resto ve solo los suyos.
3. Resolver o descartar EXIGE una respuesta: cerrar un reporte sin decir
   por que no le sirve a quien se tomo el trabajo de abrirlo.
4. Modelo propio y no reusar ErrorLog: ese captura excepciones del backend
   automaticamente. Esto lo escribe una persona que vio algo raro, y muchas
   veces el backend ni se entero (un boton que no hace nada, un numero mal
   calculado, un texto confuso).
"""

import io
import os

import pytest

from models.bug_report import BugReport


def _fuente_router():
    ruta = os.path.join(os.path.dirname(__file__), "..", "api", "bug_reports.py")
    return io.open(ruta, encoding="utf-8").read()


class TestModelo:
    def test_campos_minimos(self):
        campos = BugReport.model_fields
        for c in ("titulo", "descripcion", "adjuntos", "severidad", "estado",
                  "reportado_por_id", "reportado_por_nombre", "reportado_por_rol"):
            assert c in campos, f"falta el campo {c}"

    def test_guarda_snapshot_de_quien_reporto(self):
        """
        Nombre y rol se copian al crear. Si el usuario despues se borra o
        cambia de rol, el reporte sigue diciendo quien lo abrio y con que
        rol lo vio — que es lo que importa para reproducirlo.
        """
        campos = BugReport.model_fields
        assert "reportado_por_nombre" in campos
        assert "reportado_por_rol" in campos

    def test_admite_varios_adjuntos(self):
        """
        Una sola captura muchas veces no alcanza (pantalla + consola).

        Se inspecciona la definicion del campo en vez de instanciar: crear un
        Document de Beanie exige que la coleccion este inicializada, y estos
        tests corren sin base.
        """
        campo = BugReport.model_fields["adjuntos"]
        assert "List" in str(campo.annotation) or "list" in str(campo.annotation)
        assert campo.default_factory is list

    def test_defaults_razonables(self):
        """Un reporte nuevo nace abierto y con severidad media."""
        assert BugReport.model_fields["estado"].default == "abierto"
        assert BugReport.model_fields["severidad"].default == "media"
        assert BugReport.model_fields["adjuntos"].default_factory is list

    def test_rechaza_titulo_o_descripcion_muy_cortos(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            BugReport(
                titulo="ab",  # < 5
                descripcion="descripcion suficientemente larga",
                reportado_por_id="6a4ba854d872cd33d4b49bae",
                reportado_por_nombre="T", reportado_por_rol="admin",
            )
        with pytest.raises(ValidationError):
            BugReport(
                titulo="Titulo valido",
                descripcion="corta",  # < 10
                reportado_por_id="6a4ba854d872cd33d4b49bae",
                reportado_por_nombre="T", reportado_por_rol="admin",
            )


class TestPermisos:
    def test_usa_require_staff(self):
        """require_staff ya bloquea docentes y estudiantes."""
        src = _fuente_router()
        assert "require_staff" in src
        assert "get_current_user" not in src, (
            "no usar get_current_user: dejaria entrar a docentes y estudiantes"
        )

    def test_gestionar_es_solo_admin_o_superadmin(self):
        src = _fuente_router()
        assert "def _puede_gestionar" in src
        assert "UserRole.ADMIN" in src and "UserRole.SUPERADMIN" in src

    def test_el_que_no_gestiona_ve_solo_los_suyos(self):
        """Incluso si no pide solo_mios, el listado se le acota."""
        src = _fuente_router()
        assert "if solo_mios or not _puede_gestionar(current_user):" in src

    def test_borrar_es_solo_superadmin(self):
        src = _fuente_router()
        assert "current_user.rol != UserRole.SUPERADMIN" in src


class TestReglasDeCierre:
    def test_resolver_o_descartar_exige_respuesta(self):
        src = _fuente_router()
        assert "ESTADOS_QUE_EXIGEN_RESPUESTA" in src
        assert '"resuelto"' in src and '"descartado"' in src

    def test_hay_tope_de_adjuntos(self):
        """Un reporte con 20 capturas no ayuda y llena Cloudinary."""
        src = _fuente_router()
        assert "MAX_ADJUNTOS" in src


class TestRegistro:
    def test_el_modelo_esta_en_document_models(self):
        """Si falta, Beanie no lo inicializa y todo tira 500 en runtime."""
        ruta = os.path.join(os.path.dirname(__file__), "..", "core", "database.py")
        src = io.open(ruta, encoding="utf-8").read()
        assert "BugReport" in src

    def test_el_router_esta_registrado(self):
        ruta = os.path.join(os.path.dirname(__file__), "..", "api", "api.py")
        src = io.open(ruta, encoding="utf-8").read()
        assert "bug_reports" in src
        assert '"/bug-reports"' in src
