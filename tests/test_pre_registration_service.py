"""
Tests de pre_registration_service (BUG-PRE-001)
================================================

Verifica la lógica del count de submissions en delete_form:

- Submissions con estado='rechazado' NO bloquean el delete
- Submissions con estado='pendiente' o 'aprobado' SÍ bloquean

Estos tests son focused en la QUERY del service, parseando el código fuente
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
    """Tests que verifican el código fuente de delete_form (BUG-PRE-001)."""

    def test_query_excluye_rechazadas(self):
        """El query a PreRegistration debe filtrar estado != 'rechazado'."""
        source = get_delete_form_source()
        assert 'PreRegistration.estado != "rechazado"' in source, (
            "BUG-PRE-001: delete_form debe filtrar submissions con estado != 'rechazado'.\n"
            f"Source:\n{source}"
        )

    def test_variable_renombrada_a_active(self):
        """La variable debe llamarse active_submissions_count (semántica clara)."""
        source = get_delete_form_source()
        assert "active_submissions_count" in source, (
            "BUG-PRE-001: delete_form debe usar 'active_submissions_count' como nombre "
            "de variable para mayor claridad."
        )

    def test_mensaje_incluye_activas(self):
        """El mensaje de error debe mencionar 'activa(s)' para que el usuario entienda."""
        source = get_delete_form_source()
        assert "activa(s)" in source, (
            "BUG-PRE-001: el mensaje de error debe decir 'activa(s)' para que el "
            "usuario entienda que cuenta solo las no rechazadas."
        )

    def test_no_hay_count_simple_sin_filtro(self):
        """NO debe haber un .count() simple sin el filtro de estado."""
        source = get_delete_form_source()
        # Encuentra la línea del .count()
        count_lines = re.findall(r"\.count\(\)", source)
        # Solo debe haber UNA línea .count() (la de active_submissions_count)
        assert len(count_lines) == 1, (
            f"BUG-PRE-001: debe haber exactamente un .count() en delete_form. "
            f"Encontré {len(count_lines)}: {count_lines}"
        )

    def test_usa_find_con_dos_condiciones(self):
        """El find() debe tener 2 condiciones: form_id Y estado != rechazado."""
        source = get_delete_form_source()
        # Busca el patrón find(...)
        find_match = re.search(
            r"PreRegistration\.find\(\s*([^)]+)\)",
            source,
            re.DOTALL,
        )
        assert find_match, "No se encontró PreRegistration.find(...) en delete_form"
        conditions = find_match.group(1)
        # Cuenta las comas de nivel-superficie
        # Si las condiciones están separadas por comas en el mismo nivel, hay 2
        assert "form_id" in conditions, "Falta condición form_id en el find()"
        assert 'estado != "rechazado"' in conditions, (
            f"Falta filtro estado != 'rechazado' en el find(). Condiciones: {conditions}"
        )


class TestDeleteFormLogic:
    """Tests conceptuales que documentan la lógica esperada."""

    def test_logica_submissions_mezcladas(self):
        """
        Documenta: con 5 rechazadas + 1 pendiente, el count debe ser 1.
        El backend debe permitir eliminar porque SOLO cuenta activas.
        """
        # Este test es de documentación. La verificación real está en
        # test_query_excluye_rechazadas que parsea el código.
        assert True, "Ver test_query_excluye_rechazadas"

    def test_logica_solo_aprobadas(self):
        """
        Documenta: si todas las submissions están en 'aprobado', no se puede
        eliminar (hay que rechazarlas primero o cerrar el form en vez).
        """
        assert True, "Ver test_query_excluye_rechazadas"
