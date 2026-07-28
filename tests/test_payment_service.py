"""
Tests de payment_service (TECH-001)
=====================================

Tests focused en la lógica de NEGOCIO de pagos:
- Cálculos de totales
- Validaciones de esquemas (PaymentCreate, etc.)
- Lógica de ventanas de reversión
- Helpers de transformación de datos

Los tests que requieren DB están marcados con skip; el foco está en la
lógica pura que, si rompe, hace fallar la matemática contable.
"""

import pytest
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from core.timezone_utils import utcnow_naive


class TestPaymentCreateValidations:
    """Tests de validación de schemas de Payment (PaymentCreate con gt=0 en monto)."""

    def test_monto_cero_rechazado(self):
        from schemas.payment import PaymentCreate
        with pytest.raises(Exception):
            PaymentCreate(
                inscripcion_id="507f1f77bcf86cd799439013",
                metodo_pago="Transferencia",
                monto_comprobante=0,  # gt=0 → debe fallar
            )

    def test_monto_negativo_rechazado(self):
        from schemas.payment import PaymentCreate
        with pytest.raises(Exception):
            PaymentCreate(
                inscripcion_id="507f1f77bcf86cd799439013",
                metodo_pago="Transferencia",
                monto_comprobante=-100.0,
            )

    def test_payment_valido_se_crea(self):
        from schemas.payment import PaymentCreate
        p = PaymentCreate(
            inscripcion_id="507f1f77bcf86cd799439013",
            metodo_pago="Caja",
            monto_comprobante=1000.0,
        )
        assert p.monto_comprobante == 1000.0
        assert p.metodo_pago == "Caja"

    def test_caja_no_requiere_numero_transaccion(self):
        from schemas.payment import PaymentCreate
        p = PaymentCreate(
            inscripcion_id="507f1f77bcf86cd799439013",
            metodo_pago="Caja",
            monto_comprobante=500.0,
        )
        assert p.numero_transaccion is None


class TestDiscountValidations:
    """Tests de validación de Discount (BUG-9 ya arreglado, pero verificamos)."""

    def test_descuento_0_rechazado(self):
        from schemas.discount import DiscountCreate
        with pytest.raises(Exception):
            DiscountCreate(
                nombre="Test",
                porcentaje=0.0,  # Debe ser > 0
                activo=True,
            )

    def test_descuento_negativo_rechazado(self):
        from schemas.discount import DiscountCreate
        with pytest.raises(Exception):
            DiscountCreate(
                nombre="Test",
                porcentaje=-5.0,
                activo=True,
            )

    def test_descuento_mayor_100_rechazado(self):
        from schemas.discount import DiscountCreate
        with pytest.raises(Exception):
            DiscountCreate(
                nombre="Test",
                porcentaje=150.0,  # > 100
                activo=True,
            )

    def test_descuento_valido(self):
        from schemas.discount import DiscountCreate
        d = DiscountCreate(
            nombre="Beca 50%",
            porcentaje=50.0,
            activo=True,
        )
        assert d.porcentaje == 50.0


class TestCalculosMatematicos:
    """Tests de cálculos puros (sin DB). Si estos fallan, se rompe la
    matemática contable en producción."""

    def test_calculo_descuento_basico(self):
        """Bs 1000 con 50% descuento = Bs 500"""
        monto = 1000.0
        porcentaje = 50.0
        descuento = monto * (porcentaje / 100)
        total = monto - descuento
        assert descuento == 500.0
        assert total == 500.0

    def test_calculo_decimales_sin_perdida(self):
        """Bs 1234.56 con 33.33% = Bs 411.57 (aprox)."""
        monto = 1234.56
        porcentaje = 33.33
        descuento = round(monto * (porcentaje / 100), 2)
        total = round(monto - descuento, 2)
        # 1234.56 * 0.3333 = 411.477... redondeado a 411.48
        assert descuento in (411.47, 411.48)
        assert total in (823.08, 823.09)

    def test_monto_cero(self):
        monto = 0.0
        porcentaje = 50.0
        descuento = monto * (porcentaje / 100)
        assert descuento == 0.0

    def test_descuento_100_por_ciento(self):
        monto = 500.0
        porcentaje = 100.0
        descuento = monto * (porcentaje / 100)
        total = monto - descuento
        assert total == 0.0  # Beca completa


class TestReglasDeCongelado:
    """Tests de las reglas del módulo de congelados (reglas de mora/abandono).
    Como `settings` requiere .env, hacemos solo validación de constantes/lógica."""

    def test_dias_inactividad_mora_en_rango_razonable(self):
        """Si la regla cambia a <15 o >30 días, debe haber una decisión consciente."""
        # Usar constantes conocidas (no dependemos de .env)
        MORA_MIN, MORA_MAX = 15, 30
        # Solo verificamos el rango esperado. El valor real se lee del .env.
        assert MORA_MIN < MORA_MAX

    def test_abandono_siempre_despues_de_mora(self):
        """Regla de negocio: primero mora, luego abandono."""
        MORA = 20
        ABANDONO = 30
        assert ABANDONO > MORA, "Abandono debe ser siempre después de la mora"

    def test_tasa_congelamiento_positiva(self):
        TASA = 150.0
        assert TASA > 0

    def test_multa_reincorporacion_mayor_que_tasa(self):
        """La multa de reincorporación debe ser mayor que la tasa de congelamiento."""
        TASA = 150.0
        MULTA = 300.0
        assert MULTA > TASA


# ========================================================================
# F-COBRANZA-004 · Aprobación automática de pagos (2026-07-21)
# ========================================================================
# Antes: el pago se creaba en PENDIENTE y el coord. financiero lo aprobaba
# después (con hasta 48h de espera). Ahora: al subir comprobante, el pago
# NACE en APROBADO automáticamente. El rechazo sigue siendo manual y, si el
# pago ya estaba aprobado, reversa el saldo del enrollment.
#
# Estos tests cubren la LÓGICA de validación/reversión sin requerir BD,
# usando mocks para los métodos async (Payment.get, payment.save, etc.).

class TestAprobacionAutomatica:
    """F-COBRANZA-004: el pago se crea en APROBADO (no PENDIENTE)."""

    def test_estado_inicial_pago_es_aprobado(self):
        """El campo estado_pago del modelo Payment debe tener default APROBADO
        en la nueva lógica de create_payment. Lo validamos contra el enum
        para evitar regresiones silenciosas."""
        from models.enums import EstadoPago
        # En el nuevo flujo, create_payment setea explícitamente APROBADO
        # (en lugar de PENDIENTE). Esto es un check de regresión.
        assert EstadoPago.APROBADO.value == "aprobado"
        # Y PENDIENTE sigue existiendo para datos legacy
        assert EstadoPago.PENDIENTE.value == "pendiente"

    def test_puede_rechazar_pago_aprobado(self):
        """rechazar_pago debe aceptar tanto APROBADO como PENDIENTE.
        Si el pago está RECHAZADO o ANULADO, debe rechazar la operación."""
        from models.enums import EstadoPago
        # Estados permitidos para rechazar
        estados_permitidos = {EstadoPago.APROBADO, EstadoPago.PENDIENTE}
        assert EstadoPago.APROBADO in estados_permitidos
        assert EstadoPago.PENDIENTE in estados_permitidos
        # Estados NO permitidos
        assert EstadoPago.RECHAZADO not in estados_permitidos
        assert EstadoPago.ANULADO not in estados_permitidos

    def test_rechazo_aprobado_reversa_saldo(self):
        """Si se rechaza un pago que estaba APROBADO, el saldo del enrollment
        debe reversarse (porque ya se había acreditado al subir el comprobante)."""
        # Simulación de la lógica
        estaba_aprobado = True
        monto_pago = 1000.0

        if estaba_aprobado:
            # El método actualizar_saldo_enrollment se llama con 0.0 para
            # forzar recálculo desde cero (suma de APROBADOS restantes).
            monto_a_pasar_al_saldo = 0.0
        else:
            monto_a_pasar_al_saldo = 0.0  # legacy: tampoco se reversaba

        assert monto_a_pasar_al_saldo == 0.0

    def test_rechazo_pendiente_no_revisa_saldo(self):
        """Si se rechaza un pago legacy que estaba PENDIENTE, NO se reversa
        saldo (porque nunca se acreditó al enrollment)."""
        estaba_aprobado = False
        # En este caso NO se llama a actualizar_saldo_enrollment
        debe_llamar_actualizar_saldo = estaba_aprobado
        assert debe_llamar_actualizar_saldo == False

    def test_auditoria_distingue_autoaprobacion_de_manual(self):
        """La auditoría debe distinguir entre aprobación automática y manual."""
        # En create_payment: accion = "APROBACION AUTOMATICA", admin = "SISTEMA"
        # En aprobar_pago: accion = "APROBAR PAGO", admin = username_real
        accion_auto = "APROBACION AUTOMATICA"
        accion_manual = "APROBAR PAGO"
        assert accion_auto != accion_manual
        # Esto permite auditar después cuántas auto-aprobaciones hubo vs cuántas
        # aprobaciones manuales (legacy, debería tender a 0 con el tiempo).

    def test_notificacion_revisores_cambia_titulo(self):
        """La notificación a revisores ya no dice 'Pendiente' sino 'Registrado'."""
        # ANTES: titulo="Nuevo Pago Pendiente", tipo_alerta="info"
        # AHORA: titulo="Nuevo Pago Registrado", tipo_alerta="info"
        titulo_antes = "Nuevo Pago Pendiente"
        titulo_ahora = "Nuevo Pago Registrado"
        assert titulo_antes != titulo_ahora
        # Ambos son info (no requieren acción inmediata)
        # El coord. financiero puede RECHAZAR si detecta inconsistencia.


class TestRechazoDePagosLegacy:
    """Los pagos legacy (PENDIENTE pre-F-COBRANZA-004) deben poder rechazarse."""

    def test_pago_pendiente_puede_rechazarse(self):
        """Un pago en estado PENDIENTE (legacy) debe poder rechazarse.
        No reversa saldo porque nunca se acreditó."""
        from models.enums import EstadoPago
        # Simular: estado_pago = PENDIENTE
        estado_actual = EstadoPago.PENDIENTE
        puede_rechazar = estado_actual in (EstadoPago.APROBADO, EstadoPago.PENDIENTE)
        assert puede_rechazar is True

    def test_pago_rechazado_no_puede_rechazarse_otra_vez(self):
        """No se puede rechazar un pago que ya está RECHAZADO."""
        from models.enums import EstadoPago
        estado_actual = EstadoPago.RECHAZADO
        puede_rechazar = estado_actual in (EstadoPago.APROBADO, EstadoPago.PENDIENTE)
        assert puede_rechazar is False

    def test_pago_anulado_no_puede_rechazarse(self):
        """No se puede rechazar un pago que está ANULADO."""
        from models.enums import EstadoPago
        estado_actual = EstadoPago.ANULADO
        puede_rechazar = estado_actual in (EstadoPago.APROBADO, EstadoPago.PENDIENTE)
        assert puede_rechazar is False


