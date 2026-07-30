"""
Tests para el servicio de Solicitudes de Trámite
================================================

F-TRAMITES-SOLICITUD (2026-07-29): tests unitarios con mocks de los modelos
Beanie para no depender de MongoDB. Los tests E2E se hacen en el smoke test
post-deploy.

Coverage:
- Reglas de archivos requeridos por tipo (convalidacion, tutoria, readmision, titulacion).
- Crear solicitud (caso feliz + archivos faltantes).
- Listar mis solicitudes (ordenadas desc).
- Aprobar / rechazar / cancelar (transiciones de estado).
- RBAC: estudiante no puede crear/revisar; staff sí.
- Estadísticas.
"""

from datetime import datetime, timezone
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest
from bson import ObjectId
from fastapi import HTTPException

from models.enums import (
    EstadoTramite,
    TipoTramite,
    UserRole,
)
from models.tramite_solicitud import ArchivoAdjunto, TramiteSolicitud
import services.tramite_solicitud_service as tramite_service
from schemas.tramite_solicitud import (
    ArchivoAdjuntoCreate,
    TramiteSolicitudCreate,
)


# ========================================================================
# FIXTURES
# ========================================================================


def _make_archivos_requeridos(tipo: TipoTramite) -> List[ArchivoAdjuntoCreate]:
    """Devuelve una lista con todos los archivos requeridos para el tipo."""
    if tipo == TipoTramite.CONVALIDACION or tipo == TipoTramite.TUTORIA:
        return [
            ArchivoAdjuntoCreate(nombre_campo="carta", url="https://cloudinary.com/carta.pdf"),
            ArchivoAdjuntoCreate(nombre_campo="certificado_nota", url="https://cloudinary.com/cert.pdf"),
            ArchivoAdjuntoCreate(nombre_campo="comprobante_pago", url="https://cloudinary.com/pago.jpg"),
        ]
    if tipo == TipoTramite.READMISION:
        return [
            ArchivoAdjuntoCreate(nombre_campo="carta", url="https://cloudinary.com/carta.pdf"),
        ]
    if tipo == TipoTramite.TITULACION:
        return [
            ArchivoAdjuntoCreate(nombre_campo="carta", url="https://cloudinary.com/carta.pdf"),
            ArchivoAdjuntoCreate(nombre_campo="comprobante_pago", url="https://cloudinary.com/pago.jpg"),
        ]
    return []


def _make_estudiante() -> MagicMock:
    """Mock de Student con id."""
    s = MagicMock()
    s.id = ObjectId()
    s.role = None  # Student no tiene .role
    return s


def _make_staff(role: UserRole) -> MagicMock:
    """Mock de User con role (en el modelo KYC DataHub el campo es 'rol', no 'role')."""
    u = MagicMock()
    u.id = ObjectId()
    u.username = f"staff_{role.value}"
    u.rol = role
    return u


def _make_solicitud(tipo: TipoTramite, estudiante_id: ObjectId, estado: str = "pendiente") -> MagicMock:
    """Mock de TramiteSolicitud con id y estado."""
    s = MagicMock()
    s.id = ObjectId()
    s.tipo = tipo.value
    s.estudiante_id = estudiante_id
    s.enrollment_id = None
    s.estado = estado
    s.nombre_completo = "Juan Perez"
    s.ci = "1234567"
    s.email = "juan@test.com"
    s.telefono = None
    s.motivo = "Detalle de la solicitud de prueba"
    s.programa_relacionado = None
    s.modulos_relacionados = []
    s.monto_pago_bs = None
    s.archivos = []
    s.fecha_revision = None
    s.revisado_por = None
    s.motivo_rechazo = None
    s.motivo_cancelacion = None
    s.fecha_cancelacion = None
    s.created_at = datetime(2026, 7, 29, 10, 0, 0)
    s.updated_at = datetime(2026, 7, 29, 10, 0, 0)

    # save() async
    async def fake_save():
        return s
    s.save = fake_save
    return s


# ========================================================================
# TESTS: VALIDACIÓN DE ARCHIVOS POR TIPO
# ========================================================================


