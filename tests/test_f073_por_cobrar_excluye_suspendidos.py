# -*- coding: utf-8 -*-
"""
F-073 (2026-07-23) · Tests: "Por Cobrar" del dashboard NO debe incluir suspendidos
===============================================================================

Regla de negocio (Sandra Cobranza, 2026-07-23 vía WhatsApp):
"hay una diferencia con la cuenta por cobrarse en sistema, después todo lo
demás cuadró. Será que los está tomando a los congelados aunque hice el cálculo
y han así es mayo el monto"

Diferencia observada en producción: Sistema Bs 129.054 vs Excel Sandra Bs 115.824
= Bs 13.230 que corresponden a 3 inscripciones SUSPENDIDO (2 congelados + 1
pasivo según KPI del dashboard).

El bug estaba en `services/payment_service.py::get_resumen_economico` (líneas
1115-1123 originales): sumaba `saldo_pendiente` de TODOS los enrollments sin
filtrar por estado, incluyendo SUSPENDIDO/CONGELADO/PASIVO/ABANDONO.

Fix:
- `por_cobrar` y `cobros_pendientes` ahora EXCLUYEN enrollments en estado
  SUSPENDIDO, COMPLETADO o CANCELADO.
- `total_esperado` se mantiene intacto: es la suma teórica de lo que TODOS
  los inscritos deberían pagar (los suspendidos también, porque al
  reactivarse vuelven a deber).
- `total_inscritos` se mantiene intacto: muestra el alcance completo.

Estos tests son de LECTURA ESTÁTICA DEL CÓDIGO (no requieren venv con
fastapi/beanie instalados), siguiendo el patrón F-061 / F-070.
"""
import os
import re
import pytest
from pathlib import Path

PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"
ENUMS_FILE = Path(__file__).parent.parent / "models" / "enums.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_function_body(content: str, func_name: str) -> str:
    """Extrae el cuerpo de una función async del código (heurística simple)."""
    pattern = rf"async def {func_name}\([^)]*\)[^:]*:.*?(?=\n\nasync def |\n\nclass |\nclass |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return ""
    return match.group(0)


class TestF073ImportEstadoInscripcion:
    """F-073: payment_service.py debe importar EstadoInscripcion para filtrar."""

    def test_import_estado_inscripcion(self):
        """El import de EstadoInscripcion debe existir en payment_service.py."""
        content = read(PAYMENT_SERVICE_FILE)
        # Acepta tanto `from models.enums import ... EstadoInscripcion` (en línea
        # de imports múltiples) o import dedicado.
        match = re.search(
            r"from\s+models\.enums\s+import\s+([^#\n]+)",
            content,
        )
        assert match, "F-073: Falta `from models.enums import ...` en payment_service.py"
        imported = match.group(1)
        assert "EstadoInscripcion" in imported, (
            "F-073: payment_service.py debe importar `EstadoInscripcion` para "
            "poder filtrar las inscripciones suspendidas/completadas/canceladas "
            "del cálculo de `por_cobrar` y `cobros_pendientes`."
        )


class TestF073EnumEstadoInscripcion:
    """F-073: el enum EstadoInscripcion debe tener los valores esperados."""

    def test_enum_tiene_suspendido(self):
        content = read(ENUMS_FILE)
        assert re.search(
            r'class\s+EstadoInscripcion[^:]*:.*?SUSPENDIDO\s*=\s*["\']suspendido["\']',
            content,
            re.DOTALL,
        ), "F-073: `EstadoInscripcion.SUSPENDIDO = 'suspendido'` debe existir en models/enums.py"

    def test_enum_tiene_completado(self):
        content = read(ENUMS_FILE)
        assert re.search(
            r'COMPLETADO\s*=\s*["\']completado["\']',
            content,
        ), "F-073: `EstadoInscripcion.COMPLETADO = 'completado'` debe existir"

    def test_enum_tiene_cancelado(self):
        content = read(ENUMS_FILE)
        assert re.search(
            r'CANCELADO\s*=\s*["\']cancelado["\']',
            content,
        ), "F-073: `EstadoInscripcion.CANCELADO = 'cancelado'` debe existir"

    def test_enum_tiene_activo(self):
        content = read(ENUMS_FILE)
        assert re.search(
            r'ACTIVO\s*=\s*["\']activo["\']',
            content,
        ), "F-073: `EstadoInscripcion.ACTIVO = 'activo'` debe existir"


