"""
F-046 · Calificar módulo retornaba 500 (22/7 audios)
====================================================

Síntoma reportado (Sandra Zabala, audios 22/7 19:12):
  "algunos detalles que no están funcionando bien en el guardado de las notas
   ni de manera individual ni de manera conjunta"

Root cause (en logs del contenedor):
  File "/app/services/enrollment_service.py", line 719, in subir_nota_borrador
    enrollment.updated_at = utcnow_naive()
                            ^^^^^^^^^^^^
  NameError: name 'utcnow_naive' is not defined

Causa: al refactorizar, `utcnow_naive()` se movió a `core/timezone_utils.py`,
pero solo se importaba LOCALMENTE en `enrich_enrollment_dates`. Las 9 funciones
que la usan NO la importaban localmente → todas reventaban con NameError.

Funciones afectadas:
  - subir_nota_borrador (línea 719)         ← la que reporta Sandra
  - actualizar_saldo_enrollment (línea 408)
  - cambiar_estado_inscripcion (450, 571, 604, 628)
  - eximir_matricula (598, 604)
  - rechazar_nota_borrador (826)

Fix: agregar `from core.timezone_utils import utcnow_naive` a nivel módulo.

Este test verifica AMBAS cosas:
  1. Que el import está presente a nivel módulo en enrollment_service.py
  2. Que el import está bien formado (no es solo en una función)
"""

import re
from pathlib import Path


# Path al archivo de servicio
SERVICE_FILE = Path(__file__).parent.parent / "services" / "enrollment_service.py"


class TestF046UtcnowImport:
    """F-046: utcnow_naive debe estar importado a nivel módulo."""

    def test_archivo_existe(self):
        assert SERVICE_FILE.exists(), f"No se encontró {SERVICE_FILE}"

    def test_utcnow_naive_importado_a_nivel_modulo(self):
        """
        El import `from core.timezone_utils import utcnow_naive` debe estar
        a nivel módulo (NO dentro de una función), para que esté disponible
        en todas las funciones que lo usan.
        """
        content = SERVICE_FILE.read_text(encoding="utf-8-sig")

        # Buscar el import exacto a nivel módulo
        # Debe estar precedido solo por whitespace o comentarios de import,
        # NO por indentación (que indicaría que está dentro de una función)
        pattern = r"^from\s+core\.timezone_utils\s+import\s+utcnow_naive\s*$"
        match = re.search(pattern, content, re.MULTILINE)

        assert match is not None, (
            "F-046: Falta `from core.timezone_utils import utcnow_naive` "
            "a nivel módulo en enrollment_service.py. Esto causa que "
            "subir_nota_borrador y 8 funciones más revienten con NameError "
            "cuando se llaman (regression de F-046)."
        )

    def test_utcnow_naive_no_solo_en_funcion_local(self):
        """
        Antes del fix, el import solo estaba en `enrich_enrollment_dates`.
        Verificar que AHORA está a nivel módulo (no solo dentro de una función).
        """
        content = SERVICE_FILE.read_text(encoding="utf-8-sig")

        # Buscar imports dentro de funciones (indentados)
        indented_pattern = r"^\s+from\s+core\.timezone_utils\s+import\s+utcnow_naive"
        indented_match = re.search(indented_pattern, content, re.MULTILINE)

        module_pattern = r"^from\s+core\.timezone_utils\s+import\s+utcnow_naive\s*$"
        module_match = re.search(module_pattern, content, re.MULTILINE)

        # Si hay import dentro de función PERO NO a nivel módulo → bug
        if indented_match and not module_match:
            pytest.fail(
                "F-046: El import de utcnow_naive solo está dentro de una "
                "función, no a nivel módulo. Esto causa NameError en otras "
                "funciones que lo usan."
            )

    def test_subir_nota_borrador_usa_utcnow_naive(self):
        """
        Verificar que la función `subir_nota_borrador` llama a `utcnow_naive()`,
        que es donde se disparó el NameError original.
        """
        content = SERVICE_FILE.read_text(encoding="utf-8-sig")

        # Buscar la función subir_nota_borrador
        func_pattern = (
            r"async\s+def\s+subir_nota_borrador.*?(?=\nasync\s+def\s+|\nclass\s+|\Z)"
        )
        func_match = re.search(func_pattern, content, re.DOTALL)

        assert func_match is not None, (
            "No se encontró la función `subir_nota_borrador` en enrollment_service.py"
        )

        func_body = func_match.group(0)
        assert "utcnow_naive()" in func_body, (
            "La función `subir_nota_borrador` debe llamar a `utcnow_naive()` "
            "para actualizar `enrollment.updated_at`."
        )

    def test_todas_las_funciones_rotas_usan_utcnow_naive(self):
        """
        Listar todas las funciones que usan utcnow_naive() y verificar
        que el import a nivel módulo las cubre a TODAS.
        """
        content = SERVICE_FILE.read_text(encoding="utf-8-sig")

        # Buscar todas las definiciones de funciones async
        func_pattern = r"async\s+def\s+(\w+)"
        funciones = re.findall(func_pattern, content)

        # Funciones que sabemos que usan utcnow_naive
        funciones_esperadas = [
            "subir_nota_borrador",
            "actualizar_saldo_enrollment",
            "cambiar_estado_enrollment",
            "otorgar_matricula_exenta",
            "rechazar_nota_borrador",
        ]

        for func_name in funciones_esperadas:
            assert func_name in funciones, (
                f"F-046: Se esperaba encontrar la función `{func_name}` "
                f"en enrollment_service.py"
            )