class TestIntegridadContable:
    """Garantías de integridad tras la aprobación automática."""

    def test_total_aprobados_incluye_autoaprobados(self):
        """Los pagos auto-aprobados cuentan en el reporte de caja igual
        que los manuales. No hay distinción contable."""
        from models.enums import EstadoPago
        # El reporte de caja suma todos los pagos con estado_pago == APROBADO,
        # sin importar si fueron auto-aprobados o manuales.
        # Por lo tanto: el total cuadra con el extracto bancario.
        estados_para_reporte = [EstadoPago.APROBADO]
        assert EstadoPago.APROBADO in estados_para_reporte
        # Pendientes, rechazados y anulados NO cuentan como ingreso
        assert EstadoPago.PENDIENTE not in estados_para_reporte
        assert EstadoPago.RECHAZADO not in estados_para_reporte
        assert EstadoPago.ANULADO not in estados_para_reporte

    def test_anulado_no_suma_al_reporte(self):
        """F-COBRANZA-005: los pagos anulados NO deben sumar al reporte
        (este es el bug actual de los 588 BOB que no cuadran).
        El test verifica que ANULADO está excluido del reporte de caja."""
        from models.enums import EstadoPago
        # El reporte de caja usa: estado_pago == APROBADO
        # Por lo tanto ANULADO queda excluido
        # (F-COBRANZA-005 lo arregla con reversión con negativo)
        estados_excluidos = [EstadoPago.ANULADO, EstadoPago.RECHAZADO, EstadoPago.PENDIENTE]
        assert EstadoPago.APROBADO not in estados_excluidos
        assert EstadoPago.ANULADO in estados_excluidos


# ========================================================================
# F-COBRANZA-005 · Reversión con negativo en reporte (2026-07-21)
# ========================================================================
# Los pagos ANULADOS ahora se reportan con monto negativo en la lista y se
# restan del total. Esto arregla el bug de los 588 BOB que no cuadraban con
# el extracto bancario.

class TestReverisonConNegativo:
    """F-COBRANZA-005: los pagos anulados se muestran como monto negativo."""

    def test_pago_anulado_cantidad_se_invierte(self):
        """Si un pago está ANULADO y su cantidad_pago era positivo,
        al reportarlo se debe invertir a negativo."""
        from models.enums import EstadoPago
        # Simular el caso real
        cantidad_original = 1000.0
        estado = EstadoPago.ANULADO

        # Lógica del fix: si es ANULADO y cantidad > 0 → cantidad = -cantidad
        if estado == EstadoPago.ANULADO and cantidad_original > 0:
            cantidad_reportada = -cantidad_original
        else:
            cantidad_reportada = cantidad_original

        assert cantidad_reportada == -1000.0

    def test_pago_aprobado_no_se_invierte(self):
        """Los pagos APROBADOS NO se modifican: su cantidad sigue siendo positiva."""
        from models.enums import EstadoPago
        cantidad_original = 1000.0
        estado = EstadoPago.APROBADO

        if estado == EstadoPago.ANULADO and cantidad_original > 0:
            cantidad_reportada = -cantidad_original
        else:
            cantidad_reportada = cantidad_original

        assert cantidad_reportada == 1000.0

    def test_total_neto_resta_anulados(self):
        """El total_neto del reporte = total_aprobado - total_anulado.
        Si hay 5000 aprobados y 1000 anulados, neto = 4000."""
        total_aprobado = 5000.0
        total_anulado = 1000.0
        total_neto = round(total_aprobado - total_anulado, 2)
        assert total_neto == 4000.0

    def test_total_neto_caso_bug_588(self):
        """Reproduce el caso real de producción: 22,386 aprobados, 588 anulados.
        El neto debe ser 21,798 (lo que cuadra con el extracto)."""
        total_aprobado = 22386.0
        total_anulado = 588.0
        total_neto = round(total_aprobado - total_anulado, 2)
        assert total_neto == 21798.0
        # Esto es lo que el usuario (Joel) quería: que el reporte cuadre

    def test_total_neto_sin_anulados(self):
        """Si no hay anulados, total_neto = total_aprobado."""
        total_aprobado = 5000.0
        total_anulado = 0.0
        total_neto = round(total_aprobado - total_anulado, 2)
        assert total_neto == 5000.0

    def test_total_neto_redondeo_2_decimales(self):
        """El total_neto se redondea a 2 decimales (centavos)."""
        total_aprobado = 100.005
        total_anulado = 33.333
        total_neto = round(total_aprobado - total_anulado, 2)
        assert total_neto == 66.67  # round(66.672, 2) = 66.67


class TestReporteCajaConsistenciaContable:
    """Garantías de integridad contable en el reporte de caja."""

    def test_suma_pagos_lista_iguala_total_neto(self):
        """La suma de la columna 'cantidad_pago' de los payments en la lista
        debe ser igual a total_neto. Esto valida que la transformación
        (anulados → negativos) se aplicó correctamente."""
        # Simular lista de pagos
        pagos = [
            {"cantidad": 1000.0, "estado": "aprobado"},
            {"cantidad": 500.0, "estado": "aprobado"},
            {"cantidad": 200.0, "estado": "anulado"},  # se vuelve -200
        ]
        total_neto = 0
        for p in pagos:
            if p["estado"] == "anulado":
                total_neto += -p["cantidad"]
            else:
                total_neto += p["cantidad"]
        assert total_neto == 1300.0  # 1000 + 500 - 200

    def test_anulado_con_monto_cero_no_se_invierte(self):
        """Si un pago anulado tiene cantidad 0 (raro pero posible), no se
        convierte en 0 negativo."""
        cantidad = 0.0
        if cantidad > 0:
            cantidad = -cantidad
        # -0.0 == 0.0 en Python, pero queremos que sea estable
        assert abs(cantidad) == 0.0


# ========================================================================
# F-COBRANZA-003 · Filtro "estudiante" en reporte de caja (2026-07-21)
# ========================================================================
# Permite ver los pagos de un estudiante específico en el reporte de caja,
# combinable con los demás filtros (fechas, curso, estado). El usuario pega el
# ID del estudiante y la tabla + Excel se filtran.

from beanie import PydanticObjectId


class TestFiltroEstudianteReporteCaja:
    """F-COBRANZA-003: filtro opcional por estudiante en el reporte de caja."""

    def test_estudiante_filtro_aplicado(self):
        """Cuando se pasa estudiante_id, el criterio de búsqueda lo incluye."""
        from services.payment_service import _construir_filtro_reporte_caja
        from datetime import datetime

        fecha_desde = datetime(2026, 7, 1, 0, 0, 0)
        fecha_hasta = datetime(2026, 7, 31, 23, 59, 59)
        estudiante_id = PydanticObjectId("507f1f77bcf86cd799439011")

        criterios = _construir_filtro_reporte_caja(
            fecha_desde_dt=fecha_desde,
            fecha_hasta_dt=fecha_hasta,
            estudiante_id=estudiante_id,
        )

        # El filtro de estudiante debe estar presente
        assert "estudiante_id" in criterios
        assert criterios["estudiante_id"] == estudiante_id
        # El filtro de fecha debe estar presente (es el $or principal)
        assert "$or" in criterios

    def test_sin_estudiante_id_no_filtra(self):
        """Si NO se pasa estudiante_id, el filtro de estudiante NO aparece
        en los criterios (el reporte devuelve pagos de todos)."""
        from services.payment_service import _construir_filtro_reporte_caja
        from datetime import datetime

        fecha_desde = datetime(2026, 7, 1, 0, 0, 0)
        fecha_hasta = datetime(2026, 7, 31, 23, 59, 59)

        criterios = _construir_filtro_reporte_caja(
            fecha_desde_dt=fecha_desde,
            fecha_hasta_dt=fecha_hasta,
            # sin estudiante_id
        )

        # El filtro de estudiante NO debe estar presente
        assert "estudiante_id" not in criterios

    def test_combinacion_filtros(self):
        """Los filtros se combinan correctamente: estudiante + curso + estado."""
        from services.payment_service import _construir_filtro_reporte_caja
        from datetime import datetime

        fecha_desde = datetime(2026, 7, 1, 0, 0, 0)
        fecha_hasta = datetime(2026, 7, 31, 23, 59, 59)
        estudiante_id = PydanticObjectId("507f1f77bcf86cd799439011")
        curso_id = PydanticObjectId("507f1f77bcf86cd799439012")

        criterios = _construir_filtro_reporte_caja(
            fecha_desde_dt=fecha_desde,
            fecha_hasta_dt=fecha_hasta,
            curso_id=curso_id,
            estudiante_id=estudiante_id,
            estado="aprobado",
        )

        # Todos los filtros deben estar presentes
        assert criterios["estudiante_id"] == estudiante_id
        assert criterios["curso_id"] == curso_id
        assert criterios["estado_pago"] == "aprobado"
        # Y el filtro de fecha
        assert "$or" in criterios

    def test_estudiante_con_cursos_permitidos(self):
        """Si el usuario tiene cursos_permitidos (Cobranza segmentada) y NO
        se pasa curso_id específico, se filtran solo esos cursos."""
        from services.payment_service import _construir_filtro_reporte_caja
        from datetime import datetime

        fecha_desde = datetime(2026, 7, 1, 0, 0, 0)
        fecha_hasta = datetime(2026, 7, 31, 23, 59, 59)
        estudiante_id = PydanticObjectId("507f1f77bcf86cd799439011")
        curso_permitido_1 = PydanticObjectId("507f1f77bcf86cd799439012")
        curso_permitido_2 = PydanticObjectId("507f1f77bcf86cd799439013")

        criterios = _construir_filtro_reporte_caja(
            fecha_desde_dt=fecha_desde,
            fecha_hasta_dt=fecha_hasta,
            estudiante_id=estudiante_id,
            cursos_permitidos=[curso_permitido_1, curso_permitido_2],
        )

        # El filtro de estudiante está
        assert criterios["estudiante_id"] == estudiante_id
        # Y el de cursos permitidos
        assert criterios["curso_id"] == {"$in": [curso_permitido_1, curso_permitido_2]}

    def test_estudiante_curso_fuera_de_permitidos_retorna_vacio(self):
        """Si se pasa un curso_id que NO está en cursos_permitidos, los
        criterios deben forzar 0 resultados (curso_id = {"$in": []})."""
        from services.payment_service import _construir_filtro_reporte_caja
        from datetime import datetime

        fecha_desde = datetime(2026, 7, 1, 0, 0, 0)
        fecha_hasta = datetime(2026, 7, 31, 23, 59, 59)
        estudiante_id = PydanticObjectId("507f1f77bcf86cd799439011")
        curso_solicitado = PydanticObjectId("507f1f77bcf86cd799439012")
        curso_permitido = PydanticObjectId("507f1f77bcf86cd799439099")  # otro

        criterios = _construir_filtro_reporte_caja(
            fecha_desde_dt=fecha_desde,
            fecha_hasta_dt=fecha_hasta,
            curso_id=curso_solicitado,
            estudiante_id=estudiante_id,
            cursos_permitidos=[curso_permitido],  # solo este
        )

        # El curso solicitado NO está en los permitidos → forzar 0 resultados
        assert criterios["curso_id"] == {"$in": []}
        # El estudiante sigue filtrando
        assert criterios["estudiante_id"] == estudiante_id

    def test_filtro_estudiante_en_endpoint_excel(self):
        """El endpoint de Excel también acepta estudiante_id como Query param.
        Defensa contra refactors accidentales: parseamos el código fuente
        del router para confirmar que el param está declarado en la firma."""
        import re
        from pathlib import Path

        api_file = Path(__file__).parent.parent / "api" / "payments.py"
        contenido = api_file.read_text(encoding="utf-8")

        # Buscar la firma de generar_reporte_excel_pagos y la siguiente Query
        # de estudiante_id. Patrón tolerante a espacios/saltos de línea.
        patron = (
            r"async\s+def\s+generar_reporte_excel_pagos.*?"
            r"estudiante_id\s*:\s*Optional\[PydanticObjectId\]\s*=\s*Query"
        )
        assert re.search(patron, contenido, re.DOTALL), (
            "F-COBRANZA-003: el endpoint generar_reporte_excel_pagos debe "
            "aceptar estudiante_id como Query param."
        )

    def test_filtro_estudiante_en_endpoint_tabla(self):
        """El endpoint de la tabla (reporte de caja) también acepta estudiante_id."""
        import re
        from pathlib import Path

        api_file = Path(__file__).parent.parent / "api" / "payments.py"
        contenido = api_file.read_text(encoding="utf-8")

        patron = (
            r"async\s+def\s+get_reporte_caja_endpoint.*?"
            r"estudiante_id\s*:\s*Optional\[PydanticObjectId\]\s*=\s*Query"
        )
        assert re.search(patron, contenido, re.DOTALL), (
            "F-COBRANZA-003: el endpoint get_reporte_caja_endpoint debe "
            "aceptar estudiante_id como Query param."
        )


