"""
F-CERT-NO-DEUDOR-COBRO (2026-08-17)
===================================

El Certificado de No Deudor pasa a tener arancel, aprobacion restringida y
un segundo paso de firma fisica antes de que el estudiante pueda descargarlo.

Decisiones que estos tests fijan (transcripcion de la charla + confirmaciones
de Kevin del 2026-08-17):

1. Arancel de Bs 150, configurable por entorno. Se guarda como SNAPSHOT en la
   solicitud: si manana la tarifa cambia, la solicitud vieja conserva el monto
   que se le informo al estudiante.
2. El No Deudor lo aprueban SOLO el coordinador financiero y el superadmin.
   Es mas restrictivo que el certificado de Notas a proposito: este acredita
   que no hay deuda Y cobra, o sea que es una decision economica.
3. Aprobar NO habilita la descarga. Kevin: "el coordinador hace firmar la
   copia fisica y debe habilitar o aprobar al estudiante para que lo tenga".
   Sin el bloqueo de descarga el segundo paso seria decorativo, porque el PDF
   ya existe desde que se aprobo.
4. Tratamiento profesional (Lic./Ing./...) antes del nombre, elegido por quien
   aprueba y no por el estudiante: es el que conoce el titulo real y el que
   firma. Los de diplomado continuo no llevan, por eso None es valido.
5. El PDF final va sobre la hoja membretada. Los membretes que paso Kevin son
   PDF SOLO GRAFICOS (0 texto extraible), asi que el texto se superpone.
"""

import io
import os
from datetime import datetime, timezone

import pytest

import services.certificate_service as cs


# ==========================================================================
# Stubs: los modelos Beanie necesitan BD inicializada, y estos tests corren
# sin base. Se usan objetos con los mismos atributos que consume el render.
# ==========================================================================

class _Obj:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _student(nombre="Kevin Andres Soto Villarroel"):
    return _Obj(nombre=nombre, carnet="7654321", extension="SC", complemento_carnet=None)


def _course():
    return _Obj(nombre_programa="Inteligencia Artificial Aplicada", codigo="DIPL-IA-2026")


def _enrollment(n_modulos=5):
    mods = [
        _Obj(
            nombre=f"Modulo {i}",
            estado="Pagado",
            fecha_inicio=datetime(2026, 3, 1, tzinfo=timezone.utc),
            fecha_fin=datetime(2026, 3, 28, tzinfo=timezone.utc),
        )
        for i in range(1, n_modulos + 1)
    ]
    return _Obj(modulos=mods)


def _fuente(nombre_archivo):
    ruta = os.path.join(os.path.dirname(__file__), "..", nombre_archivo)
    return io.open(ruta, encoding="utf-8").read()


# ==========================================================================
# 1. Arancel
# ==========================================================================

class TestArancel:
    def test_monto_default_es_150(self):
        from core.config import settings
        assert settings.MONTO_CERTIFICADO_NO_DEUDOR == 150.0

    def test_el_monto_se_guarda_como_snapshot_en_la_solicitud(self):
        """
        Si la tarifa cambia, la solicitud vieja tiene que conservar la suya.
        Por eso `monto` es un campo del documento y no se lee de config al
        momento de cobrar.
        """
        from models.certificate_request import CertificateRequest
        assert "monto" in CertificateRequest.model_fields

    def test_solo_las_solicitudes_de_no_deudor_llevan_monto(self):
        src = _fuente("services/certificate_request_service.py")
        assert "if data.tipo == TipoCertificado.NO_DEUDOR else None" in src

    def test_hay_campo_para_el_comprobante_de_pago(self):
        from models.certificate_request import CertificateRequest
        assert "comprobante_url" in CertificateRequest.model_fields

    def test_el_arancel_se_puede_consultar_antes_de_solicitar(self):
        """
        F-CERT-UX-ESTUDIANTE (2026-08-17): el estudiante tiene que ver cuanto
        cuesta ANTES de crear la solicitud. Antes el monto solo existia dentro
        de una solicitud ya creada, asi que la pantalla no tenia de donde
        sacarlo y se enteraba del cobro despues de haber pedido.
        """
        src = _fuente("api/certificates.py")
        assert '"/arancel-no-deudor"' in src
        assert "settings.MONTO_CERTIFICADO_NO_DEUDOR" in src

    def test_el_arancel_se_declara_antes_de_la_ruta_de_id(self):
        """
        `/arancel-no-deudor` y `/{cert_id}` son ambas de UN segmento. Si la
        generica se declarara primero, FastAPI matchearia "arancel-no-deudor"
        como si fuera un id de certificado y el endpoint devolveria 400.
        """
        src = _fuente("api/certificates.py")
        assert src.index('"/arancel-no-deudor"') < src.index('"/{cert_id}"')


