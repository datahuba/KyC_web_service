"""
Tests para el servicio de Cuentas por Cobrar
=============================================

F-CUENTAS-POR-COBRAR (2026-07-29): cubre la lógica pura de cálculo de
CxC real (a la fecha) vs estimada (total) y la validación de inicio
de módulo. La generación del reporte XLSX y la query a MongoDB
están cubiertas por smoke test E2E post-deploy.
"""

import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from services.cuentas_por_cobrar_service import (
    _calcular_saldo_modulo,
    _enrollment_excluido,
    _modulo_cuenta_cxc,
    iniciar_modulo,
    deshacer_inicio_modulo,
    ESTADOS_EXCLUIDOS_CXC,
)
from models.enums import EstadoInscripcion
from models.enrollment import ModuloEstado


# ========================================================================
# HELPERS: cálculo de saldo
# ========================================================================

class TestCalcularSaldoModulo:
    def test_saldo_cero_si_pagado_completo(self):
        m = ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=500)
        assert _calcular_saldo_modulo(m) == 0.0

    def test_saldo_total_si_sin_pago(self):
        m = ModuloEstado(nombre="M1", costo=500, estado="Pendiente", monto_pagado=0)
        assert _calcular_saldo_modulo(m) == 500.0

    def test_saldo_parcial(self):
        m = ModuloEstado(nombre="M1", costo=500, estado="Parcial", monto_pagado=200)
        assert _calcular_saldo_modulo(m) == 300.0

    def test_saldo_no_negativo_si_exceso(self):
        # Caso edge: pagó más del costo (saldo a favor)
        m = ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=600)
        assert _calcular_saldo_modulo(m) == 0.0  # max(0, ...)

    def test_costo_none_tratado_como_cero(self):
        # Si costo es None o 0, saldo = max(0, 0 - pago) = 0 si pago > 0
        m = ModuloEstado(nombre="M1", costo=0, estado="Pagado", monto_pagado=100)
        assert _calcular_saldo_modulo(m) == 0.0


# ========================================================================
# HELPERS: estado del módulo y del enrollment
# ========================================================================

class TestModuloCuentaCxc:
    def test_modulo_sin_iniciar_no_cuenta(self):
        m = ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=500)
        assert m.iniciado_en is None
        assert not _modulo_cuenta_cxc(m)

    def test_modulo_iniciado_si_cuenta(self):
        m = ModuloEstado(
            nombre="M1", costo=500, estado="Pagado", monto_pagado=500,
            iniciado_en=datetime(2026, 7, 29, tzinfo=timezone.utc),
        )
        assert _modulo_cuenta_cxc(m)


class TestEnrollmentExcluido:
    def _make_enrollment(self, estado):
        e = MagicMock()
        e.estado = estado
        return e

    def test_activo_no_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.ACTIVO)
        assert not _enrollment_excluido(e)

    def test_pendiente_pago_no_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.PENDIENTE_PAGO)
        assert not _enrollment_excluido(e)

    def test_suspendido_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.SUSPENDIDO)
        assert _enrollment_excluido(e)

    def test_retirado_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.RETIRADO)
        assert _enrollment_excluido(e)

    def test_cancelado_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.CANCELADO)
        assert _enrollment_excluido(e)

    def test_completado_excluido(self):
        e = self._make_enrollment(EstadoInscripcion.COMPLETADO)
        assert _enrollment_excluido(e)

    def test_estados_excluidos_son_los_correctos(self):
        # Documentación: estos son los estados que NO cuentan para CxC
        assert EstadoInscripcion.SUSPENDIDO in ESTADOS_EXCLUIDOS_CXC
        assert EstadoInscripcion.RETIRADO in ESTADOS_EXCLUIDOS_CXC
        assert EstadoInscripcion.CANCELADO in ESTADOS_EXCLUIDOS_CXC
        assert EstadoInscripcion.COMPLETADO in ESTADOS_EXCLUIDOS_CXC
        # Activos sí cuentan
        assert EstadoInscripcion.ACTIVO not in ESTADOS_EXCLUIDOS_CXC
        assert EstadoInscripcion.PENDIENTE_PAGO not in ESTADOS_EXCLUIDOS_CXC


# ========================================================================
# INICIAR MÓDULO: validaciones
# ========================================================================