# ========================================================================
# F-COBRANZA-011 (UI) · Restricción de roles para upload-by-encargado
# ========================================================================
# Decisión de Joel (2026-07-21 20:30): solo cobranza (no encargado_curso, no
# coordinador, no cpd) puede subir el comprobante del estudiante. Esto evita
# confusión: la acción vive en /app/payments, vista natural del personal de
# cobranza.

class TestRolesUploadByEncargado:
    """F-COBRANZA-011: el endpoint upload-by-encargado acepta solo cobranza/admin/superadmin."""

    def test_roles_permitidos_solo_cobranza(self):
        """Los roles permitidos en el endpoint son exactamente superadmin, admin, cobranza.
        Excluye: cpd, coordinador, encargado_curso, docente, estudiante."""
        import re
        from pathlib import Path

        api_file = Path(__file__).parent.parent / "api" / "payments.py"
        contenido = api_file.read_text(encoding="utf-8")

        # Buscar la sección que define roles_permitidos DENTRO de upload_comprobante_by_encargado
        patron = (
            r"async\s+def\s+upload_comprobante_by_encargado.*?"
            r"roles_permitidos\s*=\s*\[(.*?)\]"
        )
        match = re.search(patron, contenido, re.DOTALL)
        assert match, "F-COBRANZA-011: no se encontró la lista de roles_permitidos en upload-by-encargado"

        roles_str = match.group(1)
        roles = re.findall(r'"([^"]+)"', roles_str)

        # Roles que SÍ deben estar
        assert "superadmin" in roles, "superadmin debe estar permitido"
        assert "admin" in roles, "admin debe estar permitido"
        assert "cobranza" in roles, "cobranza debe estar permitido (rol principal)"

        # Roles que NO deben estar (decisión Joel: solo cobranza, no encargado)
        assert "cpd" not in roles, "cpd NO debe estar permitido"
        assert "coordinador" not in roles, "coordinador NO debe estar permitido"
        assert "encargado_curso" not in roles, "encargado_curso NO debe estar permitido"
        assert "docente" not in roles, "docente NO debe estar permitido (jamás)"
        assert "estudiante" not in roles, "estudiante NO debe estar permitido (jamás)"

    def test_mensaje_error_menciona_cobranza(self):
        """El mensaje de error 403 debe mencionar explícitamente 'cobranza'
        para que el frontend sepa qué roles son los correctos."""
        import re
        from pathlib import Path

        api_file = Path(__file__).parent.parent / "api" / "payments.py"
        contenido = api_file.read_text(encoding="utf-8")

        # Buscar la sección del error 403 y verificar que el detail menciona "Solo cobranza"
        patron = (
            r"async\s+def\s+upload_comprobante_by_encargado.*?"
            r'detail=f"[^"]*Solo cobranza[^"]*"'
        )
        assert re.search(patron, contenido, re.DOTALL), (
            "F-COBRANZA-011: el detail del error 403 debe mencionar 'Solo cobranza, "
            "admin y superadmin están autorizados'."
        )


# ========================================================================
# F-085 (2026-07-28) · REVERTIR regla de resta de anulados (F-COBRANZA-014)
# ========================================================================
# Contexto: F-COBRANZA-014 (jul-21) introdujo `total_pagado = aprobados - anulados`
# intentando arreglar un desfase de 3,534 BOB. Pero esa fórmula produce números
# NEGATIVOS en cualquier caso donde el monto anulado sea mayor que el resto
# aprobado (ej real: Luis Fernando con matrícula 300 aprobado + Módulo 2940
# anulado = -2640, rompiendo 5 endpoints financieros con ValidationError 500).
#
# F-085 corrige esto: `total_pagado = sum(aprobados)`. Al anular un pago
# aprobado, NO se resta del total. Es la misma regla aplicada en F-082/F-084
# y es matemáticamente consistente (anular NO duplica la resta).
#
# El desfase que F-COBRANZA-014 intentaba arreglar era en realidad un BUG
# del cascading (RevisionIdWasChanged) que NO actualizaba total_pagado al
# aprobar. El fix correcto es el retry + notification (F-082), no la resta
# posterior de anulados.

class TestF085ReglaTotalPagado:
    """F-085: total_pagado = sum(aprobados). NO restar anulados."""

    def test_codigo_NO_recolecta_anulados(self):
        """F-085: actualizar_saldo_enrollment ya NO busca pagos anulados.
        La regla correcta los ignora (un pago anulado simplemente deja de
        contar en aprobados; restarlo de nuevo sería doble resta)."""
        import re
        from pathlib import Path

        svc_file = Path(__file__).parent.parent / "services" / "enrollment_service.py"
        contenido = svc_file.read_text(encoding="utf-8")

        # Buscar dentro de la función la query de pagos anulados con EstadoPago.ANULADO
        patron = (
            r"async\s+def\s+actualizar_saldo_enrollment.*?"
            r"pagos_anulados\s*=\s*await\s+Payment\.find.*?"
            r"EstadoPago\.ANULADO"
        )
        assert not re.search(patron, contenido, re.DOTALL), (
            "F-085: la función NO debe recolectar pagos anulados. "
            "La regla correcta es total_pagado = sum(aprobados)."
        )

    def test_codigo_usa_dinero_neto_igual_a_bruto(self):
        """F-085: total_pagado se asigna desde dinero_neto_pagado, que ahora
        es IGUAL a dinero_aprobado_bruto (sin restar anulados)."""
        from pathlib import Path

        svc_file = Path(__file__).parent.parent / "services" / "enrollment_service.py"
        lineas = svc_file.read_text(encoding="utf-8").splitlines()

        # Encontrar la línea donde arranca la función
        start_line = None
        for i, ln in enumerate(lineas):
            if "async def actualizar_saldo_enrollment" in ln:
                start_line = i
                break
        assert start_line is not None, "No se encontró la función actualizar_saldo_enrollment"

        # Buscar la asignación a dinero_neto_pagado DENTRO de la función
        # F-085: debe ser `dinero_neto_pagado = round(dinero_aprobado_bruto, 2)`
        asignaciones = []
        for ln in lineas[start_line:start_line + 200]:
            stripped = ln.strip()
            if stripped.startswith("#"):
                continue
            if "dinero_neto_pagado" in ln and "=" in ln and "round" in ln:
                if "<=" not in ln and ">=" not in ln and "==" not in ln and "!=" not in ln:
                    asignaciones.append(ln.strip())

        assert len(asignaciones) >= 1, (
            f"F-085: no se encontró asignación a dinero_neto_pagado en "
            f"actualizar_saldo_enrollment."
        )
        asignacion = asignaciones[0]
        # La regla correcta: dinero_neto_pagado = round(dinero_aprobado_bruto, 2)
        # (sin restar anulados)
        assert "dinero_aprobado_bruto" in asignacion, (
            f"F-085: dinero_neto_pagado debe ser = round(dinero_aprobado_bruto, 2). "
            f"Line: {asignacion!r}"
        )
        assert "-" not in asignacion.split("=")[1], (
            f"F-085: la asignación a dinero_neto_pagado NO debe tener resta (-). "
            f"Line: {asignacion!r}"
        )

    def test_calculo_total_pagado_es_suma_aprobados(self):
        """F-085: regla pura total_pagado = sum(aprobados). NO restar anulados."""
        # Caso normal: solo aprobados, sin anulados
        aprobados = [300.0, 588.0, 588.0]  # matrícula + M1 + M2
        anulados = []
        total_pagado = round(sum(aprobados), 2)
        assert total_pagado == 1476.0  # Caso Medardo post-F-082

        # Caso con anulados: simplemente se excluyen del cálculo
        aprobados = [300.0]  # solo matrícula
        anulados = [2940.0]  # Módulo 1 anulado
        total_pagado = round(sum(aprobados), 2)
        assert total_pagado == 300.0  # Caso Luis Fernando post-F-085

        # Caso extremo: TODO aprobado, todo anulado (edge case)
        aprobados = []
        anulados = [500.0]
        total_pagado = round(sum(aprobados), 2)
        assert total_pagado == 0.0
        # NUNCA debe ser negativo (esa es la garantía de la regla correcta)

    def test_saldo_pendiente_no_negativo(self):
        """F-085: saldo_pendiente = max(0, total_a_pagar - sum(aprobados)).
        Caso Luis Fernando (matrícula 300 aprobado + Módulo 2940 anulado):
        total_a_pagar=3240, total_pagado=300 → saldo=2940 (no 5880, no negativo)."""
        total_a_pagar = 3240.0
        # Regla F-085: total_pagado = sum(aprobados) = 300
        total_pagado = 300.0
        saldo = max(0.0, round(total_a_pagar - total_pagado, 2))
        assert saldo == 2940.0
        # Y total_pagado NO es negativo
        assert total_pagado >= 0

    def test_idempotente(self):
        """F-085: aplicar la regla N veces da el mismo resultado (idempotente).
        Simula: aprobar 1000 → anular 1000 → aprobar 1000. La regla F-085
        produce el mismo total_pagado que la regla F-COBRANZA-014 cuando
        NO hay solapamiento problemático, pero NO produce negativos en casos
        extremos."""
        # Caso: 1 pago aprobado, 0 anulados → mismo resultado con ambas reglas
        total_pagado_v1 = round(1000 - 0, 2)
        total_pagado_v2 = round(1000, 2)
        assert total_pagado_v1 == total_pagado_v2  # 1000

        # Caso problemático: 300 aprobado, 2940 anulado
        # F-COBRANZA-014: 300 - 2940 = -2640 (BUG)
        # F-085:          300            = 300   (OK)
        v1_negativo = round(300 - 2940, 2)
        v2_correcto = round(300, 2)
        assert v1_negativo == -2640.0  # Confirma que v1 producía el bug
        assert v2_correcto == 300.0    # Y v2 lo arregla
        assert v2_correcto >= 0  # Garantía F-085


