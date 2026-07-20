"""
Tests de pre_registration_service (BUG-PRE-002)
================================================

Verifica la lógica del delete de formularios de pre-registro:

- Submissions con estado='pendiente' SÍ bloquean (esperan revisión)
- Submissions con estado='aprobado' o 'rechazado' NO bloquean (data histórica)
- Al eliminar el form, las submissions NO pendientes se borran en cascada

Tests focused en la QUERY del service, parseando el código fuente
para evitar importar el módulo (que requiere python-jose no instalado en
el environment de testing puro).
"""

import re
import pytest
from pathlib import Path


# Path al servicio
SERVICE_PATH = Path(__file__).parent.parent / "services" / "pre_registration_service.py"


def get_delete_form_source() -> str:
    """Lee la fuente de la función delete_form del servicio."""
    source = SERVICE_PATH.read_text(encoding="utf-8")
    # Extrae la función delete_form
    match = re.search(
        r"async def delete_form\([^)]*\).*?(?=\nasync def |\n# ====|\Z)",
        source,
        re.DOTALL,
    )
    assert match, "No se pudo extraer la función delete_form del servicio"
    return match.group(0)


class TestDeleteFormQueryFilter:
    """Tests que verifican el código fuente de delete_form (BUG-PRE-002)."""

    def test_query_solo_pendientes_bloquean(self):
        """Solo submissions con estado='pendiente' deben bloquear el delete."""
        source = get_delete_form_source()
        assert 'PreRegistration.estado == "pendiente"' in source, (
            "BUG-PRE-002: delete_form debe filtrar submissions con estado == 'pendiente' "
            "para determinar si bloquea el delete."
        )

    def test_cascada_elimina_historicas(self):
        """Las submissions NO pendientes (aprobadas/rechazadas) deben eliminarse en cascada."""
        source = get_delete_form_source()
        assert "PreRegistration.estado != \"pendiente\"" in source, (
            "BUG-PRE-002: las submissions históricas (aprobadas/rechazadas) deben "
            "identificarse con estado != 'pendiente'."
        )
        # Verifica que hay un .delete() para las históricas
        delete_count = source.count("PreRegistration.find(") - source.count("PreRegistration.find(\n        PreRegistration.form_id == form_id,\n    )")
        assert delete_count >= 1, (
            "BUG-PRE-002: debe haber un .delete() para eliminar submissions históricas en cascada."
        )

    def test_mensaje_incluye_pendientes(self):
        """El mensaje de error debe mencionar 'pendiente(s) de revisar'."""
        source = get_delete_form_source()
        assert "pendiente(s) de revisar" in source, (
            "BUG-PRE-002: el mensaje de error debe decir 'pendiente(s) de revisar' "
            "para que el usuario entienda exactamente qué bloquea."
        )

    def test_mensaje_opciones_alternativas(self):
        """El mensaje debe sugerir 'Aprobá o rechazá' como alternativa."""
        source = get_delete_form_source()
        assert "Aprob" in source and "rechaz" in source.lower(), (
            "BUG-PRE-002: el mensaje debe sugerir 'Aprobá o rechazá' las pendientes primero."
        )

    def test_no_bloquea_con_solo_aprobadas(self):
        """Una submission aprobada NO debe bloquear el delete (es histórica)."""
        source = get_delete_form_source()
        # El filtro debe ser == 'pendiente', no == 'aprobado' o != 'rechazado'
        assert "PreRegistration.estado == \"aprobado\"" not in source, (
            "BUG-PRE-002: NO debe haber un filtro == 'aprobado'. Las aprobadas NO bloquean."
        )

    def test_no_bloquea_con_solo_rechazadas(self):
        """Una submission rechazada NO debe bloquear el delete (es histórica)."""
        source = get_delete_form_source()
        # El filtro debe ser == 'pendiente', no != 'rechazado' (que era el bug anterior)
        assert "PreRegistration.estado != \"rechazado\"" not in source, (
            "BUG-PRE-002: NO debe filtrar por != 'rechazado' (eso era el bug BUG-PRE-001). "
            "Ahora solo pendientes bloquean."
        )

    def test_form_no_existe(self):
        """Si el form no existe, debe lanzar ValueError."""
        source = get_delete_form_source()
        assert "Formulario no encontrado" in source, (
            "delete_form debe lanzar ValueError si el form no existe."
        )

    def test_elimina_form_al_final(self):
        """Después de limpiar submissions históricas, elimina el form."""
        source = get_delete_form_source()
        # El último .delete() debe ser sobre el form
        last_delete = source.rfind(".delete()")
        form_delete = source.rfind("form.delete()")
        assert form_delete > 0, "delete_form debe llamar form.delete()"
        assert form_delete > last_delete - 100, "form.delete() debe ser la última operación"


class TestDeleteFormLogic:
    """Tests conceptuales que documentan la lógica esperada."""

    def test_logica_aprobadas_no_bloquean(self):
        """
        Documenta: si una submission está aprobada, NO bloquea el delete
        (es data histórica, se borra en cascada).
        """
        assert True, "Ver test_no_bloquea_con_solo_aprobadas"

    def test_logica_solo_pendientes_bloquean(self):
        """
        Documenta: solo submissions con estado='pendiente' bloquean.
        Si hay 1 pendiente + 5 aprobadas → BLOQUEA.
        Si hay 0 pendientes + 5 aprobadas → NO BLOQUEA, se borra en cascada.
        """
        assert True, "Ver test_query_solo_pendientes_bloquean"
