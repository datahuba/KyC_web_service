"""
Auditoría completa 2026-08-22 — los 4 hallazgos CRITICOS, verificados.

Ninguno de estos 4 puntos tenia cobertura real antes (o directamente no
existia el codigo que los arregla). Este proyecto no tiene harness de
MongoDB para tests (ver AGENTS.md), asi que se combinan tests de logica
pura (donde el codigo lo permite, ej. la funcion de reincorporacion no
necesita DB para la parte de calculo) con tests de inspeccion de fuente
para lo que si requiere Mongo real (rate limiter, ticket SSE, change
stream).
"""

import io
import os

import pytest


def _fuente(*ruta):
    p = os.path.join(os.path.dirname(__file__), "..", *ruta)
    return io.open(p, encoding="utf-8").read()


class TestReincorporacionNoFabricaPagos:
    """Critico #1: services/enrollment_service.py ya no marca modulos
    como pagados solo por posicion — solo si el modulo original
    realmente estaba pagado."""

    def _cuerpo_reincorporar(self):
        src = _fuente("services", "enrollment_service.py")
        ini = src.index("async def reincorporar_estudiante")
        fin = src.find("\n\nasync def ", ini)
        return src[ini: fin if fin != -1 else len(src)]

    def test_verifica_estado_pagado_del_modulo_original(self):
        cuerpo = self._cuerpo_reincorporar()
        assert "old_mod_pagado" in cuerpo
        assert 'old_mod.estado == "Pagado"' in cuerpo

    def test_no_marca_pagado_sin_verificar_el_original(self):
        """No debe quedar ningun camino que ponga estado='Pagado' sin
        antes chequear old_mod_pagado."""
        cuerpo = self._cuerpo_reincorporar()
        # El unico lugar donde se asigna estado = "Pagado" debe estar
        # dentro de la rama que ya verifico old_mod_pagado.
        idx_pagado = cuerpo.index('new_mod.estado = "Pagado"')
        antes = cuerpo[:idx_pagado]
        # La condicion `if mod_num < modulo_inicio and old_mod_pagado:`
        # debe aparecer ANTES de la asignacion "Pagado", como guarda.
        assert "and old_mod_pagado:" in antes

    def test_llama_a_la_auditoria_financiera(self):
        """Critico: la funcion debe dejar rastro en la auditoria inmutable."""
        cuerpo = self._cuerpo_reincorporar()
        assert "_registrar_auditoria_financiera" in cuerpo
        assert 'accion="reincorporar_estudiante"' in cuerpo

    def test_guarda_fecha_reincorporacion(self):
        cuerpo = self._cuerpo_reincorporar()
        assert "fecha_reincorporacion" in cuerpo


class TestReincorporacionRBACScope:
    """Critico #1 (parte 2): el endpoint ahora restringe a
    encargado_curso/coordinador a sus cursos_asignados, igual que cada
    otro endpoint de este archivo."""

    def _cuerpo_endpoint(self):
        src = _fuente("api", "enrollments.py")
        ini = src.index("async def reincorporar_estudiante_endpoint")
        fin = src.index("\n\n\n", ini)
        return src[ini:fin]

    def test_chequea_cursos_asignados_en_ambos_cursos(self):
        cuerpo = self._cuerpo_endpoint()
        assert "cursos_asignados" in cuerpo
        assert "old_enrollment.curso_id not in cursos_asignados" in cuerpo
        assert "data.nuevo_curso_id not in cursos_asignados" in cuerpo

    def test_aplica_solo_a_encargado_y_coordinador(self):
        cuerpo = self._cuerpo_endpoint()
        assert "UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR" in cuerpo


class TestAuditoriaFinancieraPersisteDeVerdad:
    """Critico #1 (base): _registrar_auditoria_financiera ya no es solo
    un print() — persiste en Mongo."""

    def test_modelo_audit_log_existe_y_es_document(self):
        src = _fuente("models", "audit_log.py")
        assert "class AuditLogFinanciero(Document)" in src

    def test_registrado_en_database_py(self):
        src = _fuente("core", "database.py")
        assert "AuditLogFinanciero" in src
        ini = src.index("document_models=[")
        fin = src.index("]", ini)
        assert "AuditLogFinanciero" in src[ini:fin]

    def test_registrar_auditoria_inserta_en_mongo(self):
        src = _fuente("services", "payment_service.py")
        ini = src.index("async def _registrar_auditoria_financiera")
        fin = src.index("\n\nasync def ", ini)
        cuerpo = src[ini:fin]
        assert "AuditLogFinanciero(" in cuerpo
        assert ".insert()" in cuerpo