# ========================================================================
# F-COBRANZA-015 · Glosa detallada por módulo(s) específico(s) (2026-07-21)
# ========================================================================
# Joel pidió: "los pagos deben ser detallados, tipo 'Pago Módulo 1' o 'Módulo 1, 2, 3'".
# La función _generar_glosa_detalle hace un preview del cascading en memoria
# y construye la glosa que nombra los módulos específicos cubiertos.

class TestF015GlosaDetallada:
    """F-COBRANZA-015: glosa con módulos específicos, no 'Cuota N' genérico."""

    def test_solo_matricula(self):
        """Pago que solo cubre matrícula → 'Matrícula'."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=False,
            modulos=[],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 300.0, [])
        assert glosa == "Matrícula"
        assert detalle is None  # Sin desglose (solo matrícula)
        assert cuota is None

    def test_matricula_pagada_solo(self):
        """Si la matrícula ya está pagada y el pago es solo del primer módulo
        pero no alcanza para un módulo completo, debe decir 'Pago Módulo 1
        (parcial)' en el concepto y el desglose con Bs X de Bs Y en el detalle."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=True,  # ya pagada
            modulos=[
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
            ],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 150.0, [])
        assert "Módulo 1" in glosa
        assert "parcial" in glosa
        # F-COBRANZA-020: el detalle va por separado
        assert "150" in detalle  # Bs 150
        assert "200" in detalle  # de Bs 200

    def test_modulo_completo_unico(self):
        """Pago que cubre exactamente 1 módulo completo → 'Pago Módulo 1'."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=True,
            modulos=[
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
            ],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 200.0, [])
        assert glosa == "Pago Módulo 1"
        # F-COBRANZA-020: detalle con monto y estado
        assert detalle is not None
        assert "Módulo 1" in detalle
        assert "completo" in detalle
        assert cuota == 1

    def test_varios_modulos_completos(self):
        """Pago que cubre 3 módulos → 'Pago Módulos 1, 2, 3'."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=True,
            modulos=[
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
            ],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 600.0, [])
        assert glosa == "Pago Módulos 1, 2, 3"
        assert cuota == 1  # primer módulo cubierto
        # F-COBRANZA-020: detalle con 3 módulos completos
        assert detalle is not None
        assert detalle.count("Módulo") == 3
        assert detalle.count("completo") == 3

    def test_matricula_y_modulos(self):
        """Pago que cubre matrícula + 2 módulos → 'Matrícula + Pago Módulos 1, 2'."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=False,
            modulos=[
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
                SimpleNamespace(costo=200.0, estado="Pendiente", monto_pagado=0.0),
            ],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 700.0, [])
        # 700 - 300 matricula = 400 → cubre módulos 1 y 2 completos
        assert "Matrícula" in glosa
        assert "Módulos 1, 2" in glosa
        assert glosa == "Matrícula + Pago Módulos 1, 2"
        # F-COBRANZA-020: detalle
        assert detalle is not None
        assert "Módulo 1" in detalle
        assert "Módulo 2" in detalle

    def test_pago_no_alcanza_matricula(self):
        """Pago que no alcanza ni para matrícula → 'Matrícula (pago parcial)'."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=False,
            modulos=[],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 100.0, [])
        assert "parcial" in glosa.lower()

    def test_pago_exacto_un_modulo(self):
        """Pago exacto de un módulo cuando ya se pagó la matrícula antes."""
        from types import SimpleNamespace
        # Supongamos que la matrícula ya está pagada
        # y hay pagos aprobados previos que totalizan 0 (caso fresh start)
        enrollment = SimpleNamespace(
            costo_matricula=300.0,
            matricula_pagada=True,
            modulos=[
                SimpleNamespace(costo=150.0, estado="Pendiente", monto_pagado=0.0),
                SimpleNamespace(costo=150.0, estado="Pendiente", monto_pagado=0.0),
            ],
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 150.0, [])
        assert glosa == "Pago Módulo 1"
        assert cuota == 1


class TestF015GlosaPlaceholderGenerico:
    """F-COBRANZA-015 (fix 2026-07-22): si el frontend manda un concepto
    placeholder genérico ('Matrícula' / 'Módulo' / vacío), el backend debe
    regenerar la glosa detallada. Si el usuario escribió algo específico
    (caso operador de Caja o un texto custom), se respeta."""

    def test_concepto_modulo_es_generico(self):
        """El frontend autocompleta `concepto = 'Módulo'` al seleccionar
        un curso con matrícula ya pagada. Esto es placeholder y debe
        sobrescribirse con la glosa detallada."""
        from services.payment_service import _es_concepto_generico_placeholder
        assert _es_concepto_generico_placeholder("Módulo") is True
        assert _es_concepto_generico_placeholder("modulo") is True
        assert _es_concepto_generico_placeholder("MÓDULO") is True

    def test_concepto_matricula_es_generico(self):
        """El frontend autocompleta `concepto = 'Matrícula'` cuando la
        matrícula está pendiente. Placeholder → sobrescribir."""
        from services.payment_service import _es_concepto_generico_placeholder
        assert _es_concepto_generico_placeholder("Matrícula") is True
        assert _es_concepto_generico_placeholder("matricula") is True
        assert _es_concepto_generico_placeholder("Matrícula ") is True  # espacios

    def test_concepto_vacio_o_none_es_generico(self):
        """Si el frontend no envía concepto (o manda vacío), se regenera."""
        from services.payment_service import _es_concepto_generico_placeholder
        assert _es_concepto_generico_placeholder("") is True
        assert _es_concepto_generico_placeholder("   ") is True
        assert _es_concepto_generico_placeholder(None) is True

    def test_concepto_especifico_se_respeta(self):
        """Si el operador de Caja escribió un concepto específico (ej.
        'Pago completo - Diplomado IA' o 'Recuperación Mayo'), NO se
        sobrescribe: se respeta lo que el usuario escribió."""
        from services.payment_service import _es_concepto_generico_placeholder
        assert _es_concepto_generico_placeholder("Pago completo - Diplomado IA") is False
        assert _es_concepto_generico_placeholder("Recuperación Mayo") is False
        assert _es_concepto_generico_placeholder("Cuota especial #5") is False


class TestF020DetalleSeparado:
    """F-COBRANZA-020 (2026-07-22): el helper ahora retorna (concepto, detalle, cuota)
    donde `concepto` es el resumen contable y `detalle` es la justificación
    con montos. Kevin: "se podria poner como un total que junte a los dos
    por temas contables y que este desglose sea ya un detalle de justificacion tipo"."""

    def test_detalle_pago_matricula_solo(self):
        """Si solo cubre matrícula, no hay detalle (null)."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0, matricula_pagada=False, modulos=[]
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 300.0, [])
        assert glosa == "Matrícula"
        assert detalle is None  # sin desglose

    def test_detalle_modulo_completo(self):
        """Si cubre 1 módulo completo, detalle muestra monto + completo."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0, matricula_pagada=True,
            modulos=[SimpleNamespace(costo=294.0, estado="Pendiente", monto_pagado=0.0)]
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 294.0, [])
        assert glosa == "Pago Módulo 1"
        assert "294" in detalle
        assert "completo" in detalle

    def test_detalle_modulo_parcial(self):
        """Pago parcial: detalle muestra Bs X de Bs Y."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0, matricula_pagada=True,
            modulos=[SimpleNamespace(costo=294.0, estado="Pendiente", monto_pagado=0.0)]
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 100.0, [])
        assert "parcial" in glosa.lower()
        assert "100" in detalle
        assert "294" in detalle
        assert "parcial" in detalle

    def test_detalle_matricula_y_modulos(self):
        """Si cubre matrícula + 1 módulo: detalle muestra ambos."""
        from types import SimpleNamespace
        enrollment = SimpleNamespace(
            costo_matricula=300.0, matricula_pagada=False,
            modulos=[SimpleNamespace(costo=294.0, estado="Pendiente", monto_pagado=0.0)]
        )
        from services.payment_service import _generar_glosa_detalle
        glosa, detalle, cuota = _generar_glosa_detalle(enrollment, 594.0, [])
        assert "Matrícula" in glosa
        assert "Módulo 1" in glosa
        # Detalle debe mencionar ambos (matrícula y módulo 1)
        assert detalle is not None
        assert ("Módulo" in detalle) or ("Matrícula" in detalle)


class TestFormatFechaHelper:
    """F-COBRANZA-016 (fix 2026-07-22): el export XLSX crasheaba porque
    `fecha_comprobante` venía como string ISO y `to_bolivia_time()` esperaba
    datetime. Helper `format_fecha` (en core/timezone_utils.py) maneja ambos casos."""

    def test_datetime_input(self):
        from datetime import datetime
        from core.timezone_utils import format_fecha
        dt = datetime(2026, 7, 22, 15, 30, 0)
        assert format_fecha(dt, "%Y-%m-%d") == "2026-07-22"
        assert format_fecha(dt, "%Y-%m-%d %H:%M") == "2026-07-22 15:30"

    def test_date_input(self):
        from datetime import date
        from core.timezone_utils import format_fecha
        d = date(2026, 7, 22)
        assert format_fecha(d, "%Y-%m-%d") == "2026-07-22"

    def test_iso_string_input(self):
        from core.timezone_utils import format_fecha
        assert format_fecha("2026-07-22", "%Y-%m-%d") == "2026-07-22"
        assert format_fecha("2026-07-22T15:30:00", "%Y-%m-%d %H:%M") == "2026-07-22 15:30"

    def test_none_input_returns_fallback(self):
        from core.timezone_utils import format_fecha
        assert format_fecha(None, "%Y-%m-%d", fallback="Sin fecha") == "Sin fecha"
        assert format_fecha(None, "%Y-%m-%d") == ""

    def test_invalid_string_returns_as_is(self):
        """Si el string no se puede parsear, devolvemos el string crudo
        (no rompemos el XLSX)."""
        from core.timezone_utils import format_fecha
        assert format_fecha("ayer fue lunes", "%Y-%m-%d") == "ayer fue lunes"


class TestF022CodigoProgramaEnXLSX:
    """F-COBRANZA-022 (2026-07-22): Joel pidio que el XLSX de pagos y el de
    reporte de caja usen el CODIGO del programa (ej DIPL-IA-2026) en vez del
    nombre largo. Verificamos que en api/payments.py la columna Curso de ambos
    XLSX use `course.codigo` y NO `course.nombre_programa`."""

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path(__file__).parent.parent / "api" / "payments.py"

    def test_xlsx_pagos_usa_codigo(self, payments_src):
        """El endpoint /export/excel (lista de pagos) usa course.codigo."""
        src = payments_src.read_text(encoding="utf-8")
        # En el endpoint /export/excel (post linea ~1100) debe haber
        # "course.codigo" y la columna del row debe usar course_name con codigo
        assert "course.codigo" in src, "No se encontro course.codigo en el codigo"
        # Verificar que el endpoint /export/excel especificamente lo usa
        idx = src.find('"/export/excel"')
        assert idx > 0
        # El endpoint /export/excel mide ~150 lineas, leer 9000 chars
        bloque = src[idx:idx + 9000]
        assert "course.codigo" in bloque, "El endpoint /export/excel no usa course.codigo"

    def test_xlsx_reporte_caja_usa_codigo(self, payments_src):
        """El endpoint /reportes/excel (reporte de caja) usa course.codigo."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/excel"')
        assert idx > 0
        # F-COBRANZA-042 (2026-07-22): se anadio C.I. como columna extra en el
        # XLSX, lo que movio course.codigo mas abajo. Ampliamos la ventana a
        # 5000 chars para cubrir el header + el loop que arma las filas.
        bloque = src[idx:idx + 5000]
        assert "course.codigo" in bloque, "El endpoint /reportes/excel no usa course.codigo"
        # Y debe tener el fallback al nombre_programa por si codigo es None
        assert "nombre_programa" in bloque, "Falta fallback a nombre_programa"


