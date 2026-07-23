# -*- coding: utf-8 -*-
"""
F-070 (2026-07-22) · Tests para Validación de Notas
===================================================

Verifica los nuevos endpoints:
- GET  /enrollments/notas-pendientes
- POST /enrollments/notas/bulk-validar
- PUT  /enrollments/{id}/modulos/{index}/nota (editar nota validada)

Surge del bug urgente: Miguel (socio de Kevin) tenía 51 notas en
pendiente_validacion y no había forma rápida de aprobarlas. Aquí se
garantiza que el endpoint:
1. Lista correctamente las notas pendientes con filtros
2. Aprueba en bulk respetando el flujo de validación
3. Edita notas validadas con auditoría
"""
import os
import re
import pytest
from pathlib import Path

API_FILE = Path(__file__).parent.parent / "api" / "enrollments.py"
SERVICE_FILE = Path(__file__).parent.parent / "services" / "enrollment_service.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF070GradeValidationEndpoint:
    """F-070: verifica que los endpoints existen y tienen la forma correcta."""

    def test_listar_notas_pendientes_endpoint_existe(self):
        """GET /enrollments/notas-pendientes debe existir."""
        content = read(API_FILE)
        match = re.search(
            r'@router\.get\(\s*[\'"]/notas-pendientes[\'"]\s*,',
            content,
        )
        assert match, (
            "F-070: Falta el endpoint GET /enrollments/notas-pendientes. "
            "Es la pieza clave del bug urgente de Miguel."
        )

    def test_bulk_validar_endpoint_existe(self):
        """POST /enrollments/notas/bulk-validar debe existir."""
        content = read(API_FILE)
        match = re.search(
            r'@router\.post\(\s*[\'"]/notas/bulk-validar[\'"]\s*,',
            content,
        )
        assert match, (
            "F-070: Falta el endpoint POST /enrollments/notas/bulk-validar. "
            "Permite aprobar muchas notas en una sola llamada."
        )

    def test_editar_nota_validada_endpoint_existe(self):
        """PUT /enrollments/{id}/modulos/{index}/nota debe existir."""
        content = read(API_FILE)
        match = re.search(
            r'@router\.put\(\s*[\'"]/\{id\}/modulos/\{index\}/nota[\'"]\s*,',
            content,
        )
        assert match, (
            "F-070: Falta el endpoint PUT /enrollments/{id}/modulos/{index}/nota. "
            "Permite a CPD/Superadmin editar notas ya validadas con auditoría."
        )

    def test_listar_notas_pendientes_usa_require_cpd(self):
        """El endpoint debe estar protegido con require_cpd (CPD/Admin/Superadmin)."""
        content = read(API_FILE)
        # Captura el cuerpo de la función (incluyendo docstring multilinea) y busca el require_cpd
        match = re.search(
            r"async def listar_notas_pendientes\([\s\S]*?Depends\(require_cpd\)",
            content,
        )
        assert match, (
            "F-070: listar_notas_pendientes debe usar Depends(require_cpd) "
            "para que solo CPD/Admin/Superadmin puedan listar."
        )

    def test_bulk_validar_usa_require_cpd(self):
        """El bulk-validar debe estar protegido con require_cpd."""
        content = read(API_FILE)
        match = re.search(
            r"async def bulk_validar_notas\([\s\S]*?Depends\(require_cpd\)",
            content,
        )
        assert match, (
            "F-070: bulk_validar_notas debe usar Depends(require_cpd)."
        )

    def test_editar_nota_validada_usa_require_cpd(self):
        """editar_nota_validada debe estar protegido con require_cpd."""
        content = read(API_FILE)
        match = re.search(
            r"async def editar_nota_validada\([\s\S]*?Depends\(require_cpd\)",
            content,
        )
        assert match, (
            "F-070: editar_nota_validada debe usar Depends(require_cpd)."
        )