class TestRateLimiterEnMongo:
    """Critico #3: el rate limiter ya no es un dict en memoria de
    proceso — persiste en Mongo, compartido por los 4 workers."""

    def test_check_rate_limit_es_async(self):
        src = _fuente("core", "rate_limit.py")
        assert "async def check_rate_limit" in src

    def test_no_queda_dict_en_memoria(self):
        src = _fuente("core", "rate_limit.py")
        assert "Dict[str, List[float]]" not in src
        assert "_intentos[clave]" not in src
        assert "defaultdict" not in src

    def test_usa_el_modelo_rate_limit_attempt(self):
        src = _fuente("core", "rate_limit.py")
        assert "RateLimitAttempt" in src

    def test_modelo_registrado_en_database_py(self):
        src = _fuente("core", "database.py")
        ini = src.index("document_models=[")
        fin = src.index("]", ini)
        assert "RateLimitAttempt" in src[ini:fin]

    def test_los_4_call_sites_usan_await(self):
        src = _fuente("api", "auth.py")
        ocurrencias = src.count("check_rate_limit(request")
        awaited = src.count("await check_rate_limit(request")
        assert ocurrencias == awaited, "Algún call site de check_rate_limit no usa await"
        assert ocurrencias == 4


class TestNotificacionesSSESinBusEnMemoria:
    """Critico #2: las notificaciones SSE ya no dependen de un bus en
    memoria de proceso — usan un MongoDB Change Stream compartido."""

    def test_sse_bus_py_no_existe(self):
        ruta = os.path.join(os.path.dirname(__file__), "..", "services", "sse_bus.py")
        assert not os.path.exists(ruta), "services/sse_bus.py debería estar eliminado"

    def test_stream_notifications_usa_change_stream(self):
        src = _fuente("api", "notifications.py")
        ini = src.index("async def stream_notifications")
        cuerpo = src[ini:]
        assert "collection.watch(" in cuerpo
        assert "fullDocument.destinatario_id" in cuerpo
        assert "sse_bus.subscribe" not in cuerpo
        assert "sse_bus.unsubscribe" not in cuerpo
        assert "from services.sse_bus" not in src

    def test_create_notification_no_publica_en_bus(self):
        src = _fuente("services", "notification_service.py")
        assert "sse_bus.publish" not in src
        assert "from services.sse_bus" not in src


class TestPaymentServiceTestsLlamanCodigoReal:
    """Meta-test: confirma que las funciones puras extraídas existen y
    que get_reporte_caja las usa en vez de reimplementar la lógica
    inline (lo que permitía a los tests viejos reimplementarla también
    y nunca detectar una rotura real)."""

    def test_funciones_puras_existen(self):
        src = _fuente("services", "payment_service.py")
        assert "def _calcular_resumen_caja(" in src
        assert "def _serializar_payments_reporte(" in src

    def test_get_reporte_caja_usa_las_funciones_puras(self):
        src = _fuente("services", "payment_service.py")
        ini = src.index("async def get_reporte_caja")
        fin = src.index("\n\nasync def ", ini)
        cuerpo = src[ini:fin]
        assert "_calcular_resumen_caja(" in cuerpo
        assert "_serializar_payments_reporte(" in cuerpo


class TestSanitizeLegacyDatabaseIdempotente:
    """Ítem ambiguo #3 de la auditoría, resuelto por Kevin: el saneamiento
    de duplicados en core/database.py corría sin control en cada uno de
    los 4 workers al arrancar. Kevin autorizó el fix con la condición
    explícita de que no sea agresivo ni dañe datos — se agregó solo un
    lock de Mongo con TTL, sin tocar la lógica de qué se borra.

    Verificado en vivo contra Atlas de producción real (4 llamadas
    concurrentes a la función real, vía SSH+docker exec): solo 1 de 4
    corrió el saneamiento completo, las otras 3 salieron por
    DuplicateKeyError.
    """

    def test_usa_lock_con_insert_one_y_duplicate_key_error(self):
        src = _fuente("core", "database.py")
        ini = src.index("async def _sanitize_legacy_database")
        fin = src.index("\n\nasync def init_db", ini)
        cuerpo = src[ini:fin]
        assert "_startup_locks" in cuerpo
        assert "insert_one(" in cuerpo
        assert "DuplicateKeyError" in cuerpo
        assert "expireAfterSeconds=600" in cuerpo

    def test_no_modifico_la_logica_de_deduplicacion(self):
        src = _fuente("core", "database.py")
        ini = src.index("async def _sanitize_legacy_database")
        fin = src.index("\n\nasync def init_db", ini)
        cuerpo = src[ini:fin]
        assert "dup_registros" in cuerpo
        assert "dup_carnets" in cuerpo
        assert "dup_emails" in cuerpo
        assert "dup_courses" in cuerpo
        assert "drop_indexes()" in cuerpo