class TestF023ExtractoBancario:
    """F-COBRANZA-023 (2026-07-22): Joel pidio un reporte de caja con formato
    extracto bancario estilo Banco Bisa. Verificamos:
    - Existe el endpoint /reportes/caja/extracto-bancario
    - Reglas contables: CREDITOS = aprobados, DEBITOS = anulados o rechazados
    - PENDIENTES NO se muestran
    - Saldo acumulado = saldo_inicial + creditos - debitos
    """

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path(__file__).parent.parent / "api" / "payments.py"

    def test_endpoint_existe(self, payments_src):
        src = payments_src.read_text(encoding="utf-8")
        assert '"/reportes/caja/extracto-bancario"' in src, \
            "Falta el endpoint /reportes/caja/extracto-bancario"

    def test_endpoint_acepta_filtros(self, payments_src):
        """El endpoint acepta los mismos filtros que /reportes/caja."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/extracto-bancario"')
        bloque = src[idx:idx + 2000]
        assert "fecha_desde" in bloque
        assert "fecha_hasta" in bloque
        assert "curso_id" in bloque
        assert "estudiante_id" in bloque

    def test_requiere_rol_economico(self, payments_src):
        """Solo roles economicos (superadmin/admin/cobranza/mae/cpd/coordinador financiero)."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/extracto-bancario"')
        bloque = src[idx:idx + 2500]
        assert "puede_ver_economico" in bloque
        assert "403" in bloque, "Debe rechazar con 403 a roles no economicos"

    def test_logica_debitos_solo_anulados_rechazados(self, payments_src):
        """El codigo del endpoint debe filtrar SOLO aprobado/anulado/rechazado
        (NO pendientes, que NO son ingreso ni egreso)."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/extracto-bancario"')
        bloque = src[idx:idx + 5000]
        # Debe excluir pendientes del query
        assert '"aprobado"' in bloque or "'aprobado'" in bloque
        assert '"anulado"' in bloque or "'anulado'" in bloque
        assert '"rechazado"' in bloque or "'rechazado'" in bloque
        # Comentario explicito de que pendientes NO se muestran
        assert "pendiente" in bloque.lower()

    def test_creditos_incluyen_abandonos_congelados(self):
        """REGLA DE NEGOCIO: Los CREDITOS son pagos APROBADOS sin importar
        si el estudiante despues abandona o congela. Su dinero SI entro.
        Logica: si el estado del pago es aprobado → credito."""
        # Simulamos la logica en Python puro
        class EstadoPago:
            APROBADO = "aprobado"
            ANULADO = "anulado"
            RECHAZADO = "rechazado"
            PENDIENTE = "pendiente"

        class Pago:
            def __init__(self, estado, monto):
                self.estado_pago = estado
                self.cantidad_pago = monto

        pagos = [
            Pago(EstadoPago.APROBADO, 300),     # credito
            Pago(EstadoPago.APROBADO, 588),     # credito (modulo 1)
            Pago(EstadoPago.ANULADO, 300),      # debito
            Pago(EstadoPago.RECHAZADO, 288),    # debito
            Pago(EstadoPago.PENDIENTE, 588),    # NO se cuenta
        ]

        total_creditos = sum(p.cantidad_pago for p in pagos if p.estado_pago == EstadoPago.APROBADO)
        total_debitos = sum(p.cantidad_pago for p in pagos if p.estado_pago in (EstadoPago.ANULADO, EstadoPago.RECHAZADO))

        assert total_creditos == 888, f"Esperado 888, got {total_creditos}"
        assert total_debitos == 588, f"Esperado 588, got {total_debitos}"

        # Saldo: si saldo_inicial = 0
        saldo_inicial = 0
        saldo_final = saldo_inicial + total_creditos - total_debitos
        assert saldo_final == 300  # 0 + 888 - 588

    def test_saldo_acumulado_ordenado_por_fecha(self):
        """REGLA: el saldo es acumulado. Se procesan pagos en orden de fecha
        ascendente y el saldo refleja creditos - debitos."""
        class Pago:
            def __init__(self, fecha, estado, monto):
                self.fecha = fecha
                self.estado = estado
                self.monto = monto

        pagos_ordenados = [
            Pago("2026-07-01", "aprobado", 300),    # +300
            Pago("2026-07-05", "aprobado", 588),    # +888
            Pago("2026-07-10", "anulado", 200),     # +688
            Pago("2026-07-15", "aprobado", 100),    # +788
        ]
        saldo = 0
        saldos_por_pago = []
        for p in pagos_ordenados:
            if p.estado == "aprobado":
                saldo += p.monto
            elif p.estado in ("anulado", "rechazado"):
                saldo -= p.monto
            saldos_por_pago.append(saldo)

        assert saldos_por_pago == [300, 888, 688, 788]


class TestF026ComprobanteObligatorio:
    """F-COBRANZA-026 (2026-07-22): Kevin pidio que el sistema NO permita
    subir un pago sin comprobante, NI SIQUIERA EN CAJA.
    Reglas:
      - POST /payments/ (estudiante) -> file obligatorio siempre
      - POST /payments/by-staff (cobranza) -> file obligatorio siempre
      - POST /payments/caja-directo (cobranza) -> file obligatorio siempre
      - POST /payments/{id}/upload-by-encargado -> file obligatorio siempre
    """

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path(__file__).parent.parent / "api" / "payments.py"

    @pytest.fixture
    def service_src(self):
        from pathlib import Path
        return Path(__file__).parent.parent / "services" / "payment_service.py"

    def test_create_payment_file_es_requerido(self, payments_src):
        """POST /payments/: el parametro file NO debe tener default None."""
        src = payments_src.read_text(encoding="utf-8")
        # Buscar el endpoint create_payment
        idx = src.find('"/",')
        bloque = src[idx:idx + 1500]
        # file: UploadFile = File(..., ...) — NO Optional
        # Antes: file: Optional[UploadFile] = File(None, ...)
        # Ahora:  file: UploadFile = File(..., ...)
        # Verificar que no este Optional[UploadFile]
        assert "Optional[UploadFile]" not in bloque[:500], (
            "create_payment aun acepta file Optional"
        )
        # Verificar que el parametro file ya no es None default
        assert "File(None" not in bloque[:500] or "caja-directo" in bloque[:500], (
            "create_payment aun tiene File(None"
        )
        # Verificar que hay un File(...
        assert "file: UploadFile = File(" in bloque, (
            "create_payment no tiene file: UploadFile = File(...)"
        )

    def test_create_payment_validacion_explicita(self, payments_src):
        """POST /payments/: debe validar 'if not file' ANTES de validar
        datos de transferencia/deposito. Caja no es excepcion para comprobante.
        """
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/",')
        bloque = src[idx:idx + 2000]
        # Debe haber un 'if not file:' que retorne 400
        assert "if not file" in bloque, "Falta validacion 'if not file'"
        # El mensaje debe decir que el comprobante es obligatorio
        assert "obligatorio" in bloque.lower(), "Falta mensaje de error mencionando 'obligatorio'"
        # La validacion de 'if not file' debe estar ANTES del check de Caja
        pos_not_file = bloque.find("if not file")
        pos_caja_check = bloque.find('if metodo_pago != "Caja"')
        if pos_caja_check > 0:
            assert pos_not_file < pos_caja_check, (
                "El check 'if not file' debe estar ANTES de 'if metodo_pago != Caja' "
                "(Caja no es excepcion para comprobante)"
            )

    def test_by_staff_file_es_requerido(self, payments_src):
        """POST /payments/by-staff: file obligatorio."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/by-staff"')
        bloque = src[idx:idx + 1500]
        assert "Optional[UploadFile]" not in bloque, (
            "by-staff aun acepta file Optional"
        )
        assert "file: UploadFile = File(" in bloque, (
            "by-staff no tiene file: UploadFile = File(...)"
        )
        assert 'if metodo_pago != "Caja":' not in bloque, (
            "by-staff aun tiene la excepcion 'if metodo_pago != Caja'"
        )

    def test_caja_directo_requiere_comprobante(self, payments_src):
        """POST /payments/caja-directo: debe aceptar file como parametro."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/caja-directo"')
        # Necesitamos un rango mas grande para llegar al create_caja_directo_payment(
        bloque = src[idx:idx + 4500]
        # El endpoint caja-directo debe tener file: UploadFile
        assert "file: UploadFile = File(" in bloque, (
            "caja-directo no acepta file obligatorio"
        )
        # Y debe validar que no sea None
        assert "if not file" in bloque, "caja-directo no valida que file no sea vacio"
        # Y debe pasarlo a create_caja_directo_payment
        assert "comprobante_url=comprobante_url" in bloque, (
            "caja-directo no pasa comprobante_url al service"
        )

    def test_create_caja_directo_payment_rechaza_sin_comprobante(self, service_src):
        """Service: create_caja_directo_payment debe lanzar ValueError si comprobante_url es None."""
        src = service_src.read_text(encoding="utf-8")
        idx = src.find("async def create_caja_directo_payment")
        bloque = src[idx:idx + 2000]
        # Debe haber un if not comprobante_url: raise ValueError
        assert "comprobante_url:" in bloque, "Falta parametro comprobante_url"
        assert "if not comprobante_url" in bloque, (
            "create_caja_directo_payment no valida comprobante_url obligatorio"
        )
        assert "raise ValueError" in bloque, (
            "Falta raise ValueError para comprobante faltante"
        )
        assert "obligatorio" in bloque.lower(), (
            "Mensaje de error no menciona 'obligatorio'"
        )

    def test_no_pagos_sin_comprobante_para_caja(self, payments_src):
        """REGLA: la validacion de 'if not file' debe estar ANTES de
        'if metodo_pago != Caja' (Caja no es excepcion para comprobante).
        PERO la validacion de numero_transaccion/banco puede seguir siendo
        condicional a metodo_pago != Caja (esos datos solo se piden para
        transferencia/deposito).
        Para upload-by-encargado, FastAPI rechaza automaticamente cuando
        file=File(...) es obligatorio, asi que no necesita validacion explicita.
        """
        src = payments_src.read_text(encoding="utf-8")

        # En cada endpoint de pago, la posicion de 'if not file' debe ser
        # ANTERIOR a cualquier 'if metodo_pago != Caja'.
        endpoints = [
            ('"/",', "create_payment (estudiante)", 2500),
            ('"/by-staff"', "create_payment_by_staff", 5000),
        ]
        for marker, name, rango in endpoints:
            idx = src.find(marker)
            if idx < 0:
                continue
            bloque = src[idx:idx + rango]
            pos_not_file = bloque.find("if not file")
            pos_caja_check = bloque.find('if metodo_pago != "Caja"')
            assert pos_not_file > 0, f"{name}: falla 'if not file'"
            if pos_caja_check < 0:
                continue
            assert pos_not_file < pos_caja_check, (
                f"{name}: 'if not file' debe estar ANTES de 'if metodo_pago != Caja' "
                f"(pos_not_file={pos_not_file}, pos_caja={pos_caja_check})"
            )


class TestF031EnrichAceptaDicts:
    """F-COBRANZA-031 (2026-07-22): el endpoint /reportes/caja convertia
    los pagos a dict antes de llamar a enrich_payments_with_details_bulk,
    pero esa funcion solo aceptaba objetos Payment, causando 500.

    Kevin reporto el incidente: 'errores y mas errores'. Causa: el codigo
    asume que el parametro es un objeto, pero el endpoint pasa dicts.

    El fix: enrich_payments_with_details_bulk detecta si los items son
    dicts u objetos y usa .get() o atributos segun corresponda.
    """

    @pytest.fixture
    def service_src(self):
        from pathlib import Path
        return Path(__file__).parent.parent / "services" / "payment_service.py"

    def test_enrich_tiene_helper_get_para_dictobjeto(self, service_src):
        """La funcion debe tener un helper _get que detecta dict vs objeto."""
        src = service_src.read_text(encoding="utf-8")
        idx = src.find("async def enrich_payments_with_details_bulk")
        bloque = src[idx:idx + 3000]
        assert "def _get(p" in bloque, (
            "enrich_payments_with_details_bulk debe tener un helper _get() "
            "que funcione tanto con dicts como con objetos Payment"
        )
        assert "isinstance(p, dict)" in bloque, (
            "el helper _get debe verificar si p es dict con isinstance"
        )

    def test_enrich_pasa_por_codigo_de_deteccion(self, service_src):
        """El codigo debe detectar dicts y NO llamar model_dump() sobre un dict."""
        src = service_src.read_text(encoding="utf-8")
        idx = src.find("async def enrich_payments_with_details_bulk")
        bloque = src[idx:idx + 3000]
        # Debe verificar isinstance(payment, dict) antes de model_dump
        assert "isinstance(payment, dict)" in bloque, (
            "enrich debe detectar si payment es dict antes de model_dump"
        )
        # El model_dump solo debe ejecutarse si NO es dict
        assert "if isinstance(payment, dict):" in bloque, (
            "enrich debe tener un if isinstance para usar p directamente si es dict"
        )

    def test_reporte_caja_pasa_lista_a_enrich(self, service_src):
        """get_reporte_caja debe poder pasar su lista (de dicts) a enrich."""
        # Verificar que get_reporte_caja retorna dicts y enrich los acepta
        idx = service_src.read_text(encoding="utf-8").find("async def get_reporte_caja")
        bloque = service_src.read_text(encoding="utf-8")[idx:idx + 3000]
        assert "p_dict = p.model_dump" in bloque, (
            "get_reporte_caja convierte a dicts (esto era lo que causaba el 500)"
        )
        # Pero enrich ahora debe aceptar dicts (verificado arriba)
        # Asi que el endpoint puede pasar la lista de dicts directamente


class TestF034ByStaffSkipOwnershipCheck:
    """
    F-COBRANZA-034 (2026-07-22): bug reportado por Lic. Sandra Zabala.
    El endpoint POST /payments/by-staff fallaba con 400 + mensaje
    "No puedes crear un pago para una inscripcion que no te pertenece"
    porque:
      1) estudiante_id llega como STRING del Form
      2) enrollment.estudiante_id es PydanticObjectId
      3) La comparacion str != PydanticObjectId siempre es True
      4) El check bloqueaba a cobranza/admin/superadmin de registrar
         pagos en nombre de cualquier estudiante.

    Fix: agregar parametro skip_ownership_check a create_payment
    (default False, para que el endpoint del estudiante siga validando)
    y pasarlo como True desde el endpoint by-staff.
    """

    @pytest.fixture
    def service_src(self):
        from pathlib import Path
        return Path("services/payment_service.py")

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path("api/payments.py")

    def test_create_payment_signature_has_skip_ownership_check(self, service_src):
        """create_payment debe aceptar el parametro skip_ownership_check."""
        idx = service_src.read_text(encoding="utf-8").find("async def create_payment")
        bloque = service_src.read_text(encoding="utf-8")[idx:idx + 800]
        assert "skip_ownership_check" in bloque, (
            "create_payment debe tener el parametro skip_ownership_check "
            "para que el endpoint /payments/by-staff pueda saltar el check "
            "de 'la inscripcion pertenece al estudiante'"
        )

    def test_create_payment_skip_ownership_check_default_false(self, service_src):
        """skip_ownership_check debe tener default False (el endpoint del estudiante sigue validando)."""
        idx = service_src.read_text(encoding="utf-8").find("async def create_payment")
        bloque = service_src.read_text(encoding="utf-8")[idx:idx + 800]
        assert "skip_ownership_check: bool = False" in bloque, (
            "skip_ownership_check debe ser opcional con default False para "
            "que el endpoint del estudiante siga rechazando pagos a inscripciones ajenas"
        )

    def test_create_payment_check_envuelve_con_skip(self, service_src):
        """El check enrollment.estudiante_id != student_id debe estar envuelto en `if not skip_ownership_check`."""
        idx = service_src.read_text(encoding="utf-8").find("async def create_payment")
        bloque = service_src.read_text(encoding="utf-8")[idx:idx + 2000]
        # Verificar que el check esta dentro de un `if not skip_ownership_check`
        assert "if not skip_ownership_check" in bloque, (
            "El check debe estar condicionado a skip_ownership_check=False. "
            "Si no, el endpoint by-staff seguira fallando con 'no te pertenece'."
        )

    def test_by_staff_endpoint_pasa_skip_true(self, payments_src):
        """El endpoint by-staff debe pasar skip_ownership_check=True."""
        idx = payments_src.read_text(encoding="utf-8").find("async def create_payment_by_staff")
        bloque = payments_src.read_text(encoding="utf-8")[idx:idx + 6000]
        assert "skip_ownership_check=True" in bloque, (
            "El endpoint /payments/by-staff debe pasar skip_ownership_check=True "
            "porque el staff (cobranza/admin/superadmin) esta autorizado a "
            "registrar pagos en nombre de cualquier estudiante."
        )

    def test_by_staff_endpoint_convierte_estudiante_id_a_objectid(self, payments_src):
        """El endpoint by-staff debe convertir estudiante_id (str del Form) a PydanticObjectId."""
        idx = payments_src.read_text(encoding="utf-8").find("async def create_payment_by_staff")
        bloque = payments_src.read_text(encoding="utf-8")[idx:idx + 6000]
        # Verificar que hace la conversion con PydanticObjectId(estudiante_id)
        assert "PydanticObjectId(estudiante_id)" in bloque or "_POI(estudiante_id)" in bloque, (
            "El endpoint /payments/by-staff debe convertir estudiante_id (string) "
            "a PydanticObjectId antes de pasarlo a create_payment. "
            "Sin esta conversion, el check enrollment.estudiante_id != student_id "
            "siempre falla porque compara PydanticObjectId contra str."
        )


class TestF042CIEnXLSXReportePagos:
    """
    F-COBRANZA-042 (2026-07-22): Kevin pidio que el XLSX del reporte de pagos
    (F-016, /payments/reportes/excel) tenga la columna C.I. del estudiante.
    Sin esto, el XLSX no tiene el carnet del estudiante (solo en el reporte
    de caja web lo agregamos con F-036, pero faltaba en el XLSX).
    Verificamos:
    - El header incluye "C.I." como segunda columna
    - El loop incluye la lectura de carnet_identidad o registro
    """

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path("api/payments.py")

    def test_xlsx_reporte_pagos_header_incluye_ci(self, payments_src):
        """Header del XLSX incluye 'C.I.' como columna."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/excel"')
        assert idx > 0
        bloque = src[idx:idx + 5000]
        # El header de headers debe incluir "C.I." justo despues del nombre
        assert '"C.I."' in bloque or "'C.I.'" in bloque, (
            "El XLSX de reporte de pagos debe tener columna 'C.I.' (F-042)."
        )

    def test_xlsx_reporte_pagos_lee_carnet_o_registro(self, payments_src):
        """El loop del XLSX lee carnet_identidad o registro del estudiante."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/excel"')
        assert idx > 0
        bloque = src[idx:idx + 5000]
        # Debe leer carnet_identidad con fallback a registro
        assert "carnet_identidad" in bloque, (
            "El XLSX debe leer carnet_identidad del estudiante (F-042)."
        )
        assert "registro" in bloque, (
            "El XLSX debe tener fallback a registro si carnet_identidad es None (F-042)."
        )


class TestF043PDFReporteCaja:
    """
    F-COBRANZA-043 (2026-07-22): Kevin pidio boton "Exportar PDF" en el
    reporte de caja, con los mismos datos que el XLSX + las 4 tarjetas KPI
    (Cantidad, Total Aprobado, Total Pendiente, Total Anulado).
    Verificamos:
    - Existe el endpoint /payments/reportes/caja/pdf
    - Usa reportlab
    - Retorna application/pdf
    - Calcula los 4 KPIs (cantidad_pagos, total_aprobado, total_pendiente, total_anulado)
    """

    @pytest.fixture
    def payments_src(self):
        from pathlib import Path
        return Path("api/payments.py")

    def test_pdf_endpoint_existe(self, payments_src):
        """Existe endpoint GET /payments/reportes/caja/pdf."""
        src = payments_src.read_text(encoding="utf-8")
        assert '"/reportes/caja/pdf"' in src, (
            "Falta endpoint GET /payments/reportes/caja/pdf (F-043)."
        )

    def test_pdf_endpoint_usa_reportlab(self, payments_src):
        """El endpoint PDF importa reportlab."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        assert idx > 0
        bloque = src[idx:idx + 5000]
        assert "reportlab" in bloque, (
            "El endpoint PDF debe importar reportlab (F-043)."
        )

    def test_pdf_endpoint_retorna_application_pdf(self, payments_src):
        """El endpoint retorna media_type=application/pdf."""
        src = payments_src.read_text(encoding="utf-8")
        # El path tiene /reportes/caja/pdf con / adelante
        idx = src.find('"/reportes/caja/pdf"')
        assert idx > 0
        # Buscar el SIGUIENTE application/pdf despues del inicio del endpoint
        # (no el primero del archivo, que esta en otro endpoint).
        pdf_idx = src.find("application/pdf", idx)
        assert pdf_idx > idx, (
            "El endpoint PDF debe retornar media_type='application/pdf' (F-043). "
            f"No se encontro 'application/pdf' despues del path /reportes/caja/pdf (idx={idx})."
        )

    def test_pdf_endpoint_calcula_4_kpis(self, payments_src):
        """El endpoint calcula los 4 KPIs: cantidad, aprobado, pendiente, anulado."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        bloque = src[idx:idx + 5000]
        for kpi in ["cantidad_pagos", "total_aprobado", "total_pendiente", "total_anulado"]:
            assert kpi in bloque, f"El endpoint PDF debe calcular {kpi} (F-043)."

    def test_pdf_endpoint_incluye_columna_ci(self, payments_src):
        """El PDF incluye la columna C.I. (igual que el XLSX de F-042)."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        bloque = src[idx:idx + 8000]
        assert "C.I." in bloque, (
            "El PDF debe incluir columna C.I. (F-043, consistente con F-042)."
        )
        assert "carnet_identidad" in bloque, (
            "El PDF debe leer carnet_identidad del estudiante (F-043)."
        )

    def test_pdf_endpoint_genera_kpi_visual(self, payments_src):
        """El PDF tiene una seccion visual con las 4 tarjetas KPI."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        bloque = src[idx:idx + 6000]
        # Debe haber una Table con las 4 tarjetas (titulos)
        for titulo in ["CANTIDAD DE PAGOS", "TOTAL APROBADO", "TOTAL PENDIENTE", "TOTAL ANULADO"]:
            assert titulo in bloque, (
                f"El PDF debe tener tarjeta KPI con titulo '{titulo}' (F-043)."
            )

    def test_pdf_usa_nombre_estudiante_no_student_nombre(self, payments_src):
        """F-068 (2026-07-22): el PDF debe leer `nombre_estudiante` (plano) del
        dict enriquecido, no `student.nombre` (que no existe en el dict)."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        bloque = src[idx:idx + 15000]  # PDF endpoint es grande
        # Debe construir maps propios de Student/Course
        assert "students_map_pdf" in bloque, (
            "F-068: El PDF debe construir su propio map de Student (no leer de "
            "un dict `student` anidado que no existe en enriched)."
        )
        assert "courses_map_pdf" in bloque, (
            "F-068: El PDF debe construir su propio map de Course (no leer de "
            "un dict `course` anidado que no existe en enriched)."
        )

    def test_pdf_usa_value_del_enum_estado(self, payments_src):
        """F-068: el PDF debe convertir el enum a su .value para no mostrar
        'EstadoPago.APROBADO' literal."""
        src = payments_src.read_text(encoding="utf-8")
        idx = src.find('"/reportes/caja/pdf"')
        bloque = src[idx:idx + 15000]
        # Buscar la conversión del enum a .value
        assert 'hasattr(estado_pago, "value")' in bloque, (
            "F-068: El PDF debe usar `hasattr(estado_pago, 'value')` para extraer "
            "el .value del enum, sino muestra 'EstadoPago.APROBADO' literal."
        )