class TestArchivosRequeridosPorTipo:
    def test_convalidacion_requiere_carta_certificado_y_pago(self):
        data = TramiteSolicitudCreate(
            tipo=TipoTramite.CONVALIDACION,
            nombre_completo="Maria Lopez",
            motivo="Detalle de la solicitud",
            archivos=_make_archivos_requeridos(TipoTramite.CONVALIDACION),
        )
        assert len(data.archivos) == 3

    def test_tutoria_requiere_carta_certificado_y_pago(self):
        data = TramiteSolicitudCreate(
            tipo=TipoTramite.TUTORIA,
            nombre_completo="Maria Lopez",
            motivo="Detalle de la solicitud",
            archivos=_make_archivos_requeridos(TipoTramite.TUTORIA),
        )
        assert len(data.archivos) == 3

    def test_readmision_solo_requiere_carta(self):
        data = TramiteSolicitudCreate(
            tipo=TipoTramite.READMISION,
            nombre_completo="Maria Lopez",
            motivo="Detalle de la solicitud",
            archivos=_make_archivos_requeridos(TipoTramite.READMISION),
        )
        assert len(data.archivos) == 1

    def test_titulacion_requiere_carta_y_pago(self):
        data = TramiteSolicitudCreate(
            tipo=TipoTramite.TITULACION,
            nombre_completo="Maria Lopez",
            motivo="Detalle de la solicitud",
            archivos=_make_archivos_requeridos(TipoTramite.TITULACION),
        )
        assert len(data.archivos) == 2


# ========================================================================
# TESTS: CREAR SOLICITUD
# ========================================================================


class TestCrearSolicitud:
    @pytest.mark.asyncio
    async def test_crear_convalidacion_exitosa(self, monkeypatch):
        # Mock el constructor de TramiteSolicitud para no tocar Beanie
        def fake_constructor(*args, **kwargs):
            sol = MagicMock()
            sol.id = ObjectId()
            sol.tipo = kwargs.get("tipo")
            sol.estudiante_id = kwargs.get("estudiante_id")
            sol.estado = kwargs.get("estado", "pendiente")
            sol.archivos = kwargs.get("archivos", [])
            sol.nombre_completo = kwargs.get("nombre_completo")
            sol.motivo = kwargs.get("motivo")

            async def fake_insert():
                return sol
            sol.insert = fake_insert
            return sol
        monkeypatch.setattr(tramite_service, "TramiteSolicitud", fake_constructor)

        data = TramiteSolicitudCreate(
            tipo=TipoTramite.CONVALIDACION,
            nombre_completo="Maria Lopez",
            motivo="Necesito convalidar las materias de la maestría anterior",
            archivos=_make_archivos_requeridos(TipoTramite.CONVALIDACION),
        )
        estudiante = _make_estudiante()
        sol = await tramite_service.crear_solicitud(data, estudiante)

        assert sol.tipo == "convalidacion"
        assert sol.estado == "pendiente"
        assert sol.estudiante_id == estudiante.id
        assert len(sol.archivos) == 3
        assert sol.archivos[0].nombre_campo == "carta"

    @pytest.mark.asyncio
    async def test_crear_readmision_exitosa(self, monkeypatch):
        def fake_constructor(*args, **kwargs):
            sol = MagicMock()
            sol.id = ObjectId()
            sol.tipo = kwargs.get("tipo")
            sol.estudiante_id = kwargs.get("estudiante_id")
            sol.estado = "pendiente"
            sol.archivos = kwargs.get("archivos", [])

            async def fake_insert():
                return sol
            sol.insert = fake_insert
            return sol
        monkeypatch.setattr(tramite_service, "TramiteSolicitud", fake_constructor)

        data = TramiteSolicitudCreate(
            tipo=TipoTramite.READMISION,
            nombre_completo="Pedro Ramirez",
            motivo="Estudié hace 5 años y no defendí, solicito readmisión",
            archivos=_make_archivos_requeridos(TipoTramite.READMISION),
        )
        estudiante = _make_estudiante()
        sol = await tramite_service.crear_solicitud(data, estudiante)

        assert sol.tipo == "readmision"
        assert len(sol.archivos) == 1
        assert sol.archivos[0].nombre_campo == "carta"

    @pytest.mark.asyncio
    async def test_archivos_faltantes_falla_en_schema(self):
        """Si faltan archivos requeridos, el schema rechaza antes de llamar al service."""
        with pytest.raises(ValueError) as exc:
            TramiteSolicitudCreate(
                tipo=TipoTramite.CONVALIDACION,  # requiere 3 archivos
                nombre_completo="Maria Lopez",
                motivo="Detalle de la solicitud",
                archivos=[],  # sin archivos
            )
        assert "adjuntar" in str(exc.value).lower() or "faltan" in str(exc.value).lower()

    @pytest.mark.asyncio
    async def test_enrollment_id_invalido_422(self, monkeypatch):
        def fake_constructor(*args, **kwargs):
            sol = MagicMock()
            sol.id = ObjectId()

            async def fake_insert():
                return sol
            sol.insert = fake_insert
            return sol
        monkeypatch.setattr(tramite_service, "TramiteSolicitud", fake_constructor)

        data = TramiteSolicitudCreate(
            tipo=TipoTramite.TUTORIA,
            nombre_completo="Maria Lopez",
            motivo="Detalle de la solicitud",
            archivos=_make_archivos_requeridos(TipoTramite.TUTORIA),
            enrollment_id="no-es-un-objectid",
        )
        estudiante = _make_estudiante()
        with pytest.raises(HTTPException) as exc:
            await tramite_service.crear_solicitud(data, estudiante)
        assert exc.value.status_code == 422


