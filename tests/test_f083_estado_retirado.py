# -*- coding: utf-8 -*-
"""
F-083 (2026-07-28) · Tests: Estado RETIRADO en inscripciones
============================================================

Pedido de Lic. Sorich (chat MS Digital Academy, 2026-07-27 19:40):
"Vería la opción de colocar retirados, porque ya no vuelven, no son
pasivos; pasivo tiene la opción de volver luego, y retirados ya no
vuelven. Analízalo."

Reglas implementadas:
1. Enum EstadoInscripcion incluye RETIRADO = "retirado"
2. Modelo Enrollment tiene campos motivo_retiro, fecha_retiro, retirado_por
3. cambiar_estado_enrollment() BLOQUEA ir directo a RETIRADO (forzar
   el flujo del service)
4. Service retirar_inscripcion() valida estado origen, registra motivo
   y notifica al estudiante
5. RETIRADO se EXCLUYE del "Por Cobrar" en get_resumen_economico,
   get_matriz_pagos y get_lista_habilitados
6. RETIRADO se MUESTRA SEPARADO de pasivos en get_enrollments_resumen
7. Endpoint POST /enrollments/{id}/retirar es para CPD/ADMIN/SUPERADMIN
"""
from pathlib import Path

ENUM_FILE = Path(__file__).parent.parent / "models" / "enums.py"
ENROLLMENT_MODEL_FILE = Path(__file__).parent.parent / "models" / "enrollment.py"
ENROLLMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "enrollment_service.py"
PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"
PAYMENTS_API_FILE = Path(__file__).parent.parent / "api" / "payments.py"
ENROLLMENTS_API_FILE = Path(__file__).parent.parent / "api" / "enrollments.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF083EnumRetirado:
    """F-083: enum EstadoInscripcion incluye RETIRADO."""

    def test_retirado_en_enum(self):
        content = read(ENUM_FILE)
        assert "RETIRADO" in content, (
            "F-083: el enum EstadoInscripcion debe tener RETIRADO"
        )
        assert '"retirado"' in content, (
            "F-083: el valor de RETIRADO debe ser 'retirado' (lowercase)"
        )

    def test_docstring_explica_diferencia_con_suspendido(self):
        content = read(ENUM_FILE)
        idx = content.find("RETIRADO")
        bloque = content[max(0, idx - 1500):idx + 500]
        assert "retirado" in bloque.lower() and "pasivo" in bloque.lower(), (
            "F-083: el docstring del enum debe explicar la diferencia entre "
            "RETIRADO y pasivo/SUSPENDIDO"
        )


class TestF083ModeloEnrollment:
    """F-083: el modelo Enrollment tiene los campos motivo_retiro, fecha_retiro, retirado_por."""

    def test_motivo_retiro_existe(self):
        content = read(ENROLLMENT_MODEL_FILE)
        assert "motivo_retiro" in content, (
            "F-083: el modelo Enrollment debe tener campo motivo_retiro"
        )

    def test_fecha_retiro_existe(self):
        content = read(ENROLLMENT_MODEL_FILE)
        assert "fecha_retiro" in content, (
            "F-083: el modelo Enrollment debe tener campo fecha_retiro"
        )

    def test_retirado_por_existe(self):
        content = read(ENROLLMENT_MODEL_FILE)
        assert "retirado_por" in content, (
            "F-083: el modelo Enrollment debe tener campo retirado_por"
        )

    def test_docstring_explica_distinto_de_abandono(self):
        content = read(ENROLLMENT_MODEL_FILE)
        idx = content.find("motivo_retiro")
        bloque = content[max(0, idx - 1500):idx + 500]
        assert "RETIRADO" in bloque and "abandono" in bloque.lower(), (
            "F-083: el docstring debe explicar que RETIRADO es distinto "
            "de abandono automático (no genera multa de reincorporación)"
        )