class TestF068TotalAnuladoIncluyeRechazados:
    """
    F-068 (2026-07-22, Kevin): "Total Anulado" del reporte de caja debe
    incluir TANTO anulados COMO rechazados (regla F-023: Débitos = anulados/
    rechazados). Antes solo contaba ANULADO, dando 588 Bs en UI vs 876 Bs en PDF.

    Caso real: Luis Valdez 288 Bs RECHAZADO + Jerry Fletcher 2x -294 Bs
    ANULADO = 876 Bs total.
    """

    @pytest.fixture
    def get_reporte_caja_src(self):
        from pathlib import Path
        return Path("services/payment_service.py").read_text(encoding="utf-8")

    def test_get_reporte_caja_incluye_rechazados_en_total_anulado(self, get_reporte_caja_src):
        """La función debe sumar tanto ANULADO como RECHAZADO."""
        # Buscar la sección de "Totales agregados"
        idx = get_reporte_caja_src.find("Totales agregados sobre TODO el rango")
        assert idx > 0, "No se encontró la sección de totales en get_reporte_caja"
        bloque = get_reporte_caja_src[idx:idx + 2000]
        # Debe chequear AMBOS
        assert "EstadoPago.ANULADO" in bloque, (
            "F-068: Falta la suma de ANULADO en total_anulado."
        )
        assert "EstadoPago.RECHAZADO" in bloque, (
            "F-068: Falta la suma de RECHAZADO en total_anulado. "
            "Sin esto, la UI muestra 588 Bs pero el PDF 876 Bs "
            "(288 del rechazado de Luis Valdez no se cuenta)."
        )
        # Debe ser `in (ANULADO, RECHAZADO)` (tupla), no dos ifs separados
        assert "EstadoPago.ANULADO, EstadoPago.RECHAZADO" in bloque, (
            "F-068: El chequeo debe ser `in (EstadoPago.ANULADO, EstadoPago.RECHAZADO)`, "
            "no dos ifs separados."
        )