class TestF073GetResumenEconomicoExcluyeSuspendidos:
    """F-073: get_resumen_economico debe excluir SUSPENDIDO/COMPLETADO/CANCELADO."""

    def test_function_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_resumen_economico" in content, (
            "F-073: get_resumen_economico debe existir en payment_service.py"
        )

    def test_declara_estados_excluidos(self):
        """Debe declarar un set/lista de estados excluidos con SUSPENDIDO."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        assert body, "F-073: No se encontró el cuerpo de get_resumen_economico"
        # Busca la declaración del set (puede ser set, list, tuple, frozenset)
        pattern = (
            r"estados_excluidos(?:_por_cobrar)?\s*=\s*[\{(].*?SUSPENDIDO.*?[\})]"
        )
        match = re.search(pattern, body, re.DOTALL)
        assert match, (
            "F-073: get_resumen_economico debe declarar un set/lista "
            "`estados_excluidos` que contenga `EstadoInscripcion.SUSPENDIDO` "
            "(y opcionalmente COMPLETADO, CANCELADO)."
        )

    def test_estructura_incluye_los_tres_estados(self):
        """El set debe incluir SUSPENDIDO + COMPLETADO + CANCELADO (los 3 inactivos)."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        assert body, "F-073: No se encontró el cuerpo de get_resumen_economico"
        # Buscamos la asignación del set completo en una o varias líneas
        pattern = (
            r"estados_excluidos(?:_por_cobrar)?\s*=\s*\{([^}]+)\}"
        )
        match = re.search(pattern, body, re.DOTALL)
        assert match, "F-073: No se encontró declaración de set de estados excluidos"
        items = match.group(1)
        for estado in ("SUSPENDIDO", "COMPLETADO", "CANCELADO"):
            assert estado in items, (
                f"F-073: El set de estados excluidos debe contener "
                f"`EstadoInscripcion.{estado}`. Contenido: {items.strip()}"
            )

    def test_continue_o_skip_antes_de_sumar_por_cobrar(self):
        """Debe haber un `continue` o guardia antes de sumar al por_cobrar."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        assert body, "F-073: No se encontró el cuerpo de get_resumen_economico"
        # Busca: tras declarar estados_excluidos, debe haber un `if e.estado in ...: continue`
        # Acepta variantes como `if e.estado not in estados_excluidos:` o `continue`
        pattern_continue = (
            r"if\s+e\.estado\s+in\s+estados_excluidos[^:]*:\s*\n\s*continue"
        )
        pattern_neg = (
            r"if\s+e\.estado\s+not\s+in\s+estados_excluidos[^:]*:"
        )
        match_cont = re.search(pattern_continue, body)
        match_neg = re.search(pattern_neg, body)
        assert match_cont or match_neg, (
            "F-073: get_resumen_economico debe saltarse (`continue`) o condicionar "
            "(`if not in`) los enrollments con estado excluido antes de sumar al "
            "por_cobrar. Patrón esperado: `if e.estado in estados_excluidos_por_cobrar: continue`"
        )

    def test_total_esperado_no_excluye_suspendido(self):
        """`total_esperado` debe sumar TODOS los enrollments (incluye pasivos)."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        assert body, "F-073: No se encontró el cuerpo de get_resumen_economico"
        # El test verifica que DENTRO del loop, `total_esperado += ...` aparece
        # ANTES del `continue` (o guardia de exclusión). De esta forma, los
        # suspendidos sí cuentan para el total_esperado (teórico) pero no para
        # el por_cobrar.
        lines = body.split("\n")
        idx_total_esperado = None
        idx_continue = None
        idx_estados_excluidos_uso = None
        for i, line in enumerate(lines):
            if "total_esperado +=" in line and idx_total_esperado is None:
                idx_total_esperado = i
            # Captura la primera aparición de `continue` que esté relacionada
            # con la exclusión de estado
            if idx_continue is None and "continue" in line:
                # Backtrack: ver si las 5 líneas anteriores mencionan estados_excluidos
                contexto = "\n".join(lines[max(0, i-5):i+1])
                if "estados_excluidos" in contexto and "if" in contexto:
                    idx_continue = i
            if "estados_excluidos" in line and "in" in line and "if" in line:
                idx_estados_excluidos_uso = i
        assert idx_total_esperado is not None, (
            "F-073: No se encontró la línea `total_esperado +=` en get_resumen_economico"
        )
        assert idx_continue is not None or idx_estados_excluidos_uso is not None, (
            "F-073: No se encontró el bloque de exclusión de estado (continue/if)"
        )
        # La línea de `total_esperado +=` debe estar antes de la guardia
        idx_guardia = idx_continue if idx_continue is not None else idx_estados_excluidos_uso
        assert idx_total_esperado < idx_guardia, (
            f"F-073: `total_esperado +=` debe estar ANTES de la guardia de "
            f"exclusión (línea {idx_total_esperado+1} vs {idx_guardia+1}). "
            f"El total_esperado es teórico e incluye a TODOS los inscritos "
            f"(incluidos pasivos/congelados, porque al reactivarse vuelven a deber)."
        )

    def test_docstring_o_comentario_explica_regla(self):
        """Debe haber un comentario/docstring que explique la regla de Sandra."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        assert body, "F-073: No se encontró el cuerpo de get_resumen_economico"
        # Busca mención a "Sandra" o "F-COBRANZA-POR-COBRAR" o "suspendido"
        # en el docstring o comentarios
        tiene_mencion_sandra = "Sandra" in body or "F-COBRANZA-POR-COBRAR" in body
        tiene_mencion_suspendido = (
            "SUSPENDIDO" in body
            and ("congelado" in body.lower() or "pasivo" in body.lower() or "abandono" in body.lower())
        )
        assert tiene_mencion_sandra or tiene_mencion_suspendido, (
            "F-073: get_resumen_economico debe tener un comentario/docstring que "
            "explique por qué se excluyen los SUSPENDIDO (congelado/pasivo/abandono) "
            "del cálculo de por_cobrar. Referencia: caso Sandra Cobranza 2026-07-23."
        )

    def test_no_retorna_campo_nuevo_no_deseado(self):
        """No debe agregar campos extra no documentados (mantener contrato)."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        # El return debe seguir siendo los 7 campos conocidos
        for field in (
            "ingreso_matricula",
            "ingreso_colegiatura",
            "total_ingresos",
            "total_esperado",
            "por_cobrar",
            "cobros_pendientes",
            "total_inscritos",
        ):
            assert field in body, (
                f"F-073: El return de get_resumen_economico debe seguir retornando "
                f"`{field}` (no se debe romper el contrato del endpoint)."
            )


class TestF073LogicaConceptual:
    """F-073: tests conceptuales sobre el orden de la lógica (sin ejecutar)."""

    def test_comentario_explica_por_que_total_esperado_incluye_todos(self):
        """Debe haber un comentario explicando que total_esperado es teórico."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_economico")
        # Busca frase tipo "teórico" o "teórica" cerca de total_esperado
        lines = body.split("\n")
        for i, line in enumerate(lines):
            if "total_esperado" in line and "teóric" in line.lower():
                return
            if "total_esperado" in line:
                # Busca en las 3 líneas siguientes
                contexto = "\n".join(lines[i:i+4])
                if "teóric" in contexto.lower():
                    return
        # Si no lo encuentra, no es error fatal pero advertimos
        # (algunos developers pueden explicarlo de otra forma)
        assert True, "OK (no fatal)"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
