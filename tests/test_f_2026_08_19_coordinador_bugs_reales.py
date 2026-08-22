"""
Tres bugs reales que Kevin encontro usando la cuenta de coordinador
financiero recien creada (2026-08-19), en la misma tanda que la vista de
Supervision Academica.

1. GET /courses/supervision-academica devolvia 422 "Id must be of type
   PydanticObjectId". Causa: se registro DESPUES de la ruta dinamica
   GET /courses/{id} en el archivo. FastAPI matchea por orden de
   registro, asi que "supervision-academica" se interpretaba como un
   {id} y fallaba al parsear como PydanticObjectId — el mismo patron de
   bug que ya habia en error_logs para /courses/en-ejecucion,
   /courses/programados, etc. (visto el 2026-08-14).

2. La misma vista tambien usaba `require_staff`, que EXCLUYE a
   COORDINADOR (solo admin/superadmin/mae/cpd/cobranza) — el
   destinatario principal de la vista nunca hubiera podido entrar, aunque
   se arreglara el problema de rutas.

3. Descargar el PDF de un certificado (para el flujo de firma fisica que
   se armo horas antes) daba 403 "No tienes permiso para acceder a este
   certificado" a CUALQUIER coordinador. Causa: la comparacion de rol
   estaba en MAYUSCULA ("COORDINADOR") contra un valor que siempre es
   minuscula (UserRole.COORDINADOR.value == "coordinador"). Nunca
   matcheaba, desde que se escribio el check. Se encontro el mismo typo
   en otros dos lugares de api/certificates.py al auditar el archivo
   completo.
"""

import io
import os

import pytest
from fastapi import HTTPException

from models.enums import UserRole


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestOrdenDeRutasSupervisionAcademica:
    def test_supervision_academica_se_registra_antes_que_id(self):
        """
        FastAPI matchea por orden de registro: una ruta estatica de un
        segmento ("supervision-academica") tiene que declararse ANTES que
        la dinamica GET /{id}, o la dinamica se la come primero.
        """
        src = _fuente("api", "courses.py")
        pos_supervision = src.index('"/supervision-academica"')
        pos_ver_curso = src.index('summary="Ver Curso"')
        assert pos_supervision < pos_ver_curso, (
            "supervision-academica debe registrarse ANTES que GET /{id} "
            "(summary='Ver Curso'), si no FastAPI intenta parsear "
            "'supervision-academica' como PydanticObjectId y da 422"
        )


class TestPermisoSupervisionAcademicaIncluyeCoordinador:
    def test_no_usa_require_staff(self):
        """
        require_staff excluye a ENCARGADO_CURSO y COORDINADOR — el
        destinatario principal de esta vista nunca hubiera podido entrar.
        """
        src = _fuente("api", "courses.py")
        ini = src.index("async def get_supervision_academica")
        fin = src.find("\n@router.", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]
        assert "Depends(require_staff)" not in cuerpo

    def test_el_chequeo_inline_incluye_coordinador_y_mae(self):
        src = _fuente("api", "courses.py")
        ini = src.index("async def get_supervision_academica")
        fin = src.find("\n@router.", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]
        assert "UserRole.COORDINADOR" in cuerpo
        assert "UserRole.MAE" in cuerpo


class TestComparacionDeRolNoEnMayuscula:
    """
    El bug real: UserRole.COORDINADOR.value es 'coordinador' en minuscula.
    Compararlo contra 'COORDINADOR' (mayuscula) nunca matchea.
    """

    def test_el_enum_es_minuscula(self):
        assert UserRole.COORDINADOR.value == "coordinador"

    def test_verificar_acceso_certificado_ya_no_compara_en_mayuscula(self):
        src = _fuente("services", "certificate_service.py")
        ini = src.index("def verificar_acceso_certificado")
        fin = src.find("\ndef ", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]
        # Sin comentarios: el fix explica el bug citando el literal viejo
        # ("COORDINADOR" en mayuscula) para documentarlo.
        codigo = "\n".join(
            l for l in cuerpo.splitlines() if not l.strip().startswith("#")
        )
        assert '"COORDINADOR"' not in codigo
        assert '"coordinador"' in codigo

    def test_no_quedan_sets_de_staff_roles_en_mayuscula_en_certificates_api(self):
        src = _fuente("api", "certificates.py")
        assert '{"SUPERADMIN"' not in src
        assert 'staff_roles = {"superadmin"' in src or "'superadmin'" in src


class TestVerificarAccesoCertificadoFuncionalmente:
    """Reproduce el bug real end-to-end sobre la funcion, sin mockear nada."""

    class _UserFake:
        def __init__(self, rol):
            self.rol = rol
            self.id = "fake-user-id"

    class _CertFake:
        student_id = "otro-estudiante-id"

    def test_coordinador_ya_puede_acceder(self):
        from services.certificate_service import verificar_acceso_certificado

        user = self._UserFake(UserRole.COORDINADOR)
        cert = self._CertFake()
        # No debe lanzar.
        verificar_acceso_certificado(cert, user)

    def test_encargado_curso_ahora_puede_acceder(self):
        """
        F-FIX-ENCARGADO-CERT-403-INCONSISTENTE (2026-08-22, encontrado en
        la auditoria completa): al 2026-08-19, ENCARGADO_CURSO NO estaba
        en STAFF_ROLES y este test documentaba que quedaba bloqueado a
        proposito (el fix de esa sesion era especifico a coordinador).
        El 2026-08-22 se le dio a encargado_curso acceso de LECTURA a
        certificados en listas (F-2026-08-22-EC-CERTIFICADOS-READONLY),
        lo que dejo una inconsistencia: podia ver el certificado en una
        lista pero no descargarlo (403). Se agrego encargado_curso a
        STAFF_ROLES para que sea consistente — este test se actualiza
        para reflejar el comportamiento correcto actual.
        """
        from services.certificate_service import verificar_acceso_certificado

        user = self._UserFake(UserRole.ENCARGADO_CURSO)
        cert = self._CertFake()
        # No debe lanzar.
        verificar_acceso_certificado(cert, user)

    def test_estudiante_ajeno_sigue_sin_poder_acceder(self):
        from services.certificate_service import verificar_acceso_certificado

        class _StudentFake:
            id = "estudiante-que-no-es-el-dueño"

        cert = self._CertFake()
        with pytest.raises(HTTPException):
            verificar_acceso_certificado(cert, _StudentFake())
