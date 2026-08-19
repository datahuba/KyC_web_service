"""
F-FIX-COMPROBANTE-DICT (2026-08-19)
====================================

Kevin probando el flujo nuevo de comprobante obligatorio (F-CERT-COMPROBANTE-
OBLIGATORIO, mergeado horas antes) se llevo un 422 al hacer clic en
"Solicitar": "Input should be a valid string".

Causa raiz: `upload_document()` (core/cloudinary_utils.py) devuelve un DICT
({url, public_id, resource_type, mime_type, size_bytes}), no un string plano.
Tres endpoints trataban su valor de retorno como si YA fuera el string de la
URL:

- api/certificates.py: subir_comprobante_cert (existente desde el
  2026-08-17, PRE-EXISTENTE — no lo introdujo la sesion de hoy).
- api/certificates.py: upload_comprobante_temp (nuevo de esta sesion, HEREDO
  el bug al copiar el patron del endpoint de arriba).
- api/bug_reports.py: los adjuntos de "Reportar un Error" tenian el mismo
  problema, encontrado al auditar todos los call sites de upload_document().

Efecto real: el dict entero (con las 5 claves) quedaba guardado donde se
esperaba un string. Para el certificado, ese dict via al re-enviarse en el
JSON de creacion de la solicitud, y Pydantic lo rechazaba con 422 porque
`comprobante_url` es `str`. Para bug_reports, el dict quedaba en
`adjuntos: List[str]`, silenciosamente mal tipado (sin 422 inmediato porque
no vuelve a pasar por validacion de schema, pero rompe cualquier cosa que
espere una URL ahi, ej. el link "Ver adjunto").

Como se encontro: se reprodujo el error real contra produccion mandando un
POST con `comprobante_url` como objeto en vez de string, y el mensaje/loc
devuelto coincidio EXACTO con el que reporto Kevin.
"""

import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestUploadDocumentDevuelveUnDict:
    def test_la_firma_declara_dict(self):
        src = _fuente("core", "cloudinary_utils.py")
        ini = src.index("async def upload_document")
        # La firma es multi-linea; el cierre real es "\n) -> dict:", no el
        # primer ":" (que aparece antes, en "file: UploadFile").
        fin = src.index("\n) -> dict:", ini)
        firma = src[ini:fin]
        assert "async def upload_document" in firma, (
            "si upload_document cambia a devolver un string, hay que "
            "actualizar este test Y revisar todos los call sites de nuevo"
        )

    def test_el_dict_tiene_la_clave_url(self):
        src = _fuente("core", "cloudinary_utils.py")
        ini = src.index("async def upload_document")
        fin = src.find("\nasync def ", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]
        assert '"url": url' in cuerpo


class TestCertificatesExtraeElStringCorrectamente:
    def test_subir_comprobante_cert_no_trata_el_dict_como_string(self):
        """
        Endpoint pre-existente (2026-08-17). Regresion real: guardaba el
        dict completo en CertificateRequest.comprobante_url (campo str).
        """
        src = _fuente("api", "certificates.py")
        ini = src.index("async def subir_comprobante_cert")
        fin = src.find("\n@router.", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]

        assert 'resultado["url"]' in cuerpo or "resultado['url']" in cuerpo, (
            "subir_comprobante_cert debe extraer ['url'] del dict que "
            "devuelve upload_document(), no usar el dict entero"
        )

    def test_upload_comprobante_temp_no_trata_el_dict_como_string(self):
        """
        Endpoint nuevo de esta sesion. Reproducido en vivo contra
        produccion: mandar {"url": "..."} como comprobante_url produce
        exactamente 'Input should be a valid string' en loc
        ['body', 'comprobante_url'] — el bug que vio Kevin.
        """
        src = _fuente("api", "certificates.py")
        ini = src.index("async def upload_comprobante_temp")
        fin = src.find("\n@router.", ini + 10)
        cuerpo = src[ini: fin if fin != -1 else len(src)]

        assert 'resultado["url"]' in cuerpo or "resultado['url']" in cuerpo


class TestBugReportsExtraeElStringCorrectamente:
    def test_los_adjuntos_no_guardan_el_dict_completo(self):
        """
        Mismo bug, encontrado al auditar TODOS los call sites de
        upload_document() tras diagnosticar el del certificado. Sin este
        fix, cada adjunto de un reporte de error queda como un dict en vez
        de una URL, rompiendo el link "Ver adjunto".
        """
        src = _fuente("api", "bug_reports.py")
        ini = src.index("for archivo in reales:")
        fin = src.index("reporte = BugReport(")
        cuerpo = src[ini:fin]

        assert 'resultado["url"]' in cuerpo or "resultado['url']" in cuerpo
        assert "urls.append(url)" not in cuerpo, (
            "volvio a appendear el dict entero en vez del string"
        )


class TestLosDemasCallSitesYaEstabanBien:
    """
    Documentan que estos NO tenian el bug, para que quede registrado por
    que no se tocaron al hacer la auditoria completa.
    """

    def test_pre_registrations_ya_extraia_url(self):
        src = _fuente("api", "pre_registrations.py")
        assert src.count('result["url"]') >= 3

    def test_classroom_material_service_ya_extraia_url(self):
        src = _fuente("services", "classroom_material_service.py")
        assert 'result["url"]' in src

    def test_submission_service_ya_extraia_url(self):
        src = _fuente("services", "submission_service.py")
        assert 'result["url"]' in src