# ==========================================================================
# 2. Quien aprueba
# ==========================================================================

class TestQuienAprueba:
    def _user(self, rol, subtipo=None, cursos=None):
        from models.enums import UserRole
        from models.user import User
        u = User.model_construct(
            rol=rol,
            subtipo_coordinador=subtipo,
            cursos_asignados=cursos or [],
            username="tester",
        )
        return u

    def test_superadmin_aprueba_no_deudor(self):
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.SUPERADMIN)
        assert puede_aprobar_solicitud_cert(u, "curso1", "no_deudor") is True

    def test_coordinador_financiero_aprueba_no_deudor(self):
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.COORDINADOR, subtipo="financiero")
        assert puede_aprobar_solicitud_cert(u, "curso1", "no_deudor") is True

    def test_coordinador_academico_NO_aprueba_no_deudor(self):
        """El subtipo importa: solo el financiero decide sobre plata."""
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.COORDINADOR, subtipo="academico")
        assert puede_aprobar_solicitud_cert(u, "curso1", "no_deudor") is False

    def test_encargado_de_curso_NO_aprueba_no_deudor(self):
        """
        Sigue aprobando certificados de NOTAS de sus cursos, pero el de No
        Deudor no: Kevin fue explicito con quienes lo aprueban.
        """
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.ENCARGADO_CURSO, cursos=["curso1"])
        assert puede_aprobar_solicitud_cert(u, "curso1", "no_deudor") is False
        assert puede_aprobar_solicitud_cert(u, "curso1", "notas") is True

    def test_admin_NO_aprueba_no_deudor_pero_si_notas(self):
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.ADMIN)
        assert puede_aprobar_solicitud_cert(u, "curso1", "no_deudor") is False
        assert puede_aprobar_solicitud_cert(u, "curso1", "notas") is True

    def test_sin_tipo_se_comporta_como_antes(self):
        """
        Los llamadores viejos pasan 2 argumentos. No pueden romperse por
        agregar el tercero.
        """
        from models.enums import UserRole
        from services.certificate_request_service import puede_aprobar_solicitud_cert
        u = self._user(UserRole.ADMIN)
        assert puede_aprobar_solicitud_cert(u, "curso1") is True


# ==========================================================================
# 3. Firma fisica: aprobar no alcanza
# ==========================================================================