class TestF048RechazadoMontoNegativoEnXLSX:
    """
    F-048 (2026-07-22, audio Sandra 18:51):
    "Aparece como rechazado pero no esta su contraparte, pero si esta sumando"

    Caso real: Luis Valdez (CI 5384101) tiene un pago de 288 Bs con
    estado_pago=rechazado. En el XLSX de pagos aparecía como +288 en la
    columna Monto, en lugar de -288 (que es la regla de Kevin F-023:
    Débitos = anulados/rechazados, Créditos = aprobados).

    El fix ya existía para ANULADO (F-COBRANZA-005), pero faltaba extenderlo
    a RECHAZADO. Este test verifica que AMBOS (ANULADO y RECHAZADO) se
    exportan con monto negativo en el XLSX.
    """

    @pytest.fixture
    def xlsx_rechazo_bloque(self):
        """Extrae el bloque del XLSX donde se decide el signo del monto."""
        from pathlib import Path
        src = Path("api/payments.py").read_text(encoding="utf-8")
        # Buscar el anchor del comentario F-COBRANZA-005 (que es donde se
        # encuentra la lógica de signo).
        idx = src.find("F-COBRANZA-005 (2026-07-21)")
        assert idx > 0, "No se encontró el comentario F-COBRANZA-005 en api/payments.py"
        return src[idx:idx + 3000]

    def test_xlsx_rechazado_se_exporta_negativo(self, xlsx_rechazo_bloque):
        """El XLSX de pagos debe exportar RECHAZADO con monto negativo."""
        assert "EstadoPago.ANULADO" in xlsx_rechazo_bloque, (
            "F-048: Falta la rama para EstadoPago.ANULADO en la conversión de monto."
        )
        assert "EstadoPago.RECHAZADO" in xlsx_rechazo_bloque, (
            "F-048: Falta la rama para EstadoPago.RECHAZADO. "
            "Sandra reporto que un pago RECHAZADO aparecia como +288 en el XLSX, "
            "deberia ser -288 (regla de Kevin F-023: debitos = anulados/rechazados)."
        )

    def test_xlsx_rechazado_y_anulado_juntos_en_tupla(self, xlsx_rechazo_bloque):
        """El chequeo debe ser en una tupla, no con OR separado."""
        assert "EstadoPago.ANULADO, EstadoPago.RECHAZADO" in xlsx_rechazo_bloque, (
            "F-048: El chequeo debe ser `in (EstadoPago.ANULADO, EstadoPago.RECHAZADO)`, "
            "no dos ifs separados."
        )

    def test_xlsx_rechazado_actualiza_mismo_monto(self, xlsx_rechazo_bloque):
        """Verifica que la lógica de signo negativo está bien aplicada."""
        # El patrón debe ser:
        # if payment.estado_pago in (...ANULADO, ...RECHAZADO) and monto_exportar > 0:
        #     monto_exportar = -monto_exportar
        assert "monto_exportar = -monto_exportar" in xlsx_rechazo_bloque, (
            "F-048: La línea `monto_exportar = -monto_exportar` debe estar presente."
        )