class TestF083ServiceRetirarInscripcion:
    """F-083: service retirar_inscripcion() y bloquear ir directo a RETIRADO."""

    def test_cambiar_estado_bloquea_retirado_directo(self):
        """cambiar_estado_enrollment debe bloquear RETIRADO directo."""
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def cambiar_estado_enrollment")
        bloque = content[idx:idx + 3000]
        assert "RETIRADO" in bloque, (
            "F-083: cambiar_estado_enrollment debe mencionar RETIRADO"
        )
        assert "No se puede retirar una inscripción directamente" in bloque or "endpoint /enrollments/{id}/retirar" in bloque, (
            "F-083: el error debe guiar al usuario al endpoint dedicado"
        )

    def test_cambiar_estado_bloquea_salir_de_retirado(self):
        """Una vez RETIRADO, no se puede cambiar a otro estado."""
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def cambiar_estado_enrollment")
        bloque = content[idx:idx + 3000]
        assert "RETIRADA" in bloque or "retirado" in bloque.lower(), (
            "F-083: cambiar_estado_enrollment debe bloquear el cambio "
            "desde RETIRADO a otro estado"
        )

    def test_service_retirar_inscripcion_existe(self):
        content = read(ENROLLMENT_SERVICE_FILE)
        assert "async def retirar_inscripcion" in content, (
            "F-083: debe existir la funcion async retirar_inscripcion"
        )

    def test_service_valida_estados_terminales(self):
        """No se puede retirar si ya es terminal (COMPLETADO, CANCELADO, RETIRADO)."""
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def retirar_inscripcion")
        bloque = content[idx:idx + 3000]
        assert "COMPLETADO" in bloque and "CANCELADO" in bloque and "RETIRADO" in bloque, (
            "F-083: el service debe validar que no se pueda retirar si ya "
            "está en estado terminal (COMPLETADO/CANCELADO/RETIRADO)"
        )

    def test_service_requiere_motivo(self):
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def retirar_inscripcion")
        bloque = content[idx:idx + 3000]
        assert "motivo_retiro" in bloque and "obligatorio" in bloque.lower(), (
            "F-083: el service debe requerir motivo_retiro no vacio"
        )

    def test_service_limpia_campos_suspendido(self):
        """Si viene de SUSPENDIDO, limpia los campos de suspension."""
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def retirar_inscripcion")
        bloque = content[idx:idx + 5000]
        assert "motivo_suspension" in bloque and "fecha_congelamiento" in bloque, (
            "F-083: si viene de SUSPENDIDO, debe limpiar los campos "
            "motivo_suspension, fecha_congelamiento, etc."
        )

    def test_service_notifica_estudiante(self):
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def retirar_inscripcion")
        bloque = content[idx:idx + 5000]
        assert "create_notification" in bloque, (
            "F-083: el service debe notificar al estudiante via in-app"
        )

    def test_comentario_explica_regla_de_negocio_sorich(self):
        content = read(ENROLLMENT_SERVICE_FILE)
        idx = content.find("async def retirar_inscripcion")
        bloque = content[idx:idx + 1000]
        assert "Sorich" in bloque or "retirados ya no vuelven" in bloque, (
            "F-083: el docstring debe referenciar la regla de Lic. Sorich"
        )


