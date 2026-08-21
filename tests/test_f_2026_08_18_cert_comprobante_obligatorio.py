"""
F-CERT-COMPROBANTE-OBLIGATORIO (2026-08-18)
===========================================

Kevin, textual: "hay que solicitar obviamente el comprobante al estudiante.
Una vez sube el comprobante, recien se pueda dejar enviar la solicitud".

Esto CIERRA una decision que estaba abierta desde el 2026-08-17: "el
comprobante debe ser obligatorio para aprobar?". La respuesta resulto ser que
bloquea ANTES, al enviar, no al aprobar.

Por que importa la diferencia: bloquear la APROBACION dejaba sin camino al
cobro en ventanilla. El estudiante paga en caja, no tiene comprobante digital,
y el coordinador no podia aprobar aunque le constara el pago. Exigirlo al
ENVIAR no tiene ese problema — el alumno le saca una foto a su recibo de caja
igual — y ademas le llega al coordinador ya con el respaldo adjunto.

Solo aplica a 'no_deudor', que es el unico tipo con arancel. El certificado de
notas no cobra nada y no debe pedir comprobante.
"""

import io
import os

import pytest


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


def _crear_solicitud_sin_comentarios():
    src = _fuente("services", "certificate_request_service.py")
    ini = src.index("async def crear_solicitud")
    fin = src.index("async def listar_mis_solicitudes")
    bloque = src[ini:fin]
    return "\n".join(
        l for l in bloque.splitlines() if not l.strip().startswith("#")
    )


class TestElSchemaAceptaElComprobante:
    def test_create_tiene_el_campo(self):
        src = _fuente("schemas", "certificate_request.py")
        ini = src.index("class CertificateRequestCreate")
        # Buscar la clase SIGUIENTE, no la actual: `index("class ")` sobre el
        # bloque ya recortado devuelve 0 y deja el fragmento vacio.
        fin = src.find("\nclass ", ini + 1)
        bloque = src[ini: fin if fin != -1 else len(src)]
        assert "comprobante_url" in bloque

    def test_el_campo_es_opcional_en_el_schema(self):
        """
        Opcional en el schema y obligatorio SOLO para no_deudor en la logica:
        el certificado de notas no cobra arancel, asi que exigirlo ahi seria
        pedir un comprobante de algo que no se paga.
        """
        from schemas.certificate_request import CertificateRequestCreate

        campo = CertificateRequestCreate.model_fields["comprobante_url"]
        assert campo.is_required() is False


class TestSeExigeAlEnviarNoAlAprobar:
    def test_crear_solicitud_valida_el_comprobante(self):
        bloque = _crear_solicitud_sin_comentarios()

        assert "comprobante_url" in bloque, (
            "crear_solicitud dejo de exigir el comprobante"
        )
        assert "TipoCertificado.NO_DEUDOR" in bloque

    def test_solo_se_exige_para_no_deudor(self):
        """Los tipos con arancel > 0 exigen comprobante al enviar."""
        bloque = _crear_solicitud_sin_comentarios()
        assert "if monto and monto > 0 and not (data.comprobante_url or \"\").strip():" in bloque

    def test_el_comprobante_queda_guardado_en_la_solicitud(self):
        """
        Si se exige y no se persiste, el coordinador no lo ve y el estudiante
        tuvo que subirlo para nada.
        """
        bloque = _crear_solicitud_sin_comentarios()
        assert "comprobante_url=" in bloque

    def test_la_aprobacion_sigue_sin_bloquear(self):
        """
        La aprobacion NO debe exigir comprobante: el coordinador tiene el boton
        "Verificar pagos" para el caso de caja fisica. Si alguien agrega ahi la
        validacion, vuelve el problema que esta decision evito.
        """
        src = _fuente("services", "certificate_request_service.py")
        ini = src.index("async def aprobar_solicitud")
        fin = src.find("\nasync def ", ini + 10)
        bloque = src[ini: fin if fin != -1 else len(src)]
        codigo = "\n".join(
            l for l in bloque.splitlines() if not l.strip().startswith("#")
        )

        assert "not req.comprobante_url" not in codigo, (
            "la aprobacion volvio a exigir comprobante: deja sin camino al "
            "cobro en ventanilla"
        )


class TestElMensajeExplicaQueHacer:
    def test_menciona_el_monto_y_el_caso_de_caja(self):
        """
        Un 422 seco no le dice al estudiante que hacer. El mensaje tiene que
        decir cuanto es y que la foto del recibo de caja sirve.
        """
        src = _fuente("services", "certificate_request_service.py")
        assert "en caja" in src
        assert "comprobante del pago del arancel" in src