class TestFirmaFisica:
    def test_el_modelo_registra_quien_y_cuando_confirmo(self):
        from models.certificate_request import CertificateRequest
        campos = CertificateRequest.model_fields
        for c in ("firma_fisica_confirmada", "fecha_firma_fisica", "confirmada_por"):
            assert c in campos, f"falta {c}"
        assert campos["firma_fisica_confirmada"].default is False

    def test_no_deudor_aprobado_sin_firma_NO_es_descargable(self):
        from models.certificate_request import CertificateRequest
        from services.certificate_request_service import es_descargable
        req = CertificateRequest.model_construct(
            tipo="no_deudor", estado="aprobada", certificate_id="c1",
            firma_fisica_confirmada=False,
        )
        assert es_descargable(req) is False

    def test_no_deudor_aprobado_con_firma_SI_es_descargable(self):
        from models.certificate_request import CertificateRequest
        from services.certificate_request_service import es_descargable
        req = CertificateRequest.model_construct(
            tipo="no_deudor", estado="aprobada", certificate_id="c1",
            firma_fisica_confirmada=True,
        )
        assert es_descargable(req) is True

    def test_notas_no_necesita_firma_fisica(self):
        """El flujo de Notas no cambia: aprobado es descargable."""
        from models.certificate_request import CertificateRequest
        from services.certificate_request_service import es_descargable
        req = CertificateRequest.model_construct(
            tipo="notas", estado="aprobada", certificate_id="c1",
            firma_fisica_confirmada=False,
        )
        assert es_descargable(req) is True

    def test_la_descarga_esta_bloqueada_de_verdad_en_el_endpoint(self):
        """
        Sin este chequeo el segundo paso seria decorativo: el PDF ya existe
        desde que se aprobo, asi que el estudiante podria bajarselo igual.
        """
        src = _fuente("api/certificates.py")
        assert "motivo_bloqueo_descarga" in src
        assert "isinstance(current_user, Student)" in src

    def test_el_staff_no_queda_bloqueado(self):
        """Alguien tiene que poder imprimirlo para hacerlo firmar."""
        src = _fuente("services/certificate_request_service.py")
        assert "async def motivo_bloqueo_descarga" in src
        assert "if cert.tipo != TipoCertificado.NO_DEUDOR:" in src


# ==========================================================================
# 4. Tratamiento profesional
# ==========================================================================

class TestTratamiento:
    def test_antepone_el_tratamiento_al_nombre(self):
        assert cs._nombre_con_tratamiento("Kevin Soto", "Lic.") == "LIC. KEVIN SOTO"
        assert cs._nombre_con_tratamiento("Kevin Soto", "Ing.") == "ING. KEVIN SOTO"

    def test_sin_tratamiento_el_nombre_sale_solo(self):
        """Los de diplomado continuo no llevan tratamiento."""
        assert cs._nombre_con_tratamiento("Kevin Soto", None) == "KEVIN SOTO"
        assert cs._nombre_con_tratamiento("Kevin Soto", "") == "KEVIN SOTO"
        assert cs._nombre_con_tratamiento("Kevin Soto", "   ") == "KEVIN SOTO"

    def test_rechaza_tratamientos_inventados(self):
        from pydantic import ValidationError
        from schemas.certificate_request import CertificateRequestAprobar
        with pytest.raises(ValidationError):
            CertificateRequestAprobar(tratamiento="Sr.")

    def test_acepta_los_tratamientos_de_la_lista(self):
        from schemas.certificate_request import CertificateRequestAprobar, TRATAMIENTOS_VALIDOS
        for t in TRATAMIENTOS_VALIDOS:
            assert CertificateRequestAprobar(tratamiento=t).tratamiento == t

    def test_vacio_se_normaliza_a_None(self):
        from schemas.certificate_request import CertificateRequestAprobar
        assert CertificateRequestAprobar(tratamiento="  ").tratamiento is None

    def test_el_certificado_guarda_el_tratamiento_usado(self):
        """
        Hace falta para que el re-render de respaldo reproduzca el documento
        tal cual se emitio.
        """
        from models.certificate import Certificate
        assert "tratamiento" in Certificate.model_fields
        assert "membrete" in Certificate.model_fields


# ==========================================================================
# 5. Hoja membretada
# ==========================================================================

