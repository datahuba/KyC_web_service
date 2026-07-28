# -*- coding: utf-8 -*-
"""
F-087 (2026-07-28) · Tests: Vista "Por Pago" en Gestión de Pagos
================================================================

Kevin (2026-07-28 18:31): "que bueno que los encontraste [pagos con
excesos como 12 Bs], el punto es que esos pagos por ejemplo lo reflejemos
en la matriz, en gestion de pagos tenemos lista y matriz en la matriz
seria bueno que se vean reflejados los pagos asi como llegaron, o sea
quiero que tengamos 3 ventanas, ya tenemos dos una que es lista, la
otra matriz y una tercera pero que sea por pago asi como la matriz
pero en este caso con los pagos que cada estudiante tenga en vez de
totales por modulo sea pagos que subio su usuario o el encargado pero
a dirigido a ese usuario".

Implementación:
- `models/payment.py`: campo `subido_por: Optional[str]` (None para pagos
  antiguos, "estudiante" | "encargado" para nuevos).
- `services/payment_service.py::get_matriz_por_pago`: nueva función que
  devuelve 1 fila por cada pago individual (no agrupado por módulo).
  Si el concepto cubre varios módulos ("Pago Módulos 1, 2"), se generan
  N filas prorrateando el monto. Si el concepto no tiene módulo
  identificable, se emite 1 fila con modulo_index=None.
- `api/payments.py::get_matriz_por_pago_endpoint`: nuevo endpoint
  GET /payments/matriz/por-pago con filtros (curso, módulo, estado,
  subido_por) y paginación.
- En `create_payment` y `upload_by_encargado` se setea subido_por.

Reglas:
- Permiso: `puede_ver_economico` (mismo que la matriz).
- Ordena por fecha_subida DESC.
- Pago multi-módulo → N filas (es SOLO vista, BD tiene 1 documento).

Tests de lectura estática del código (no requieren venv con fastapi/beanie),
siguiendo el patrón F-070 / F-073 / F-074 / F-085.
"""
import re
from pathlib import Path

PAYMENT_MODEL_FILE = Path(__file__).parent.parent / "models" / "payment.py"
PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"
API_FILE = Path(__file__).parent.parent / "api" / "payments.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def get_function_body(content: str, func_name: str) -> str:
    """Extrae el cuerpo de una función async/regular del código (heurística simple)."""
    pattern = rf"^(?:async\s+)?def\s+{func_name}\b.*?(?=^\s*(?:async\s+)?def\s+|^\s*class\s+|\Z)"
    match = re.search(pattern, content, re.DOTALL | re.MULTILINE)
    return match.group(0) if match else ""


# ============================================================================
# Tests del modelo
# ============================================================================
class TestF087ModeloPayment:
    """F-087: el modelo Payment debe tener el campo subido_por."""

    def test_campo_subido_por_existe(self):
        content = read(PAYMENT_MODEL_FILE)
        assert "subido_por: Optional[str]" in content, (
            "F-087: `subido_por: Optional[str]` debe existir en models/payment.py"
        )

    def test_campo_subido_por_default_none(self):
        content = read(PAYMENT_MODEL_FILE)
        # Verifica que el default es None
        match = re.search(r"subido_por:\s*Optional\[str\]\s*=\s*Field\(\s*None", content)
        assert match, "F-087: `subido_por` debe tener default None"