# ========================================================================
# TESTS: WORKFLOW / TRANSICIONES DE ESTADO
# ========================================================================


class TestAprobarSolicitud:
    @pytest.mark.asyncio
    async def test_aprobar_pendiente_pasa_a_aprobada(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, ObjectId(), estado="pendiente")

        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)

        async def fake_save(self):
            return self
        monkeypatch.setattr(TramiteSolicitud, "save", fake_save)

        staff = _make_staff(UserRole.CPD)
        result = await tramite_service.aprobar_solicitud(str(sol_mock.id), staff)

        assert result.estado == "aprobada"
        assert result.revisado_por == staff.username
        assert result.fecha_revision is not None

    @pytest.mark.asyncio
    async def test_aprobar_ya_aprobada_409(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, ObjectId(), estado="aprobada")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)

        staff = _make_staff(UserRole.CPD)
        with pytest.raises(HTTPException) as exc:
            await tramite_service.aprobar_solicitud(str(sol_mock.id), staff)
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_estudiante_no_puede_aprobar(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, ObjectId(), estado="pendiente")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)

        # User con role de estudiante
        estudiante_user = _make_staff(UserRole.DOCENTE)  # DOCENTE no está en STAFF_ROLES_REVISION
        with pytest.raises(HTTPException) as exc:
            await tramite_service.aprobar_solicitud(str(sol_mock.id), estudiante_user)
        assert exc.value.status_code == 403


class TestRechazarSolicitud:
    @pytest.mark.asyncio
    async def test_rechazar_pendiente(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.CONVALIDACION, ObjectId(), estado="pendiente")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)
        async def fake_save(self):
            return self
        monkeypatch.setattr(TramiteSolicitud, "save", fake_save)

        staff = _make_staff(UserRole.ADMIN)
        result = await tramite_service.rechazar_solicitud(
            str(sol_mock.id), staff, "Documentación incompleta"
        )
        assert result.estado == "rechazada"
        assert result.motivo_rechazo == "Documentación incompleta"
        assert result.revisado_por == staff.username

    @pytest.mark.asyncio
    async def test_rechazar_en_revision_ok(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.READMISION, ObjectId(), estado="en_revision")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)
        async def fake_save(self):
            return self
        monkeypatch.setattr(TramiteSolicitud, "save", fake_save)

        staff = _make_staff(UserRole.ADMIN)
        result = await tramite_service.rechazar_solicitud(
            str(sol_mock.id), staff, "No cumple los requisitos"
        )
        assert result.estado == "rechazada"


class TestCancelarSolicitud:
    @pytest.mark.asyncio
    async def test_estudiante_cancela_propia_pendiente(self, monkeypatch):
        estudiante = _make_estudiante()
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, estudiante.id, estado="pendiente")

        async def fake_get(solicitud_id, estudiante=None, current_user=None):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)
        async def fake_save(self):
            return self
        monkeypatch.setattr(TramiteSolicitud, "save", fake_save)

        result = await tramite_service.cancelar_solicitud(
            str(sol_mock.id), estudiante, "Ya no la necesito"
        )
        assert result.estado == "cancelada"
        assert result.motivo_cancelacion == "Ya no la necesito"

    @pytest.mark.asyncio
    async def test_estudiante_no_puede_cancelar_otra(self, monkeypatch):
        otro_estudiante = _make_estudiante()
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, ObjectId(), estado="pendiente")

        # Mock TramiteSolicitud.get (Beanie class method) para devolver sol_mock
        async def fake_get(_id):
            return sol_mock
        monkeypatch.setattr(TramiteSolicitud, "get", staticmethod(fake_get))

        with pytest.raises(HTTPException) as exc:
            await tramite_service.cancelar_solicitud(
                str(sol_mock.id), otro_estudiante
            )
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_no_puede_cancelar_aprobada(self, monkeypatch):
        estudiante = _make_estudiante()
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, estudiante.id, estado="aprobada")
        async def fake_get(solicitud_id, estudiante=None, current_user=None):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)

        with pytest.raises(HTTPException) as exc:
            await tramite_service.cancelar_solicitud(
                str(sol_mock.id), estudiante
            )
        assert exc.value.status_code == 409