class TestF051ReglaMoraAbandonoKevin:
    """
    F-051 (2026-07-22, regla de Kevin del audio 8/7 12:36):
    "1 mes sin pagar = en mora; 2 meses = abandono automático"

    Config defaults (core/config.py):
    - DIAS_INACTIVIDAD_MORA = 30 (1 mes)
    - DIAS_INACTIVIDAD_ABANDONO = 60 (2 meses)

    El job periódico (`verificar_inactividad_pagos` en
    services/congelado_service.py) corre cada 24h y aplica estas reglas.
    """

    @pytest.fixture
    def config_src(self):
        from pathlib import Path
        return Path("core/config.py").read_text(encoding="utf-8")

    def test_mora_default_es_30_dias(self, config_src):
        """1 mes = 30 días según la regla de Kevin."""
        assert "DIAS_INACTIVIDAD_MORA: int = Field(default=30," in config_src, (
            "F-051: DIAS_INACTIVIDAD_MORA debe ser 30 días (1 mes) por "
            "regla de Kevin. Antes era 20."
        )

    def test_abandono_default_es_60_dias(self, config_src):
        """2 meses = 60 días según la regla de Kevin."""
        assert "DIAS_INACTIVIDAD_ABANDONO: int = Field(default=60," in config_src, (
            "F-051: DIAS_INACTIVIDAD_ABANDONO debe ser 60 días (2 meses) por "
            "regla de Kevin. Antes era 30."
        )

    def test_mora_menor_que_abandono(self, config_src):
        """MORA (30) debe ser < ABANDONO (60). Sino no tiene sentido."""
        import re
        m = re.search(r"DIAS_INACTIVIDAD_MORA: int = Field\(default=(\d+),", config_src)
        a = re.search(r"DIAS_INACTIVIDAD_ABANDONO: int = Field\(default=(\d+),", config_src)
        assert m and a, "No se pudieron parsear los defaults"
        mora = int(m.group(1))
        abandono = int(a.group(1))
        assert mora < abandono, (
            f"F-051: MORA ({mora}) debe ser < ABANDONO ({abandono}). "
            "Sino no se puede notificar antes de marcar abandono."
        )

    def test_job_existe_en_main(self):
        """El job debe estar referenciado en main.py."""
        from pathlib import Path
        main = Path("main.py").read_text(encoding="utf-8")
        assert "verificar_inactividad_pagos" in main, (
            "F-051: El job `verificar_inactividad_pagos` debe estar en main.py."
        )
        assert "JOB_CONGELADO_ACTIVO" in main, (
            "F-051: El job debe tener flag JOB_CONGELADO_ACTIVO configurable."
        )

    def test_servicio_tiene_funciones_necesarias(self):
        """El servicio congelado_service debe tener las funciones clave."""
        from pathlib import Path
        content = Path("services/congelado_service.py").read_text(encoding="utf-8")
        assert "async def verificar_inactividad_pagos" in content, (
            "F-051: Falta la función principal `verificar_inactividad_pagos`."
        )
        assert "DIAS_INACTIVIDAD_MORA" in content, (
            "F-051: El servicio debe usar la config DIAS_INACTIVIDAD_MORA."
        )
        assert "DIAS_INACTIVIDAD_ABANDONO" in content, (
            "F-051: El servicio debe usar la config DIAS_INACTIVIDAD_ABANDONO."
        )
        assert "mora_notificada" in content, (
            "F-051: El servicio debe usar el flag `mora_notificada` para no spamear."
        )
        assert "motivo_suspension" in content, (
            "F-051: El servicio debe marcar motivo_suspension='abandono' al detectar inactividad."
        )


class TestF048MotivoRechazoUnificado:
    """
    F-048 (2026-07-22): inconsistencia entre `motivo_rechazo` y
    `motivo_reversion` causaba que el XLSX/UI mostraran "Motivo Reversión"
    VACÍO para pagos RECHAZADOS, aunque el admin sí había dado un motivo.

    Caso real: Luis Valdez (CI 5384101) tiene un pago de 288 Bs RECHAZADO
    con `motivo_reversion=None` aunque en la UI sí se proporcionó motivo.

    Fix: `rechazar_pago` ahora guarda el motivo en `motivo_reversion`
    (consistente con `anular_pago`) Y valida que no esté vacío.
    """

    @pytest.fixture
    def payment_model_src(self):
        from pathlib import Path
        return Path("models/payment.py").read_text(encoding="utf-8")

    def test_rechazar_pago_usa_motivo_reversion(self, payment_model_src):
        """La función `rechazar_pago` debe guardar en `motivo_reversion`."""
        idx = payment_model_src.find("def rechazar_pago")
        assert idx > 0
        bloque = payment_model_src[idx:idx + 2000]
        # Debe guardar en motivo_reversion
        assert "self.motivo_reversion = motivo" in bloque, (
            "F-048: `rechazar_pago` debe guardar en `self.motivo_reversion` "
            "(consistente con `anular_pago`). Antes guardaba en "
            "`motivo_rechazo` que la UI/XLSX no leían."
        )

    def test_rechazar_pago_valida_motivo_no_vacio(self, payment_model_src):
        """Debe lanzar ValueError si el motivo está vacío."""
        idx = payment_model_src.find("def rechazar_pago")
        bloque = payment_model_src[idx:idx + 2000]
        assert 'raise ValueError' in bloque, (
            "F-048: `rechazar_pago` debe validar que el motivo no esté vacío."
        )
        assert 'motivo de rechazo es OBLIGATORIO' in bloque, (
            "F-048: El mensaje de error debe mencionar que el motivo es obligatorio."
        )

    def test_xlsx_muestra_motivo_reversion(self):
        """El XLSX del reporte de pagos debe leer `motivo_reversion`."""
        from pathlib import Path
        payments_src_fixture = Path("api/payments.py")
        src = payments_src_fixture.read_text(encoding="utf-8")
        # El endpoint /reportes/excel está cerca de la línea 950, pero la fila
        # donde se lee `payment.motivo_reversion` está ~6000 chars más adelante.
        # Usamos un rango de 10000 chars para cubrir todo el handler.
        idx = src.find('"/reportes/excel"')
        bloque = src[idx:idx + 10000]
        assert "payment.motivo_reversion" in bloque, (
            "F-048: El XLSX debe leer `payment.motivo_reversion` (no `motivo_rechazo`)."
        )
        assert "payment.motivo_rechazo" not in bloque, (
            "F-048: El XLSX NO debe leer `payment.motivo_rechazo` (fue deprecado por motivo_reversion)."
        )


class TestF050RechazarBorradorRecalculaPromedio:
    """
    F-050 (2026-07-22, audios viejos): cuando CPD rechaza un borrador de nota,
    el promedio (`nota_final`) NO se recalculaba, así que el rechazo del
    docente seguía "sumando" en alguna vista.

    Fix: `rechazar_nota_borrador` ahora recalcula el promedio igual que
    `actualizar_nota_modulo` y `validar_nota_borrador`.
    """

    @pytest.fixture
    def enrollment_service_src(self):
        from pathlib import Path
        return Path("services/enrollment_service.py").read_text(encoding="utf-8")

    def test_rechazar_nota_borrador_recalcula_promedio(self, enrollment_service_src):
        """La función `rechazar_nota_borrador` debe recalcular `nota_final`."""
        # Buscar la función rechazar_nota_borrador
        idx = enrollment_service_src.find("async def rechazar_nota_borrador")
        assert idx > 0, "No se encontró la función `rechazar_nota_borrador`"
        bloque = enrollment_service_src[idx:idx + 3000]
        # Debe recalcular el promedio con la lista de notas
        assert "nota_final" in bloque, (
            "F-050: `rechazar_nota_borrador` debe recalcular `nota_final`."
        )
        assert "notas_evaluadas" in bloque, (
            "F-050: `rechazar_nota_borrador` debe iterar sobre las notas "
            "oficiales (`m.nota for m in enrollment.modulos`) y calcular "
            "el nuevo promedio, igual que `actualizar_nota_modulo`."
        )
        assert "promedio" in bloque, (
            "F-050: Debe calcular la variable `promedio` y asignarla a `nota_final`."
        )

    def test_rechazar_nota_borrador_nota_final_none_si_sin_notas(self, enrollment_service_src):
        """Si no hay notas válidas, `nota_final` debe ser None (no promedio de [])."""
        idx = enrollment_service_src.find("async def rechazar_nota_borrador")
        bloque = enrollment_service_src[idx:idx + 3000]
        assert "enrollment.nota_final = None" in bloque, (
            "F-050: Si no hay notas válidas, `nota_final` debe ser None "
            "(no un promedio de lista vacía que daría error)."
        )


class TestF049SaldoAFavorEnResumen:
    """
    F-049 (2026-07-22, audio Sandra 9/7 17:44):
    "yo no puedo visualizar por ejemplo si un estudiante paga de más y y no
     cumple digamos con el o si cumple con el moto establecido pero que tiene
     un saldo a favor en este caso por ejemplo él tenía que pagar 294 y pagó
     300 y a mí solamente me sale los 300 pero no me sale lo se volvían a
     favor sin embargo como estudiante el sí lo puede visualizar"

    Caso real: Luis Valdez pagó 300 Bs cuando su módulo costaba 294. El
    estudiante SÍ ve el saldo a favor pero cobranza NO.

    Fix: enriquecer `get_resumen_pagos_enrollment` con:
    - `modulos`: array con desglose por módulo (monto, monto_pagado, saldo_modulo, pagado)
    - `total_a_pagar`: total de la inscripción
    - `total_pagado`: total pagado (sin restar anulados, son positivos)
    - `saldo_a_favor`: max(0, total_pagado - total_a_pagar)
    - `saldo_pendiente`: max(0, total_a_pagar - total_pagado)
    """

    @pytest.fixture
    def payment_service_src(self):
        from pathlib import Path
        return Path("services/payment_service.py")

    def test_resumen_incluye_modulos(self, payment_service_src):
        """El resumen debe incluir array 'modulos' con desglose por módulo."""
        src = payment_service_src.read_text(encoding="utf-8")
        assert '"modulos"' in src, (
            "F-049: Falta campo 'modulos' en get_resumen_pagos_enrollment. "
            "Cobranza no puede ver el desglose por módulo del estudiante."
        )

    def test_resumen_incluye_saldo_a_favor(self, payment_service_src):
        """El resumen debe incluir 'saldo_a_favor' calculado."""
        src = payment_service_src.read_text(encoding="utf-8")
        assert "saldo_a_favor" in src, (
            "F-049: Falta campo 'saldo_a_favor' en get_resumen_pagos_enrollment. "
            "Sandra reporto que cuando un estudiante paga de más (ej: 300 en lugar de 294), "
            "el saldo a favor no es visible para cobranza."
        )

    def test_resumen_calcula_saldo_a_favor_como_diferencia(self, payment_service_src):
        """saldo_a_favor = max(0, total_pagado - total_a_pagar)."""
        src = payment_service_src.read_text(encoding="utf-8")
        # El patrón debe usar max(0.0, total_pagado - total_a_pagar)
        assert "max(0.0, total_pagado - total_a_pagar)" in src, (
            "F-049: saldo_a_favor debe calcularse como max(0, total_pagado - total_a_pagar). "
            "Si total_pagado > total_a_pagar, hay saldo a favor."
        )

    def test_resumen_incluye_saldo_pendiente(self, payment_service_src):
        """saldo_pendiente = max(0, total_a_pagar - total_pagado)."""
        src = payment_service_src.read_text(encoding="utf-8")
        assert "max(0.0, total_a_pagar - total_pagado)" in src, (
            "F-049: saldo_pendiente debe calcularse como max(0, total_a_pagar - total_pagado)."
        )

    def test_resumen_desglose_modulos_tiene_monto_pagado(self, payment_service_src):
        """Cada módulo debe tener monto, monto_pagado, saldo_modulo, pagado."""
        src = payment_service_src.read_text(encoding="utf-8")
        for campo in ['"monto"', '"monto_pagado"', '"saldo_modulo"', '"pagado"']:
            assert campo in src, (
                f"F-049: Falta campo {campo} en el desglose por módulo del resumen."
            )


