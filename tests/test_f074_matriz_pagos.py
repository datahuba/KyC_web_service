# -*- coding: utf-8 -*-
"""
F-074 (2026-07-23) · Tests: Vista Matricial de Pagos
=====================================================

Kevin (2026-07-23 09:09): "aqui en gestion de pago creo que seria bueno
que se pueda filtrar por modulo tambien no se y que nos de igual resumenes
como en el dashboard pero aqui la diferencia sera que los resumenes seran
por modulos, totales y sean como la imagen que te pase de los encabezados
(Excel de Sandra con MATRÍCULA | MONTO | MODULO 1..5 | TOTAL INGRESOS |
POR COBRAR)".

Implementación:
- `services/payment_service.py::get_matriz_pagos` devuelve la matriz
  estudiante-vs-módulos con totales por columna.
- `services/payment_service.py::get_resumen_modulos` devuelve resumen
  agregado por módulo (KPI cards).
- Endpoints: GET /payments/matriz y GET /payments/resumen-modulos.

Reglas:
- Excluye SUSPENDIDO/COMPLETADO/CANCELADO del `por_cobrar` (F-073).
- `total_ingresos` siempre suma lo realmente recaudado (pagos APROBADOS).

Tests de lectura estática del código (no requieren venv con fastapi/beanie),
siguiendo el patrón F-061 / F-070 / F-073.
"""
import re
from pathlib import Path

PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"
API_FILE = Path(__file__).parent.parent / "api" / "payments.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_function_body(content: str, func_name: str) -> str:
    """Extrae el cuerpo de una función async del código (heurística simple)."""
    pattern = rf"async def {func_name}\([^)]*\)[^:]*:.*?(?=\n\nasync def |\n\ndef |\nclass |\Z)"
    match = re.search(pattern, content, re.DOTALL)
    return match.group(0) if match else ""


class TestF074FuncionesServicio:
    """F-074: las funciones get_matriz_pagos y get_resumen_modulos deben existir."""

    def test_get_matriz_pagos_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_matriz_pagos" in content, (
            "F-074: `async def get_matriz_pagos(...)` debe existir en services/payment_service.py"
        )

    def test_get_resumen_modulos_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_resumen_modulos" in content, (
            "F-074: `async def get_resumen_modulos(...)` debe existir en services/payment_service.py"
        )