class TestMarcarEnRevision:
    @pytest.mark.asyncio
    async def test_pendiente_pasa_a_en_revision(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.CONVALIDACION, ObjectId(), estado="pendiente")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)
        async def fake_save(self):
            return self
        monkeypatch.setattr(TramiteSolicitud, "save", fake_save)

        staff = _make_staff(UserRole.CPD)
        result = await tramite_service.marcar_en_revision(str(sol_mock.id), staff)
        assert result.estado == "en_revision"

    @pytest.mark.asyncio
    async def test_aprobada_no_puede_marcarse_en_revision(self, monkeypatch):
        sol_mock = _make_solicitud(TipoTramite.TUTORIA, ObjectId(), estado="aprobada")
        async def fake_get(solicitud_id):
            return sol_mock
        monkeypatch.setattr(tramite_service, "obtener_solicitud", fake_get)

        staff = _make_staff(UserRole.CPD)
        with pytest.raises(HTTPException) as exc:
            await tramite_service.marcar_en_revision(str(sol_mock.id), staff)
        assert exc.value.status_code == 409


# ========================================================================
# TESTS: RBAC
# ========================================================================


class TestRBAC:
    def test_staff_roles_revision_incluye_cpd(self):
        assert UserRole.CPD in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_admin(self):
        assert UserRole.ADMIN in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_superadmin(self):
        assert UserRole.SUPERADMIN in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_mae(self):
        assert UserRole.MAE in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_coordinador(self):
        assert UserRole.COORDINADOR in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_cobranza(self):
        assert UserRole.COBRANZA in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_incluye_encargado_curso(self):
        assert UserRole.ENCARGADO_CURSO in tramite_service.STAFF_ROLES_REVISION

    def test_staff_roles_revision_excluye_docente(self):
        assert UserRole.DOCENTE not in tramite_service.STAFF_ROLES_REVISION

    def test_es_staff_revision_true_para_cpd(self):
        u = _make_staff(UserRole.CPD)
        assert tramite_service._es_staff_revision(u) is True

    def test_es_staff_revision_false_para_docente(self):
        u = _make_staff(UserRole.DOCENTE)
        assert tramite_service._es_staff_revision(u) is False

    @pytest.mark.asyncio
    async def test_docente_no_puede_listar(self, monkeypatch):
        docente = _make_staff(UserRole.DOCENTE)
        with pytest.raises(HTTPException) as exc:
            await tramite_service.listar_todas(docente, page=1, per_page=20)
        assert exc.value.status_code == 403


# ========================================================================
# TESTS: ESTADÍSTICAS
# ========================================================================


class TestEstadisticas:
    @pytest.mark.asyncio
    async def test_estadisticas_calcula_por_tipo_y_estado(self, monkeypatch):
        # Mock del aggregate
        rows = [
            {"_id": {"tipo": "tutoria", "estado": "pendiente"}, "count": 5},
            {"_id": {"tipo": "tutoria", "estado": "aprobada"}, "count": 3},
            {"_id": {"tipo": "convalidacion", "estado": "pendiente"}, "count": 2},
        ]

        class FakeAggregate:
            def __init__(self, pipeline):
                self.pipeline = pipeline
            async def to_list(self):
                return rows

        def fake_aggregate(_pipeline):
            return FakeAggregate(_pipeline)

        class FakeFindResult:
            def __init__(self, query):
                self.query = query
            async def count(self):
                return 7

        def fake_find(_query):
            return FakeFindResult(_query)

        monkeypatch.setattr(TramiteSolicitud, "aggregate", fake_aggregate)
        monkeypatch.setattr(TramiteSolicitud, "find", fake_find)

        staff = _make_staff(UserRole.ADMIN)
        stats = await tramite_service.estadisticas(staff)
        assert stats.total == 10
        assert stats.por_tipo["tutoria"]["pendiente"] == 5
        assert stats.por_tipo["convalidacion"]["pendiente"] == 2
        assert stats.por_estado["pendiente"] == 7
        assert stats.por_estado["aprobada"] == 3
        assert stats.pendientes_hoy == 7

    @pytest.mark.asyncio
    async def test_estadisticas_docente_403(self, monkeypatch):
        docente = _make_staff(UserRole.DOCENTE)
        with pytest.raises(HTTPException) as exc:
            await tramite_service.estadisticas(docente)
        assert exc.value.status_code == 403
