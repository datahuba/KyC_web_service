# -*- coding: utf-8 -*-
"""
F-074-FIX-4 (2026-07-23) · Tests: Vista Matricial incluye becas/descuentos
==========================================================================

Regla de Kevin (2026-07-23): "en el conteo de por cobrar debe tomar en cuenta
los descuentos que tienen algunos estudiantes... no veo el conteo del que pago
todo eso lo estas contando?".

Implementación:
- `get_matriz_pagos` ahora retorna por cada estudiante:
  - `beca_porcentaje`: % de descuento (curso + personal)
  - `ahorro`: Bs ahorrados vs costo sin descuento del curso
  - `costo_sin_descuento`: Bs que pagaría sin descuento
  - `pago_todo`: True si pagó matrícula + todos los módulos
- `totales_por_columna` ahora incluye:
  - `estudiantes_pagaron_todo`: conteo global
  - `estudiantes_con_beca`: cuántos tienen algún descuento
  - `ahorro_total_por_descuentos`: suma total de Bs ahorrados
"""
import re
from pathlib import Path

PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_function_body(content: str, func_name: str) -> str:
    pattern = rf"async def {func_name}\([^)]*\)[^:]*:.*?(?=\n\nasync def |\n\ndef |\nclass |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(0) if match else ""


class TestF074FIX4BecasEstudiante:
    """F-074-FIX-4: el endpoint /payments/matriz debe incluir info de becas por estudiante."""

    def test_beca_porcentaje_en_response(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074-FIX-4: No se encontró get_matriz_pagos"
        assert "beca_porcentaje" in body, (
            "F-074-FIX-4: get_matriz_pagos debe incluir `beca_porcentaje` por estudiante "
            "(regla Kevin: 'en el conteo de por cobrar debe tomar en cuenta los descuentos')"
        )

    def test_ahorro_en_response(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074-FIX-4: No se encontró get_matriz_pagos"
        assert "ahorro" in body, (
            "F-074-FIX-4: get_matriz_pagos debe incluir `ahorro` por estudiante "
            "(Bs ahorrados vs costo sin descuento del curso)"
        )

    def test_costo_sin_descuento_en_response(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "costo_sin_descuento" in body, (
            "F-074-FIX-4: get_matriz_pagos debe incluir `costo_sin_descuento` para auditoría"
        )

    def test_pago_todo_en_response(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "pago_todo" in body, (
            "F-074-FIX-4: get_matriz_pagos debe incluir `pago_todo` por estudiante "
            "(regla Kevin: 'no veo el conteo del que pago todo eso lo estas contando?')"
        )


class TestF074FIX4BecasTotales:
    """F-074-FIX-4: el resumen debe incluir contadores agregados."""

    def test_estudiantes_pagaron_todo(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "estudiantes_pagaron_todo" in body, (
            "F-074-FIX-4: totales_por_columna debe incluir `estudiantes_pagaron_todo` "
            "(cuántos pagaron matrícula + todos los módulos)"
        )

    def test_estudiantes_con_beca(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "estudiantes_con_beca" in body, (
            "F-074-FIX-4: totales_por_columna debe incluir `estudiantes_con_beca` "
            "(cuántos tienen algún descuento aplicado)"
        )

    def test_ahorro_total_por_descuentos(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "ahorro_total_por_descuentos" in body, (
            "F-074-FIX-4: totales_por_columna debe incluir `ahorro_total_por_descuentos` "
            "(suma total de Bs ahorrados por descuentos)"
        )


class TestF074FIX4LogicaCalculo:
    """F-074-FIX-4: la lógica de cálculo de beca/ahorro debe estar bien."""

    def test_calcula_desc_curso_y_personal(self):
        """Debe sumar descuento_curso_aplicado + descuento_personalizado."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "descuento_curso_aplicado" in body, (
            "F-074-FIX-4: debe leer `enrollment.descuento_curso_aplicado`"
        )
        assert "descuento_personalizado" in body, (
            "F-074-FIX-4: debe leer `enrollment.descuento_personalizado`"
        )

    def test_ahorro_calculado_vs_costo_sin_descuento(self):
        """El ahorro = costo_sin_descuento - total_a_pagar."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        # Debe haber una operación de resta o max(0, ...)
        assert "costo_total_sin_desc" in body, (
            "F-074-FIX-4: debe calcular el costo total sin descuento "
            "(costo_matricula + suma de módulos del CURSO sin descuento)"
        )

    def test_curso_modulos_usados_para_costo_sin_descuento(self):
        """Para calcular el costo sin descuento, usa los módulos del CURSO (no del enrollment)."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        # Busca "curso.modulos" o similar
        pattern = r"curso\.modulos|curso\.get\(.{0,5}modulos"
        assert re.search(pattern, body), (
            "F-074-FIX-4: debe usar los módulos del CURSO (no del enrollment) para "
            "calcular el costo sin descuento — el enrollment tiene el costo YA con "
            "descuento aplicado en cada módulo"
        )

    def test_pago_todo_es_matricula_y_modulos(self):
        """`pago_todo = matricula_pagada AND todos los modulos pagados."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "matricula_pagada" in body, (
            "F-074-FIX-4: `pago_todo` debe chequear `enrollment.matricula_pagada`"
        )
        assert "estado" in body and "Pagado" in body, (
            "F-074-FIX-4: `pago_todo` debe chequear que cada módulo esté en estado 'Pagado'"
        )
        assert "all(" in body, (
            "F-074-FIX-4: usar `all(...)` para verificar que TODOS los módulos estén pagados"
        )


class TestF074FIX4Documentacion:
    """F-074-FIX-4: el código debe tener referencia a Kevin y la fecha."""

    def test_referencia_kevin_en_codigo(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "F-074-FIX-4" in body, (
            "F-074-FIX-4: el código debe tener referencia a F-074-FIX-4 en comentarios/docstring"
        )

    def test_referencia_fecha(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "2026-07-23" in body, (
            "F-074-FIX-4: debe tener la fecha 2026-07-23 para auditoría"
        )