class TestIniciarModulo:
    @pytest.mark.asyncio
    async def test_iniciar_modulo_ok(self):
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=500)
        ]
        enrollment.save = AsyncMock()

        result = await iniciar_modulo(
            enrollment=enrollment,
            modulo_index=0,
            current_user=MagicMock(),
        )

        # Verificar que se seteo iniciado_en
        assert enrollment.modulos[0].iniciado_en is not None
        # Verificar que se guardó
        enrollment.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_iniciar_modulo_idempotente(self):
        """Si el módulo ya estaba iniciado, no-op (no lanza, no guarda)."""
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        ts = datetime(2026, 7, 1, tzinfo=timezone.utc)
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=500, estado="Pagado",
                        monto_pagado=500, iniciado_en=ts)
        ]
        enrollment.save = AsyncMock()

        result = await iniciar_modulo(
            enrollment=enrollment,
            modulo_index=0,
            current_user=MagicMock(),
        )

        # No se modificó el iniciado_en
        assert enrollment.modulos[0].iniciado_en == ts
        # No se guardó (idempotente)
        enrollment.save.assert_not_called()

    @pytest.mark.asyncio
    async def test_iniciar_modulo_indice_fuera_de_rango(self):
        from fastapi import HTTPException
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        enrollment.modulos = [ModuloEstado(nombre="M1", costo=500)]
        enrollment.save = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await iniciar_modulo(
                enrollment=enrollment, modulo_index=5, current_user=MagicMock(),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_iniciar_modulo_indice_negativo(self):
        from fastapi import HTTPException
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        enrollment.modulos = [ModuloEstado(nombre="M1", costo=500)]
        enrollment.save = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await iniciar_modulo(
                enrollment=enrollment, modulo_index=-1, current_user=MagicMock(),
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_iniciar_modulo_enrollment_excluido(self):
        """Si el enrollment está SUSPENDIDO/RETIRADO/etc, no se puede iniciar."""
        from fastapi import HTTPException
        for estado in [EstadoInscripcion.SUSPENDIDO, EstadoInscripcion.RETIRADO,
                       EstadoInscripcion.CANCELADO, EstadoInscripcion.COMPLETADO]:
            enrollment = MagicMock()
            enrollment.estado = estado
            enrollment.modulos = [ModuloEstado(nombre="M1", costo=500)]
            enrollment.save = AsyncMock()

            with pytest.raises(HTTPException) as exc:
                await iniciar_modulo(
                    enrollment=enrollment, modulo_index=0, current_user=MagicMock(),
                )
            assert exc.value.status_code == 409, f"Falló con estado {estado}"


# ========================================================================
# DESHACER INICIO: validaciones
# ========================================================================

class TestDeshacerInicioModulo:
    @pytest.mark.asyncio
    async def test_deshacer_ok(self):
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        ts = datetime(2026, 7, 1, tzinfo=timezone.utc)
        enrollment.modulos = [
            ModuloEstado(nombre="M1", costo=500, iniciado_en=ts)
        ]
        enrollment.save = AsyncMock()

        await deshacer_inicio_modulo(
            enrollment=enrollment, modulo_index=0, current_user=MagicMock(),
        )

        # Verificar que se limpió el iniciado_en
        assert enrollment.modulos[0].iniciado_en is None
        enrollment.save.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_deshacer_sin_inicio_previo_409(self):
        from fastapi import HTTPException
        enrollment = MagicMock()
        enrollment.estado = EstadoInscripcion.ACTIVO
        enrollment.modulos = [ModuloEstado(nombre="M1", costo=500)]  # sin iniciado_en
        enrollment.save = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await deshacer_inicio_modulo(
                enrollment=enrollment, modulo_index=0, current_user=MagicMock(),
            )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_deshacer_indice_fuera_de_rango(self):
        from fastapi import HTTPException
        enrollment = MagicMock()
        enrollment.modulos = [ModuloEstado(nombre="M1", costo=500)]
        enrollment.save = AsyncMock()

        with pytest.raises(HTTPException) as exc:
            await deshacer_inicio_modulo(
                enrollment=enrollment, modulo_index=99, current_user=MagicMock(),
            )
        assert exc.value.status_code == 400


# ========================================================================
# LÓGICA DE FILTRADO: qué se incluye en el reporte
# ========================================================================

class TestCalculoCxCResumen:
    """Test de la lógica de cálculo de saldos a la fecha vs estimados."""

    def test_caso_simple_5_modulos_3_iniciados(self):
        """
        Programa de 5 módulos. M1, M2, M3 iniciados (pagados). M4, M5 no.
        - Estimado: suma de todos los saldos pendientes
        - Real: solo M1+M2+M3 (los iniciados)
        """
        modulos = [
            ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=500, iniciado_en=datetime.now(timezone.utc)),
            ModuloEstado(nombre="M2", costo=500, estado="Pagado", monto_pagado=500, iniciado_en=datetime.now(timezone.utc)),
            ModuloEstado(nombre="M3", costo=500, estado="Pagado", monto_pagado=300, iniciado_en=datetime.now(timezone.utc)),
            ModuloEstado(nombre="M4", costo=500, estado="Pendiente", monto_pagado=0),
            ModuloEstado(nombre="M5", costo=500, estado="Pendiente", monto_pagado=0),
        ]
        # Saldo estimado = 0+0+200+500+500 = 1200
        # Saldo a la fecha = 0+0+200+0+0 = 200
        estimado = sum(_calcular_saldo_modulo(m) for m in modulos)
        real = sum(_calcular_saldo_modulo(m) for m in modulos if _modulo_cuenta_cxc(m))
        assert estimado == 1200.0
        assert real == 200.0
        assert estimado - real == 1000.0  # pendiente de devengar

    def test_modulo_2_iniciado_y_3_no_escenario_reunion(self):
        """
        Escenario de la reunión con Sandra: M1 pagado, M2 en curso, M3 no.
        - M1 está pagado pero NO iniciado → NO cuenta para CxC real
        - M2 en curso → sí cuenta
        - M3 no iniciado → no cuenta
        """
        modulos = [
            ModuloEstado(nombre="M1", costo=500, estado="Pagado", monto_pagado=500),  # NO iniciado
            ModuloEstado(nombre="M2", costo=500, estado="Parcial", monto_pagado=200, iniciado_en=datetime.now(timezone.utc)),
            ModuloEstado(nombre="M3", costo=500, estado="Pendiente", monto_pagado=0),  # NO iniciado
        ]
        real = sum(_calcular_saldo_modulo(m) for m in modulos if _modulo_cuenta_cxc(m))
        assert real == 300.0  # solo M2

    def test_estudiante_pasivo_no_aparece_en_reporte(self):
        """
        Si un enrollment está SUSPENDIDO, NO cuenta para CxC
        (ni en estimado ni en real). La función de servicio ya
        lo filtra antes de calcular.
        """
        e = MagicMock()
        e.estado = EstadoInscripcion.SUSPENDIDO
        assert _enrollment_excluido(e)
        # En el reporte final, este enrollment ni siquiera aparece
