"""
F-FIX-CLOUDINARY-URL-ROTA (2026-08-19)

Kevin encontro un 404 al intentar "Ver comprobante" de un certificado desde
el perfil de coordinador financiero. Root cause verificado en vivo (subida
real a Cloudinary vía la cuenta de produccion, consultada con su Admin API):

`upload_document()` pegaba ".pdf" al final del string de `secure_url`
DESPUES de subir el archivo, asumiendo que asi quedaba igual a como
Cloudinary lo guardo. Nunca fue asi: el recurso subido queda con
`format: None` y sin extension en su path real, asi que la URL con
extension pegada jamas existio (confirmado: esa URL da 404, la misma sin
la extension da 200).

Se probaron dos arreglos que fallaron antes de llegar al que funciona:
  1. `format=ext` en el upload — no-op del lado de Cloudinary para
     `resource_type="raw"`.
  2. Generar un `public_id` propio con la extension incluida — la URL
     resultante SI coincide con el recurso real, pero la cuenta de
     Cloudinary tiene activa la proteccion "Restricted media types": da 401
     a cualquier entrega publica de un "raw" cuyo path termine en una
     extension reconocida como PDF/ZIP (probado incluso con
     `access_mode="public"` explicito en el upload — sigue en 401). Es un
     toggle de la consola de Cloudinary, no arreglable por API con las
     credenciales del backend.

El fix real: no tocar la URL para nada — usar `result["secure_url"]` tal
cual la devuelve Cloudinary, sin concatenar extension. Verificado en vivo
end-to-end contra la cuenta real: 200 OK.
"""

import io
import os


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestUploadDocumentNoManipulaLaUrl:
    def _cuerpo_upload_document(self):
        src = _fuente("core", "cloudinary_utils.py")
        ini = src.index("async def upload_document")
        fin = src.find("\nasync def ", ini + 10)
        return src[ini: fin if fin != -1 else len(src)]

    def test_no_concatena_extension_al_secure_url(self):
        cuerpo = self._cuerpo_upload_document()
        codigo = "\n".join(
            l for l in cuerpo.splitlines() if not l.strip().startswith("#")
        )
        assert 'f"{url}' not in codigo
        assert ".endswith(" not in codigo

    def test_url_final_es_secure_url_sin_modificar(self):
        cuerpo = self._cuerpo_upload_document()
        assert 'url = result["secure_url"]' in cuerpo

    def test_no_pasa_format_al_upload_de_cloudinary(self):
        """
        `format=` es un no-op para resource_type="raw" (confirmado en vivo
        vía Admin API: el recurso queda con format=None de todas formas) —
        no debe volver a intentarse.
        """
        cuerpo = self._cuerpo_upload_document()
        codigo = "\n".join(
            l for l in cuerpo.splitlines() if not l.strip().startswith("#")
        )
        assert '"format"' not in codigo

    def test_no_genera_public_id_con_extension(self):
        """
        Generar un public_id con extension incluida hace que la URL exista,
        pero la cuenta de Cloudinary bloquea su entrega publica con 401
        (proteccion "Restricted media types", ver docstring del modulo) —
        no debe volver a intentarse sin antes resolver esa configuracion de
        cuenta con Kevin.
        """
        cuerpo = self._cuerpo_upload_document()
        assert "uuid.uuid4" not in cuerpo
