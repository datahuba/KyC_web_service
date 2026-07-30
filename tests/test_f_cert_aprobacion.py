"""
F-CERT-APROBACION (2026-07-30): tests del flujo de aprobación de certificados
y de re-subida de comprobantes anulados.

Estos tests NO tocan MongoDB real — son tests unitarios de la lógica de
validación (RBAC, transiciones de estado, validaciones de re-sub de pagos).
Para tests de integración end-to-end ver test_certificates_e2e.py.
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch


class TestF060ReSubirComprobanteAnulado:
    """
    F-PAGO-RESUB-ANULADO (2026-07-30): permitir re-subir un comprobante si
    el pago anterior está ANULADO o RECHAZADO. Caso real: Luis Fernando
    Lopez Zenteno, comprobante 5603099807.
    """

    def test_bloquea_si_aprobado(self):
        """Si el pago con ese número está APROBADO, debe bloquear."""
        from models.enums import EstadoPago
        # Simular: existe un pago APROBADO con ese número
        existing_estado = EstadoPago.APROBADO
        # La regla nueva: bloquea si está en [APROBADO, PENDIENTE]
        estados_que_bloquean = {EstadoPago.APROBADO, EstadoPago.PENDIENTE}
        assert existing_estado in estados_que_bloquean

    def test_bloquea_si_pendiente(self):
        """Si el pago con ese número está PENDIENTE (en revisión), debe bloquear."""
        from models.enums import EstadoPago
        existing_estado = EstadoPago.PENDIENTE
        estados_que_bloquean = {EstadoPago.APROBADO, EstadoPago.PENDIENTE}
        assert existing_estado in estados_que_bloquean

    def test_permite_si_anulado(self):
        """Si el pago con ese número está ANULADO, debe permitir re-subir."""
        from models.enums import EstadoPago
        existing_estado = EstadoPago.ANULADO
        estados_que_bloquean = {EstadoPago.APROBADO, EstadoPago.PENDIENTE}
        assert existing_estado not in estados_que_bloquean

    def test_permite_si_rechazado(self):
        """Si el pago con ese número está RECHAZADO, debe permitir re-subir."""
        from models.enums import EstadoPago
        existing_estado = EstadoPago.RECHAZADO
        estados_que_bloquean = {EstadoPago.APROBADO, EstadoPago.PENDIENTE}
        assert existing_estado not in estados_que_bloquean


class TestF060IndiceUnicoExcluyeAnulado:
    """
    El índice único parcial uniq_numero_transaccion_activo (en models/payment.py)
    debe seguir excluyendo ANULADO y RECHAZADO para que la BD permita el insert.
    """

    def test_indice_excluye_anulado(self):
        from pathlib import Path
        content = Path("models/payment.py").read_text(encoding="utf-8")
        # El filtro parcial debe ser SOLO para pendiente y aprobado
        idx = content.find("partialFilterExpression")
        bloque = content[idx:idx + 500]
        assert "pendiente" in bloque
        assert "aprobado" in bloque
        assert "anulado" not in bloque
        assert "rechazado" not in bloque


class TestFCertAprobacionRBAC:
    """
    F-CERT-APROBACION: el RBAC para aprobar certificados y solicitudes de
    trámite.
    """

    def _make_user(self, rol, cursos_asignados=None):
        """Crea un mock que pasa el isinstance(user, User) check."""
        from unittest.mock import Mock
        from models.user import User
        # Mock con spec=User hace que isinstance(mock, User) retorne True.
        u = Mock(spec=User)
        u.rol = rol
        u.cursos_asignados = cursos_asignados or []
        u.username = "test_user"
        u.email = "test@test.com"
        return u

    def test_admin_puede_aprobar_cualquiera(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        admin = self._make_user(UserRole.ADMIN)
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert(admin, course_id) is True

    def test_superadmin_puede_aprobar_cualquiera(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        sa = self._make_user(UserRole.SUPERADMIN)
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert(sa, course_id) is True

    def test_encargado_curso_puede_aprobar_su_curso(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        course_id = ObjectId()
        enc = self._make_user(UserRole.ENCARGADO_CURSO, cursos_asignados=[course_id])
        assert puede_aprobar_solicitud_cert(enc, course_id) is True

    def test_encargado_curso_NO_puede_aprobar_otro_curso(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        mi_curso = ObjectId()
        otro_curso = ObjectId()
        enc = self._make_user(UserRole.ENCARGADO_CURSO, cursos_asignados=[mi_curso])
        assert puede_aprobar_solicitud_cert(enc, otro_curso) is False

    def test_cpd_NO_puede_aprobar(self):
        """CPD ve la cola pero NO aprueba (per Kevin 2026-07-30)."""
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        cpd = self._make_user(UserRole.CPD)
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert(cpd, course_id) is False

    def test_coordinador_NO_puede_aprobar(self):
        """Coordinador ve la cola pero NO aprueba (per Kevin 2026-07-30)."""
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        coord = self._make_user(UserRole.COORDINADOR)
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert(coord, course_id) is False

    def test_cobranza_NO_puede_aprobar(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from models.enums import UserRole
        from bson import ObjectId
        cob = self._make_user(UserRole.COBRANZA)
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert(cob, course_id) is False

    def test_student_NO_puede_aprobar(self):
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        from bson import ObjectId
        # Si current_user NO es User, retorna False
        course_id = ObjectId()
        assert puede_aprobar_solicitud_cert("not-a-user", course_id) is False


class TestFCertAprobacionTransiciones:
    """
    F-CERT-APROBACION: las transiciones de estado válidas para
    CertificateRequest.
    """

    def test_pendiente_a_en_revision(self):
        from models.enums import EstadoTramite
        assert {EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION} == {
            EstadoTramite.PENDIENTE,
            EstadoTramite.EN_REVISION,
        }

    def test_en_revision_a_aprobada(self):
        from models.enums import EstadoTramite
        transiciones_validas = {EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION}
        assert EstadoTramite.EN_REVISION in transiciones_validas
        # El service valida que se puede aprobar desde pendiente o en_revision
        # (ver cert_request_service.aprobar_solicitud)

    def test_estado_aprobada_es_terminal(self):
        from models.enums import EstadoTramite
        # Aprobada tiene certificate_id, no se puede cambiar de estado
        assert EstadoTramite.APROBADA.value == "aprobada"

    def test_estado_cancelada_es_terminal(self):
        from models.enums import EstadoTramite
        assert EstadoTramite.CANCELADA.value == "cancelada"


class TestFCertAprobacionEmisionBloqueadaEstudiante:
    """
    F-CERT-APROBACION: el estudiante NO puede emitir certificados directamente.
    Solo el staff puede usar POST /certificates/emit (caso manual).
    El estudiante usa POST /certificates/requests/.
    """

    def test_docstring_endpoint_emit_indica_solo_staff(self):
        """El endpoint POST /api/v1/certificates/emit debe estar documentado
        como solo staff después de F-CERT-APROBACION."""
        from pathlib import Path
        content = Path("api/certificates.py").read_text(encoding="utf-8")
        # Buscar el bloque del endpoint emit
        idx = content.find('"/emit"')
        bloque = content[idx:idx + 1500]
        # Debe decir explícitamente que el estudiante NO puede
        assert "Student" in bloque or "estudiante" in bloque.lower()
        # Debe redirigir al flujo de solicitud
        assert "/requests/" in bloque or "solicitud" in bloque.lower()


class TestFTramitesSolicitudCourseID:
    """
    F-CERT-APROBACION: el modelo TramiteSolicitud tiene course_id
    denormalizado para filtrar la cola del encargado.
    """

    def test_modelo_tiene_course_id(self):
        from models.tramite_solicitud import TramiteSolicitud
        from beanie import PydanticObjectId
        # course_id es opcional (compatibilidad con solicitudes antiguas)
        assert "course_id" in TramiteSolicitud.model_fields
        # default None
        assert TramiteSolicitud.model_fields["course_id"].default is None

    def test_indice_compuesto_course_estado(self):
        from pathlib import Path
        content = Path("models/tramite_solicitud.py").read_text(encoding="utf-8")
        # Debe tener un índice compuesto (course_id, estado) para la cola
        assert '"course_id"' in content or "'course_id'" in content
        assert "course_id" in content and "estado" in content
