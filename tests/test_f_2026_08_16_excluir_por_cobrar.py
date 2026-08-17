"""
F-FIX-EXCLUIR-POR-COBRAR (2026-08-16)
=====================================

US-004 v4 (2026-08-04) agrego `Enrollment.excluir_por_cobrar` para poder
sacar una inscripcion del total "Por Cobrar" del dashboard sin cambiarle el
estado. Los DOS calculos de dinero ya lo respetaban:

    api/dashboard.py:777              -> if getattr(e, "excluir_por_cobrar", False): ...
    services/payment_service.py:1678  -> idem

Pero nunca se agrego el lado de ESCRITURA:
    - `EnrollmentUpdate` no declaraba el campo -> Pydantic lo descartaba
    - `EnrollmentResponse` tampoco -> la UI no podia leerlo de vuelta
    - el endpoint PUT /enrollments/{id} procesa los campos UNO POR UNO
      (descuento_personalizado, descuento_id, estado), asi que aunque el
      schema lo hubiera aceptado, igual se ignoraba

Resultado: un interruptor muerto. Imposible excluir una inscripcion del Por
Cobrar desde la API, que es justo lo que hacia falta para los descuadres
tipo R4.

Estos tests fijan el contrato de escritura y lectura.
"""

from schemas.enrollment import EnrollmentResponse, EnrollmentUpdate


class TestEnrollmentUpdate:
    def test_declara_el_flag(self):
        assert "excluir_por_cobrar" in EnrollmentUpdate.model_fields

    def test_permite_activarlo(self):
        u = EnrollmentUpdate(excluir_por_cobrar=True)
        assert u.model_dump(exclude_unset=True)["excluir_por_cobrar"] is True

    def test_permite_desactivarlo(self):
        """Volver a incluir la inscripcion en el Por Cobrar."""
        u = EnrollmentUpdate(excluir_por_cobrar=False)
        assert u.model_dump(exclude_unset=True)["excluir_por_cobrar"] is False

    def test_no_lo_toca_si_no_se_manda(self):
        """
        Clave: el endpoint distingue None ('no tocar') de False ('incluir').
        Si `exclude_unset` no lo dejara fuera, cualquier update de otro campo
        reactivaria inscripciones excluidas a proposito.
        """
        u = EnrollmentUpdate(descuento_personalizado=50.0)
        assert "excluir_por_cobrar" not in u.model_dump(exclude_unset=True)

    def test_por_defecto_es_none_no_false(self):
        """None y False significan cosas distintas para este campo."""
        u = EnrollmentUpdate()
        assert u.excluir_por_cobrar is None


class TestEnrollmentResponse:
    def test_expone_el_flag(self):
        """Sin esto la UI no puede mostrar si una inscripcion esta excluida."""
        assert "excluir_por_cobrar" in EnrollmentResponse.model_fields

    def test_default_false_para_inscripciones_viejas(self):
        """Las inscripciones previas al fix no tienen el campo en Mongo."""
        campo = EnrollmentResponse.model_fields["excluir_por_cobrar"]
        assert campo.default is False


class TestEndpointLoProcesa:
    """
    El endpoint maneja los campos explicitamente, no con un setattr generico:
    agregar el campo al schema NO alcanzaba. Este test lee el codigo para
    asegurar que el bloque siga existiendo si alguien refactoriza.
    """

    def test_el_endpoint_asigna_el_campo(self):
        import io
        import os

        ruta = os.path.join(os.path.dirname(__file__), "..", "api", "enrollments.py")
        src = io.open(ruta, encoding="utf-8").read()
        assert "enrollment_in.excluir_por_cobrar is not None" in src
        assert "enrollment.excluir_por_cobrar = enrollment_in.excluir_por_cobrar" in src