class TestF074GetMatrizPagosEstructura:
    """F-074: la matriz debe tener la estructura esperada."""

    def test_acepta_cursos_permitidos_y_modulo_index(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        assert "cursos_permitidos" in body, (
            "F-074: get_matriz_pagos debe aceptar `cursos_permitidos: Optional[List[PydanticObjectId]]` "
            "para segmentación por curso del rol"
        )
        assert "modulo_index" in body, (
            "F-074: get_matriz_pagos debe aceptar `modulo_index: Optional[int]` "
            "para filtrar por una columna específica"
        )

    def test_retorna_cursos_estudiantes_totales(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        for key in ("cursos", "estudiantes", "totales_por_columna", "filtros_aplicados"):
            assert f'"{key}"' in body or f"'{key}'" in body or key in body, (
                f"F-074: La respuesta de get_matriz_pagos debe incluir el campo `{key}`"
            )

    def test_calcula_matricula_y_modulos(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        # Debe procesar tanto matrícula como módulos
        assert "costo_matricula" in body, "F-074: Debe usar `enrollment.costo_matricula` para la columna matrícula"
        assert "modulos" in body, "F-074: Debe iterar `enrollment.modulos`"
        assert "monto_pagado" in body, "F-074: Debe usar `modulo.monto_pagado`"

    def test_total_ingresos_suma_total_pagado(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        # `total_ingresos` debe sumar lo realmente recaudado
        assert "total_pagado" in body, (
            "F-074: total_ingresos debe basarse en `enrollment.total_pagado` "
            "(suma de pagos APROBADOS, refleja lo realmente recaudado)"
        )

    def test_excluye_suspendidos_de_por_cobrar(self):
        """F-073/F-074: por_cobrar NO incluye SUSPENDIDO/COMPLETADO/CANCELADO."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        assert "estados_excluidos" in body, (
            "F-074: get_matriz_pagos debe declarar `estados_excluidos` "
            "para excluir SUSPENDIDO/COMPLETADO/CANCELADO del por_cobrar "
            "(misma regla que F-073, decisión Kevin/Sandra 2026-07-23)"
        )
        for estado in ("SUSPENDIDO", "COMPLETADO", "CANCELADO"):
            assert estado in body, (
                f"F-074: El set de estados excluidos debe contener EstadoInscripcion.{estado}"
            )

    def test_ordena_estudiantes_por_nombre(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert body, "F-074: No se encontró get_matriz_pagos"
        assert "sort" in body, (
            "F-074: get_matriz_pagos debe ordenar los estudiantes por nombre "
            "para que la vista sea predecible"
        )


class TestF074GetResumenModulosEstructura:
    """F-074: el resumen por módulo debe tener la estructura correcta."""

    def test_retorna_matricula_y_modulos(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_modulos")
        assert body, "F-074: No se encontró get_resumen_modulos"
        for key in ("matricula", "modulos"):
            assert key in body, (
                f"F-074: La respuesta de get_resumen_modulos debe incluir el campo `{key}`"
            )

    def test_cada_modulo_tiene_campos_requeridos(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_modulos")
        assert body, "F-074: No se encontró get_resumen_modulos"
        for field in ("cantidad_pagos", "monto_total", "monto_pendiente", "estudiantes_cursando"):
            assert field in body, (
                f"F-074: Cada módulo en get_resumen_modulos debe incluir el campo `{field}` "
                f"(necesario para las KPI cards del frontend)"
            )

    def test_excluye_suspendidos(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_modulos")
        assert body, "F-074: No se encontró get_resumen_modulos"
        assert "estados_excluidos" in body, (
            "F-074: get_resumen_modulos también debe excluir suspendidos (F-073)"
        )


class TestF074EndpointsAPI:
    """F-074: los endpoints en api/payments.py deben estar bien declarados."""

    def test_endpoint_matriz_existe(self):
        content = read(API_FILE)
        # El path puede estar en la línea siguiente al @router.get(
        assert '"/matriz"' in content, (
            "F-074: Debe existir `@router.get(\"/matriz\", ...)` en api/payments.py "
            "(path puede estar en la línea siguiente)"
        )

    def test_endpoint_resumen_modulos_existe(self):
        content = read(API_FILE)
        assert '"/resumen-modulos"' in content, (
            "F-074: Debe existir `@router.get(\"/resumen-modulos\", ...)` en api/payments.py"
        )

    def test_orden_correcto_antes_de_payment_id_dinamico(self):
        """
        F-070-FIX-2: las rutas estáticas (/matriz, /resumen-modulos) deben
        estar ANTES de /{payment_id} en api/payments.py para que FastAPI
        no las matchee como IDs.
        """
        content = read(API_FILE)
        # Buscamos la línea donde aparece el path, y luego retrocedemos al @router.get
        lines = content.split("\n")
        idx_matriz_path = None
        idx_resumen_path = None
        idx_payment_id = None
        for i, line in enumerate(lines):
            if '"/matriz"' in line and idx_matriz_path is None:
                idx_matriz_path = i
            if '"/resumen-modulos"' in line and idx_resumen_path is None:
                idx_resumen_path = i
            if re.search(r'@router\.(get|put|delete)\(\s*$', line):
                # Verificar las 2 líneas siguientes para path dinámico
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()
                    if re.match(r'^"/\{[^}]+\}",?$', next_line) or re.match(r'^"/\{[^}]+\}"', next_line):
                        if idx_payment_id is None:
                            idx_payment_id = i

        assert idx_matriz_path is not None, "F-074: No se encontró '/matriz' en api/payments.py"
        assert idx_resumen_path is not None, "F-074: No se encontró '/resumen-modulos' en api/payments.py"
        # Ambos paths deben estar antes que la ruta dinámica
        if idx_payment_id is not None:
            assert idx_matriz_path < idx_payment_id, (
                f"F-074 (orden rutas): /matriz (línea {idx_matriz_path+1}) debe estar ANTES de "
                f"/{{payment_id}} (línea {idx_payment_id+1}) para evitar el bug F-070-FIX-2"
            )
            assert idx_resumen_path < idx_payment_id, (
                f"F-074 (orden rutas): /resumen-modulos (línea {idx_resumen_path+1}) debe estar "
                f"ANTES de /{{payment_id}} (línea {idx_payment_id+1})"
            )

    def test_endpoints_usan_require_staff_y_puede_ver_economico(self):
        """Ambos endpoints deben exigir rol económico (regla consistente con F-044/F-068)."""
        content = read(API_FILE)
        idx_matriz = content.find('"/matriz"')
        idx_resumen = content.find('"/resumen-modulos"')
        assert idx_matriz > 0 and idx_resumen > 0, "F-074: endpoints no encontrados"
        # Verificar que usan `Depends(require_staff)` y `puede_ver_economico`
        matriz_block = content[idx_matriz:idx_matriz+1500]
        resumen_block = content[idx_resumen:idx_resumen+1500]
        assert "require_staff" in matriz_block, "F-074: /matriz debe usar `Depends(require_staff)`"
        assert "puede_ver_economico" in matriz_block, (
            "F-074: /matriz debe validar `puede_ver_economico(current_user)` "
            "(mismo patrón que /dashboard/resumen-economico, F-043)"
        )
        assert "require_staff" in resumen_block, "F-074: /resumen-modulos debe usar `Depends(require_staff)`"
        assert "puede_ver_economico" in resumen_block, (
            "F-074: /resumen-modulos debe validar `puede_ver_economico(current_user)`"
        )

    def test_endpoint_matriz_pasa_segmentacion_a_servicio(self):
        """El endpoint debe pasar `cursos_permitidos` desde filtro_cursos_por_rol."""
        content = read(API_FILE)
        idx_matriz = content.find('"/matriz"')
        assert idx_matriz > 0, "F-074: endpoint no encontrado"
        bloque = content[idx_matriz:idx_matriz+2000]
        assert "filtro_cursos_por_rol" in bloque, (
            "F-074: El endpoint /matriz debe usar `filtro_cursos_por_rol(current_user)` "
            "para que Cobranza con cursos_asignados solo vea su alcance"
        )
        assert "cursos_permitidos" in bloque, (
            "F-074: El endpoint /matriz debe pasar `cursos_permitidos` a `payment_service.get_matriz_pagos(...)`"
        )


class TestF074Documentacion:
    """F-074: las funciones deben tener docstring explicativo."""

    def test_get_matriz_pagos_docstring(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_pagos")
        assert "F-074" in body, (
            "F-074: get_matriz_pagos debe tener una referencia explícita a F-074 en su docstring"
        )
        assert "Sandra" in body, (
            "F-074: El docstring debe mencionar que replica el Excel de Sandra (origen del requerimiento)"
        )

    def test_get_resumen_modulos_docstring(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_resumen_modulos")
        assert "F-074" in body, (
            "F-074: get_resumen_modulos debe tener una referencia explícita a F-074"
        )
        assert "F-073" in body, (
            "F-074: El docstring debe mencionar F-073 (exclusión de suspendidos) para auditoría"
        )