class TestMembrete:
    def test_los_dos_membretes_estan_presentes(self):
        assert cs.hay_membrete("CARTA") is True
        assert cs.hay_membrete("OFICIO") is True

    def test_formato_desconocido_no_revienta(self):
        assert cs.hay_membrete("A3") is False

    def test_carta_y_oficio_tienen_zonas_seguras_distintas(self):
        """
        El pie del OFICIO es mucho mas alto que el de CARTA (64.9mm contra
        41.6mm, medido sobre el archivo real). Usar el mismo margen para los
        dos meteria el texto debajo del grafico.
        """
        carta = cs.MEMBRETE_LAYOUT["CARTA"]
        oficio = cs.MEMBRETE_LAYOUT["OFICIO"]
        assert oficio["bottom_mm"] > carta["bottom_mm"]

    def test_el_pdf_sale_del_tamano_de_la_hoja(self):
        from pypdf import PdfReader
        for formato in ("CARTA", "OFICIO"):
            pdf = cs.render_pdf_no_deudor_membretado(
                student=_student(), course=_course(), enrollment=_enrollment(),
                hasta_modulo_n=3, folio="N° 042/2026",
                emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
                tratamiento="Lic.", formato=formato,
            )
            pagina = PdfReader(io.BytesIO(pdf)).pages[0]
            esperado = cs.MEMBRETE_LAYOUT[formato]
            assert abs(float(pagina.mediabox.width) - esperado["ancho_pt"]) < 1
            assert abs(float(pagina.mediabox.height) - esperado["alto_pt"]) < 1

    def test_el_texto_del_certificado_queda_en_el_pdf(self):
        """
        El membrete es solo grafico; lo que tiene que ser texto real es el
        cuerpo del certificado, para que se pueda buscar y copiar.
        """
        from pypdf import PdfReader
        pdf = cs.render_pdf_no_deudor_membretado(
            student=_student(), course=_course(), enrollment=_enrollment(),
            hasta_modulo_n=3, folio="N° 042/2026",
            emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
            tratamiento="Lic.",
        )
        texto = (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")
        assert "CERTIFICADO DE NO DEUDOR" in texto
        assert "LIC. KEVIN ANDRES SOTO VILLARROEL" in texto
        # F-CERT-REDACCION (Kevin 2026-08-17): la redaccion la dicto el:
        # "certifica que el o la postgraduante (nombre) del programa
        # (programa) no tiene deuda economica pendiente del programa
        # mencionado de acuerdo al compromiso...".
        assert "Que el o la postgraduante" in texto
        assert "no tiene deuda económica pendiente" in texto
        assert "de acuerdo al compromiso de pago firmado" in texto

    def test_el_alcance_solo_aparece_si_es_parcial(self):
        """
        La redaccion que dicto Kevin afirma que no hay deuda "del programa
        mencionado", sin mas. Eso es correcto SOLO cuando el certificado
        cubre el programa entero.

        Si cubre hasta el modulo N de un total mayor hay que decirlo: sin esa
        aclaracion el documento afirmaria que el estudiante no debe nada de un
        programa que todavia esta pagando.
        """
        from pypdf import PdfReader

        def texto_de(hasta_n):
            pdf = cs.render_pdf_no_deudor_membretado(
                student=_student(), course=_course(), enrollment=_enrollment(n_modulos=5),
                hasta_modulo_n=hasta_n, folio="N° 043/2026",
                emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
            )
            return (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")

        completo = texto_de(5)
        assert "del programa mencionado" in completo
        assert "hasta el Módulo" not in completo, (
            "cubriendo todo el programa no corresponde acotar el alcance"
        )

        parcial = texto_de(3)
        assert "hasta el Módulo 3" in parcial, (
            "un certificado parcial DEBE decir hasta que modulo cubre"
        )

    def test_sin_fechas_de_modulo_no_queda_un_guion_suelto(self):
        """
        BUG REAL, encontrado mirando el certificado N° 007/2026 ya emitido a
        un estudiante: el modulo no tenia fechas cargadas, el helper de rango
        devolvia "—" y el documento oficial salia diciendo
        'hasta el Modulo 1 (—)'. Sin fechas, el parentesis se omite entero.
        """
        from pypdf import PdfReader

        sin_fechas = _Obj(modulos=[
            _Obj(nombre=f"Modulo {i}", estado="Pagado", fecha_inicio=None, fecha_fin=None)
            for i in range(1, 6)
        ])
        pdf = cs.render_pdf_no_deudor_membretado(
            student=_student(), course=_course(), enrollment=sin_fechas,
            hasta_modulo_n=1, folio="N° 007/2026",
            emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )
        texto = (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")
        assert "(—)" not in texto, "quedo el rango vacio entre parentesis"
        assert "( )" not in texto
        assert "Módulo 1" in texto

    def test_con_fechas_el_rango_si_aparece(self):
        """El arreglo no debe borrar el rango cuando las fechas SI existen."""
        from pypdf import PdfReader

        pdf = cs.render_pdf_no_deudor_membretado(
            student=_student(), course=_course(), enrollment=_enrollment(),
            hasta_modulo_n=1, folio="N° 008/2026",
            emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )
        texto = (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")
        assert "01/03/2026" in texto

    def test_la_facultad_tiene_el_nombre_correcto(self):
        """
        Kevin, 2026-08-17: el nombre que estaba ("FACULTAD DE AUDITORIA
        FINANCIERA O CONTADURIA PUBLICA") no es el de la facultad. El correcto
        es el que figura en la hoja membretada y en el cargo del director.
        """
        assert "CIENCIAS CONTABLES" in cs.UAGRM_FACULTAD
        assert "SISTEMAS DE CONTROL DE GESTIÓN Y FINANZAS" in cs.UAGRM_FACULTAD
        assert "AUDITORIA FINANCIERA O CONTADURIA" not in cs.UAGRM_FACULTAD

    def test_la_facultad_se_nombra_una_sola_vez(self):
        """
        Kevin: "que no repita lo mismo". Antes la facultad aparecia TRES veces
        en media carilla (presentacion, cuerpo, y pie de cada firma), mas la
        que ya trae impresa la hoja membretada.
        """
        from pypdf import PdfReader

        pdf = cs.render_pdf_no_deudor_membretado(
            student=_student(), course=_course(), enrollment=_enrollment(),
            hasta_modulo_n=3, folio="N° 044/2026",
            emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )
        texto = (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")
        # El unico lugar donde queda es la linea de presentacion y el cargo del
        # director (que Kevin paso con la facultad incluida). Dos, no cuatro.
        assert texto.count("CIENCIAS CONTABLES") <= 2, (
            "la facultad se sigue repitiendo de mas: %d veces"
            % texto.count("CIENCIAS CONTABLES")
        )
        # El cargo de la coordinadora ya no la repite.
        assert "UNIDAD DE POSTGRADO" in cs.FIRMANTE_COORD_CARGO
        assert "CONTADURIA" not in cs.FIRMANTE_COORD_CARGO

    def test_los_firmantes_son_los_correctos(self):
        """
        Datos confirmados por Kevin el 2026-08-17. Los anteriores tenian dos
        errores en un documento oficial ya emitido: decia "Claudio" en una
        firma cuyo cargo es "COORDINADORA", y la segunda firma era otra
        persona ("M.Sc. Ortega Blanca Muñoz" en vez del director real).

        Se fija con test porque es el tipo de dato que nadie vuelve a mirar y
        sale impreso con la firma de la unidad.
        """
        assert cs.FIRMANTE_COORD_NOMBRE == "Lic. Claudia R. Cuéllar Paz"
        assert "Claudio" not in cs.FIRMANTE_COORD_NOMBRE
        assert cs.FIRMANTE_DIRECTORA_NOMBRE == "Ph.D. Fausto Mendoza Iriarte"
        assert "DIRECTOR DE POSTGRADO" in cs.FIRMANTE_DIRECTORA_CARGO

    def test_los_firmantes_salen_impresos_en_el_pdf(self):
        from pypdf import PdfReader

        pdf = cs.render_pdf_no_deudor_membretado(
            student=_student(), course=_course(), enrollment=_enrollment(),
            hasta_modulo_n=3, folio="N° 009/2026",
            emitido_en=datetime(2026, 8, 17, tzinfo=timezone.utc),
        )
        texto = (PdfReader(io.BytesIO(pdf)).pages[0].extract_text() or "").replace("\n", " ")
        assert "Claudia R. Cuéllar Paz" in texto
        assert "Fausto Mendoza Iriarte" in texto
        assert "Ortega Blanca Muñoz" not in texto

    def test_si_falta_el_membrete_se_emite_igual(self):
        """
        Un despliegue al que le falte assets/ no deberia dejar a la unidad
        sin poder emitir certificados.
        """
        src = _fuente("services/certificate_service.py")
        assert "usar_membrete = hay_membrete(formato_membrete)" in src
        assert "Se emite con el formato" in src
