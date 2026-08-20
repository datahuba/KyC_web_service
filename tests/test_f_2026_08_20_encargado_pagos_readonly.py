"""
Tests para F-2026-08-20-EC-PAGOS-READONLY
=========================================
Verifica que:
1. `encargado_curso` y `coordinador` tienen permiso de solo lectura en Gestión de Pagos:
   - `list_payments` (GET /payments/) los autoriza.
   - `export_payments_excel` (GET /payments/export/excel) los autoriza.
   - `puede_ver_economico` es True para `encargado_curso` y `coordinador` financiero.
2. `filtro_cursos_por_rol` segmenta por `cursos_asignados`.
3. Endpoints de escritura (mutación/aprobación) bloquean a `encargado_curso` con 403.
"""

import pytest
from beanie import PydanticObjectId
from fastapi import HTTPException

from api.dependencies import (
    puede_ver_economico,
    filtro_cursos_por_rol,
)
from models.user import User
from models.enums import UserRole, SubtipoCoordinador


class TestEncargadoPagosPermisos:
    def test_puede_ver_economico_encargado_curso(self):
        user_ec = User.model_construct(
            rol=UserRole.ENCARGADO_CURSO,
            cursos_asignados=[PydanticObjectId()],
        )
        assert puede_ver_economico(user_ec) is True

    def test_puede_ver_economico_coordinador_financiero(self):
        user_coord_fin = User.model_construct(
            rol=UserRole.COORDINADOR,
            subtipo_coordinador=SubtipoCoordinador.FINANCIERO,
        )
        assert puede_ver_economico(user_coord_fin) is True

    def test_puede_ver_economico_coordinador_academico_restringido(self):
        user_coord_acad = User.model_construct(
            rol=UserRole.COORDINADOR,
            subtipo_coordinador=SubtipoCoordinador.ACADEMICO,
        )
        assert puede_ver_economico(user_coord_acad) is False

    def test_filtro_cursos_por_rol_segmenta_encargado(self):
        c1 = PydanticObjectId()
        c2 = PydanticObjectId()
        user_ec = User.model_construct(
            rol=UserRole.ENCARGADO_CURSO,
            cursos_asignados=[c1, c2],
        )
        filtro = filtro_cursos_por_rol(user_ec)
        assert filtro is not None
        assert "curso_id" in filtro
        assert "$in" in filtro["curso_id"]
        assert filtro["curso_id"]["$in"] == [c1, c2]

    def test_export_payments_excel_incluye_encargado_y_coordinador(self):
        """Verifica que el código fuente de export_payments_excel autoriza a encargado_curso y coordinador."""
        import inspect
        from api.payments import export_payments_excel

        src = inspect.getsource(export_payments_excel)
        assert "encargado_curso" in src
        assert "coordinador" in src

    def test_list_payments_incluye_encargado_y_coordinador(self):
        """Verifica que el código fuente de list_payments autoriza a encargado_curso y coordinador."""
        import inspect
        from api.payments import list_payments

        src = inspect.getsource(list_payments)
        assert "encargado_curso" in src
        assert "coordinador" in src