class TestF070Schemas:
    """F-070: verifica que los schemas Pydantic están bien definidos."""

    def test_nota_pendiente_item_tiene_campos_clave(self):
        """NotaPendienteItem debe incluir los campos clave para la UI."""
        content = read(API_FILE)
        # buscar la definición de la clase
        match = re.search(
            r"class NotaPendienteItem\(BaseModel\):\s*\n\s*\"\"\".*?\"\"\".*?(?=\n\nclass|\n# ====)",
            content,
            re.DOTALL,
        )
        assert match, "F-070: Falta la clase NotaPendienteItem."
        block = match.group(0)
        for field in ["enrollment_id", "estudiante_nombre", "curso_codigo", "modulo_nombre", "nota_borrador"]:
            assert field in block, f"F-070: NotaPendienteItem debe tener el campo '{field}'."

    def test_bulk_validar_request_limita_items(self):
        """BulkValidarRequest debe tener min_length y max_length razonables."""
        content = read(API_FILE)
        match = re.search(
            r"class BulkValidarRequest\(BaseModel\):[\s\S]*?items: List\[BulkValidarItem\][^\n]*",
            content,
        )
        assert match, "F-070: BulkValidarRequest no encontrado."
        line = match.group(0)
        assert "min_length=1" in line, "F-070: BulkValidarRequest debe rechazar requests vacías."
        assert "max_length=200" in line, "F-070: BulkValidarRequest debe limitar a 200 items por request."

    def test_editar_nota_request_valida_rango(self):
        """EditarNotaRequest.nota debe estar entre 0 y 100."""
        content = read(API_FILE)
        match = re.search(
            r"class EditarNotaRequest\(BaseModel\):[\s\S]*?nota: float[^\n]*",
            content,
        )
        assert match, "F-070: EditarNotaRequest no encontrado."
        line = match.group(0)
        assert "ge=0" in line and "le=100" in line, (
            "F-070: EditarNotaRequest.nota debe estar en rango [0, 100]."
        )


class TestF070BusinessLogic:
    """F-070: reglas de negocio críticas."""

    def test_bulk_validar_rechaza_si_no_esta_pendiente(self):
        """bulk_validar debe rechazar items que NO estén en pendiente_validacion."""
        content = read(API_FILE)
        match = re.search(
            r"async def bulk_validar_notas\([\s\S]*?return BulkValidarResponse",
            content,
        )
        assert match, "F-070: función bulk_validar_notas no encontrada."
        block = match.group(0)
        assert "pendiente_validacion" in block, (
            "F-070: bulk_validar debe verificar estado 'pendiente_validacion' "
            "antes de aprobar."
        )

    def test_editar_nota_rechaza_si_esta_pendiente(self):
        """editar_nota_validada debe rechazar editar notas en pendiente_validacion."""
        content = read(API_FILE)
        # Capturar todo el cuerpo de la función hasta el siguiente 'return await'
        match = re.search(
            r"async def editar_nota_validada\([\s\S]*?return await enrollment_service",
            content,
        )
        assert match, "F-070: función editar_nota_validada no encontrada."
        block = match.group(0)
        assert "pendiente_validacion" in block, (
            "F-070: editar_nota_validada debe rechazar notas en estado "
            "'pendiente_validacion' (usar el flujo validar/rechazar primero)."
        )

    def test_editar_nota_recalcula_promedio(self):
        """editar_nota_validada debe recalcular nota_final."""
        content = read(API_FILE)
        match = re.search(
            r"async def editar_nota_validada\([\s\S]*?return await enrollment_service",
            content,
        )
        assert match, "F-070: función editar_nota_validada no encontrada."
        block = match.group(0)
        assert "nota_final" in block and "round" in block, (
            "F-070: editar_nota_validada debe recalcular nota_final "
            "con el nuevo promedio."
        )

    def test_editar_nota_actualiza_estado_academico(self):
        """editar_nota_validada debe actualizar estado_academico (Aprobado/Reprobado)."""
        content = read(API_FILE)
        match = re.search(
            r"async def editar_nota_validada\([\s\S]*?return await enrollment_service",
            content,
        )
        block = match.group(0)
        assert '"Aprobado"' in block and '"Reprobado"' in block, (
            "F-070: editar_nota_validada debe actualizar estado_academico "
            "según la nueva nota (>=51 Aprobado, <51 Reprobado)."
        )

    def test_editar_nota_notifica_estudiante(self):
        """editar_nota_validada debe notificar al estudiante del cambio."""
        content = read(API_FILE)
        match = re.search(
            r"async def editar_nota_validada\([\s\S]*?return await enrollment_service",
            content,
        )
        block = match.group(0)
        assert "create_notification" in block, (
            "F-070: editar_nota_validada debe notificar al estudiante "
            "que su nota fue ajustada."
        )
        assert "Nota ajustada por CPD" in block, (
            "F-070: el título de la notificación debe ser claro."
        )