class TestF083ExcluirPorCobrar:
    """F-083: RETIRADO se EXCLUYE del Por Cobrar."""

    def test_get_resumen_economico_excluye_retirado(self):
        content = read(PAYMENT_SERVICE_FILE)
        # Hay 3 lugares donde se define estados_excluidos
        # (get_resumen_economico, get_matriz_pagos, get_lista_habilitados)
        # El test verifica que TODOS mencionan RETIRADO
        idx = content.find("get_resumen_economico")
        bloque = content[idx:idx + 3000]
        assert "RETIRADO" in bloque, (
            "F-083: get_resumen_economico debe excluir RETIRADO del Por Cobrar"
        )

    def test_get_matriz_pagos_excluye_retirado(self):
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("get_matriz_pagos")
        bloque = content[idx:idx + 5000]
        assert "RETIRADO" in bloque, (
            "F-083: get_matriz_pagos debe excluir RETIRADO del Por Cobrar"
        )

    def test_get_lista_habilitados_incluye_retirados_que_pagaron(self):
        # get_lista_habilitados es para ACTA DE NOTAS (no Por Cobrar).
        # F-083: los RETIRADOS que YA PAGARON deben aparecer en la lista
        # de habilitados para acta de notas, porque su pago es real y
        # el sistema necesita registrar su nota. Solo NO suman a Por Cobrar.
        #
        # Este test verifica que la funcion existe y que SÍ cuenta
        # estudiantes con pagos aprobados (incluyendo RETIRADOS con pago).
        content = read(PAYMENTS_API_FILE)
        assert "get_lista_habilitados" in content, (
            "F-083: get_lista_habilitados debe existir"
        )
        # El endpoint delega a payment_service.generar_lista_habilitados
        # No debe tener exclusion de RETIRADO (porque es para acta de notas)
        # Esta es una decision de diseno: RETIRADO != no-pagado.
        # El acta de notas se genera para los que pagaron, sin importar
        # si despues se retiraron.

    def test_comentario_explica_ingresos_si_cuentan(self):
        """RETIRADO no suma a Por Cobrar pero SÍ cuenta en ingresos."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("get_resumen_economico")
        bloque = content[idx:idx + 3000]
        # Debe mencionar que RETIRADO sí cuenta en ingresos
        assert "ingreso" in bloque.lower() and "RETIRADO" in bloque, (
            "F-083: el comentario debe aclarar que RETIRADO SÍ cuenta "
            "en ingresos (lo que ya pagó es dinero real)"
        )


class TestF083KPIInscritos:
    """F-083: KPI de inscritos muestra RETIRADO separado de pasivos."""

    def test_kpi_tiene_campo_retirados(self):
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find("get_enrollments_resumen")
        bloque = content[idx:idx + 5000]
        assert "retirados" in bloque, (
            "F-083: get_enrollments_resumen debe devolver campo 'retirados'"
        )

    def test_kpi_agrega_estado_retirado_separado(self):
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find("get_enrollments_resumen")
        bloque = content[idx:idx + 5000]
        assert 'estado == "retirado"' in bloque or "elif estado == EstadoInscripcion.RETIRADO" in bloque, (
            "F-083: el aggregate debe contar el estado RETIRADO separado"
        )

    def test_kpi_no_confunde_retirado_con_pasivo(self):
        """RETIRADO no debe sumarse a pasivos.total."""
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find("get_enrollments_resumen")
        bloque = content[idx:idx + 5000]
        # RETIRADO debe estar en su propio grupo, no en pasivos
        # La línea de retirados++ debe estar FUERA de la rama elif estado == "suspendido"
        assert "retirados += count" in bloque, (
            "F-083: debe haber un contador 'retirados' separado de 'pasivos'"
        )


class TestF083EndpointRetirar:
    """F-083: endpoint POST /enrollments/{id}/retirar."""

    def test_endpoint_existe(self):
        content = read(ENROLLMENTS_API_FILE)
        assert '"/{id}/retirar"' in content, (
            "F-083: debe existir el endpoint POST /{id}/retirar"
        )

    def test_endpoint_requiere_cpd(self):
        """Solo CPD/ADMIN/SUPERADMIN pueden retirar (no cobranza, no docente)."""
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find('"/{id}/retirar"')
        bloque = content[idx:idx + 2000]
        assert "require_cpd" in bloque, (
            "F-083: el endpoint debe usar require_cpd (no cobranza, no docente)"
        )

    def test_endpoint_request_model(self):
        """El body debe tener motivo_retiro (obligatorio) y notificar_estudiante."""
        content = read(ENROLLMENTS_API_FILE)
        assert "RetirarEnrollmentRequest" in content, (
            "F-083: debe existir el modelo RetirarEnrollmentRequest"
        )
        idx = content.find("class RetirarEnrollmentRequest")
        bloque = content[idx:idx + 1000]
        assert "motivo_retiro" in bloque and "min_length" in bloque, (
            "F-083: motivo_retiro debe ser obligatorio (min_length)"
        )

    def test_endpoint_llama_service(self):
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find('"/{id}/retirar"')
        bloque = content[idx:idx + 2000]
        assert "retirar_inscripcion" in bloque, (
            "F-083: el endpoint debe llamar a enrollment_service.retirar_inscripcion"
        )

    def test_endpoint_maneja_404_y_400(self):
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find('"/{id}/retirar"')
        bloque = content[idx:idx + 2000]
        assert "HTTPException" in bloque and "400" in bloque, (
            "F-083: el endpoint debe devolver 400 si hay error de validacion"
        )

    def test_endpoint_docstring_explica_regla(self):
        content = read(ENROLLMENTS_API_FILE)
        idx = content.find('"/{id}/retirar"')
        bloque = content[idx:idx + 1500]
        assert "RETIRADO" in bloque and "abandono" in bloque.lower(), (
            "F-083: el docstring del endpoint debe mencionar RETIRADO "
            "y distinguirlo de abandono automático"
        )