# ============================================================================
# Tests del servicio
# ============================================================================
class TestF087FuncionesServicio:
    """F-087: las funciones de la vista Por Pago deben existir."""

    def test_get_matriz_por_pago_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_matriz_por_pago" in content, (
            "F-087: `async def get_matriz_por_pago(...)` debe existir en services/payment_service.py"
        )

    def test_parse_modulos_de_concepto_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "def _parse_modulos_de_concepto" in content, (
            "F-087: `def _parse_modulos_de_concepto` debe existir en services/payment_service.py"
        )

    def test_pago_to_fila_existe(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "def _pago_to_fila" in content, (
            "F-087: `def _pago_to_fila` debe existir en services/payment_service.py"
        )

    def test_get_matriz_por_pago_acepta_filtros(self):
        """La función debe aceptar todos los filtros del endpoint."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_por_pago")
        for param in ["cursos_permitidos", "curso_id", "modulo_index",
                      "estado_pago", "subido_por", "page", "per_page"]:
            assert param in body, f"F-087: `get_matriz_por_pago` debe aceptar param `{param}`"

    def test_get_matriz_por_pago_parsea_conceptos_multiples(self):
        """Si el concepto dice 'Pago Módulos 1, 2' debe splitearse en 2 filas."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_por_pago")
        # Verifica que itera sobre los modulos del pago
        assert "modulos_del_pago" in body, (
            "F-087: `get_matriz_por_pago` debe iterar sobre `modulos_del_pago`"
        )
        assert "per_modulo" in body, (
            "F-087: debe prorratear el monto entre los módulos"
        )

    def test_parse_matricula_devuelve_indice_0(self):
        """Si el concepto es 'Matrícula' debe devolver [0]."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "_parse_modulos_de_concepto")
        assert "MATRIC" in body, "F-087: debe detectar 'Matrícula' en el concepto"
        assert "return [0]" in body, "F-087: 'Matrícula' debe devolver [0]"

    def test_parse_modulo_simple_devuelve_indice(self):
        """Si el concepto es 'Pago Módulo 1' debe devolver [1]."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "_parse_modulos_de_concepto")
        assert "re.findall" in body, "F-087: debe usar regex para parsear números"
        assert "1 <= int" in body, "F-087: debe filtrar módulos válidos (1-9)"

    def test_respuesta_incluye_resumen(self):
        """La respuesta debe incluir un resumen con totales por estado."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_por_pago")
        for campo in ["total_aprobado", "total_anulado", "total_pendiente",
                      "total_rechazado", "pagos_con_comprobante"]:
            assert campo in body, f"F-087: la respuesta debe incluir `{campo}` en el resumen"

    def test_paginacion_en_respuesta(self):
        """La respuesta debe incluir total, page, per_page, total_pages."""
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "get_matriz_por_pago")
        for campo in ["total", "page", "per_page", "total_pages"]:
            assert campo in body, f"F-087: la respuesta debe incluir `{campo}`"


# ============================================================================
# Tests del endpoint
# ============================================================================
class TestF087Endpoint:
    """F-087: el endpoint GET /payments/matriz/por-pago debe existir."""

    def test_endpoint_por_pago_existe(self):
        content = read(API_FILE)
        assert '"/matriz/por-pago"' in content, (
            "F-087: debe existir el endpoint `GET /payments/matriz/por-pago`"
        )

    def test_endpoint_usa_puede_ver_economico(self):
        """El endpoint debe chequear permiso económico."""
        content = read(API_FILE)
        # Buscar la función del endpoint y verificar que chequea permiso
        match = re.search(
            r'async def get_matriz_por_pago_endpoint.*?(?=\n\n@router|\nclass |\Z)',
            content, re.DOTALL
        )
        assert match, "F-087: `get_matriz_por_pago_endpoint` debe existir"
        body = match.group(0)
        assert "puede_ver_economico" in body, (
            "F-087: el endpoint debe validar `puede_ver_economico`"
        )

    def test_endpoint_acepta_todos_los_filtros(self):
        """El endpoint debe aceptar todos los filtros via Query params."""
        content = read(API_FILE)
        match = re.search(
            r'async def get_matriz_por_pago_endpoint.*?(?=\n\n@router|\nclass |\Z)',
            content, re.DOTALL
        )
        assert match, "F-087: `get_matriz_por_pago_endpoint` debe existir"
        body = match.group(0)
        for param in ["curso_id", "modulo_index", "estado_pago",
                      "subido_por", "page", "per_page"]:
            assert param in body, f"F-087: el endpoint debe aceptar param `{param}`"

    def test_endpoint_antes_de_matriz_normal(self):
        """F-070-FIX-2: rutas estáticas antes de dinámicas."""
        content = read(API_FILE)
        idx_por_pago = content.find('"/matriz/por-pago"')
        idx_matriz_normal = content.find('"/matriz"')
        idx_get_id = content.find('"/{id}"')
        # /matriz/por-pago debe estar ANTES de /{id} (regla de orden de FastAPI)
        assert idx_por_pago < idx_get_id, (
            "F-087: /matriz/por-pago debe declararse ANTES de /{id} "
            "(regla FastAPI: rutas estáticas antes de dinámicas)"
        )


# ============================================================================
# Tests de integración con el flujo de creación
# ============================================================================
class TestF087SubidoPorEnCreatePayment:
    """F-087: create_payment debe aceptar y persistir el campo subido_por."""

    def test_create_payment_param_subido_por(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "create_payment")
        assert "subido_por" in body, (
            "F-087: `create_payment` debe aceptar param `subido_por`"
        )

    def test_create_payment_asigna_subido_por_al_payment(self):
        content = read(PAYMENT_SERVICE_FILE)
        body = get_function_body(content, "create_payment")
        # Verifica que el campo se asigna al construir el Payment
        assert re.search(r"subido_por\s*=\s*subido_por", body), (
            "F-087: `create_payment` debe asignar `subido_por=subido_por` al Payment"
        )

    def test_endpoint_estudiante_pasa_estudiante(self):
        """El endpoint que crea pagos para estudiantes debe pasar subido_por='estudiante'."""
        content = read(API_FILE)
        # En el create_payment endpoint, en la rama del estudiante debe estar
        # subido_por="estudiante"
        match = re.search(
            r"payment = await payment_service\.create_payment\(\s*"
            r"payment_in=payment_in,\s*"
            r"student_id=current_user\.id,\s*"
            r"auto_approve=False[^)]*\)",
            content, re.DOTALL
        )
        assert match, "F-087: la rama del estudiante debe estar presente"
        # Verifica que incluye subido_por
        assert "subido_por" in match.group(0), (
            "F-087: la rama del estudiante debe setear subido_por='estudiante'"
        )

    def test_endpoint_by_staff_pasa_encargado(self):
        """El endpoint by-staff debe pasar subido_por='encargado'."""
        content = read(API_FILE)
        # Buscamos student_oid= y verificamos que en las siguientes ~10 líneas
        # aparece subido_por="encargado" antes del cierre de la función.
        match = re.search(
            r"student_id=student_oid,(.*?)(?=^\s{0,8}\)|^\s{0,8}# F-COBRANZA-014|^\s{0,8}\Z)",
            content, re.DOTALL | re.MULTILINE
        )
        assert match, "F-087: la llamada by-staff debe estar presente"
        assert 'subido_por="encargado"' in match.group(0), (
            "F-087: by-staff debe setear subido_por='encargado'"
        )

    def test_upload_by_encargado_setea_subido_por(self):
        """El endpoint /payments/{id}/upload-by-encargado debe persistir subido_por='encargado'."""
        content = read(API_FILE)
        # Verificamos que dentro de upload_comprobante_by_encargado se persista subido_por
        body = get_function_body(content, "upload_comprobante_by_encargado")
        assert body, "F-087: debe existir la función upload_comprobante_by_encargado"
        assert '"subido_por"' in body, (
            "F-087: upload-by-encargado debe persistir el campo subido_por"
        )
        assert '"encargado"' in body, (
            "F-087: upload-by-encargado debe setear subido_por='encargado'"
        )


# ============================================================================
# Tests de regresión: que no se rompió nada
# ============================================================================
class TestF087Regresion:
    """F-087: las features anteriores no deben haberse roto."""

    def test_get_matriz_pagos_sigue_existente(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_matriz_pagos" in content, (
            "F-074: `get_matriz_pagos` no debe haberse roto"
        )

    def test_endpoint_matriz_sigue_existente(self):
        content = read(API_FILE)
        assert '"/matriz"' in content, (
            "F-074: el endpoint /matriz no debe haberse roto"
        )

    def test_get_resumen_modulos_sigue_existente(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "async def get_resumen_modulos" in content, (
            "F-074: `get_resumen_modulos` no debe haberse roto"
        )

    def test_modelo_payment_todavia_tiene_campos_originales(self):
        content = read(PAYMENT_MODEL_FILE)
        # Campos clave que no deben haberse perdido
        for campo in ["verificado_por", "comprobante_url", "estado_pago",
                      "monto_comprobante", "fecha_subida"]:
            assert campo in content, f"F-087: el modelo debe seguir teniendo `{campo}`"