class TestF070PageRoute:
    """F-070: verifica que la página del sidebar existe en el frontend."""

    def test_pagina_grade_validation_existe(self):
        page_file = (
            Path(__file__).parent.parent.parent
            / "kyc-client/src/routes/app/admin/grade-validation/+page.svelte"
        )
        assert page_file.exists(), (
            f"F-070: Falta la página {page_file}. "
            "Es donde CPD/Superadmin ven y gestionan las notas pendientes."
        )

    def test_servicio_frontend_existe(self):
        service_file = (
            Path(__file__).parent.parent.parent
            / "kyc-client/src/lib/services/grade-validation.service.ts"
        )
        assert service_file.exists(), (
            f"F-070: Falta el servicio frontend {service_file}."
        )

    def test_interfaz_frontend_existe(self):
        interface_file = (
            Path(__file__).parent.parent.parent
            / "kyc-client/src/lib/interfaces/grade-validation.interface.ts"
        )
        assert interface_file.exists(), (
            f"F-070: Falta la interfaz frontend {interface_file}."
        )

    def test_sidebar_tiene_link_grade_validation(self):
        sidebar_file = (
            Path(__file__).parent.parent.parent
            / "kyc-client/src/lib/components/layout/Sidebar.svelte"
        )
        content = read(sidebar_file)
        assert "/app/admin/grade-validation" in content, (
            "F-070: El Sidebar debe tener el link /app/admin/grade-validation."
        )
        assert "Validación de Notas" in content, (
            "F-070: El Sidebar debe mostrar 'Validación de Notas' como texto."
        )
        # debe estar restringido a cpd/admin/superadmin
        match = re.search(
            r"href:\s*'/app/admin/grade-validation'[^}]*roles:\s*\[([^\]]+)\]",
            content,
        )
        assert match, "F-070: El link del Sidebar debe tener un array 'roles'."
        roles = match.group(1)
        assert "cpd" in roles, "F-070: El link debe incluir rol 'cpd'."
        assert "admin" in roles, "F-070: El link debe incluir rol 'admin'."
        assert "superadmin" in roles, "F-070: El link debe incluir rol 'superadmin'."


class TestF070BulkApproved:
    """F-070: bulk-validar debe llamar a la lógica existente de validación."""

    def test_bulk_validar_reusa_validar_nota_borrador(self):
        """bulk_validar debe reutilizar enrollment_service.validar_nota_borrador."""
        content = read(API_FILE)
        match = re.search(
            r"async def bulk_validar_notas\([\s\S]*?return BulkValidarResponse",
            content,
        )
        block = match.group(0)
        assert "validar_nota_borrador" in block, (
            "F-070: bulk_validar_notas debe reutilizar "
            "enrollment_service.validar_nota_borrador para mantener consistencia."
        )

    def test_bulk_validar_recolecta_errores_por_item(self):
        """bulk_validar debe continuar procesando aunque un item falle."""
        content = read(API_FILE)
        # Capturar el cuerpo completo de la función
        match = re.search(
            r"async def bulk_validar_notas\([\s\S]*?return BulkValidarResponse",
            content,
        )
        assert match, "F-070: función bulk_validar_notas no encontrada."
        block = match.group(0)
        # debe usar try/except por cada item (el try está dentro del for)
        assert "try:" in block and "except Exception" in block, (
            "F-070: bulk_validar debe tener try/except por cada item "
            "para que un fallo no aborte el resto."
        )
        assert "fallidos" in block, (
            "F-070: bulk_validar debe retornar conteo de fallidos."
        )
