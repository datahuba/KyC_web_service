# -*- coding: utf-8 -*-
"""
F-082 (2026-07-28) · Tests: Indice UNIQUE en numero_transaccion + notification de desbalance
==========================================================================================

Kevin reporto (2026-07-28 09:00) que el sistema permitio registrar el mismo
comprobante bancario 2 veces para el estudiante Medardo Balvino Rojas (CI
2720765). La validacion en payment_service.create_payment se puede saltar
por race condition o si un pago fue RECHAZADO y luego se intenta de nuevo
con el mismo NRO.

Fix:
- Indice UNIQUE PARCIAL en payments.numero_transaccion (solo aplica a
  pagos con estado 'pendiente' o 'aprobado'). MongoDB rechaza cualquier
  intento de insertar un duplicado a nivel de BD, incluso si la validacion
  en el service falla.
- Cuando el prorrateo (actualizar_saldo_enrollment) falla definitivamente
  tras 2 intentos, notificar al equipo economico via in-app notification
  para que vean el desbalance y ejecuten el fix manual.
"""
from pathlib import Path

PAYMENT_MODEL_FILE = Path(__file__).parent.parent / "models" / "payment.py"
PAYMENT_SERVICE_FILE = Path(__file__).parent.parent / "services" / "payment_service.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF082IndiceUnico:
    """F-082: indice UNIQUE PARCIAL en numero_transaccion."""

    def test_indice_unico_existe(self):
        content = read(PAYMENT_MODEL_FILE)
        # Debe haber un IndexModel con unique=True en numero_transaccion
        assert "unique=True" in content, (
            "F-082: el modelo Payment debe tener un indice UNIQUE"
        )
        assert "numero_transaccion" in content, (
            "F-082: el indice debe ser sobre numero_transaccion"
        )
        assert "partialFilterExpression" in content, (
            "F-082: el indice UNIQUE debe ser PARCIAL (no aplicar a RECHAZADO/ANULADO)"
        )

    def test_indice_excluye_rechazado_y_anulado(self):
        """El indice UNIQUE debe excluir pagos RECHAZADOS y ANULADOS."""
        content = read(PAYMENT_MODEL_FILE)
        # Buscar el bloque del partialFilterExpression
        idx = content.find("partialFilterExpression")
        assert idx > 0, "F-082: debe haber un partialFilterExpression definido"
        bloque = content[idx:idx + 500]
        assert "pendiente" in bloque, "F-082: el indice debe permitir 'pendiente'"
        assert "aprobado" in bloque, "F-082: el indice debe permitir 'aprobado'"
        assert "rechazado" not in bloque, "F-082: el indice debe EXCLUIR 'rechazado'"
        assert "anulado" not in bloque, "F-082: el indice debe EXCLUIR 'anulado'"

    def test_indice_excluye_nro_null(self):
        """Pagos en Caja (sin NRO de transaccion) no deben chocar."""
        content = read(PAYMENT_MODEL_FILE)
        idx = content.find("partialFilterExpression")
        bloque = content[idx:idx + 500]
        # El filtro debe verificar que numero_transaccion existe y es string
        assert "$exists" in bloque or "$type" in bloque, (
            "F-082: el indice debe excluir pagos sin numero_transaccion (Caja)"
        )

    def test_nombre_del_indice(self):
        content = read(PAYMENT_MODEL_FILE)
        assert "uniq_numero_transaccion_activo" in content, (
            "F-082: el indice debe tener un nombre descriptivo (uniq_numero_transaccion_activo)"
        )

    def test_comentario_explica_caso_medardo(self):
        """El comentario debe mencionar el caso Medardo (origen del bug)."""
        content = read(PAYMENT_MODEL_FILE)
        idx = content.find("uniq_numero_transaccion_activo")
        bloque = content[max(0, idx - 1500):idx + 200]
        assert "Medardo" in bloque, (
            "F-082: el comentario debe mencionar el caso Medardo Balvino Rojas (origen del bug, 2026-07-28)"
        )


class TestF082NotificationDesbalance:
    """F-082: notification al equipo economico si el prorrateo falla."""

    def test_bloque_f082_presente(self):
        content = read(PAYMENT_SERVICE_FILE)
        assert "F-082" in content, (
            "F-082: debe haber un comentario/referencia al fix F-082 en payment_service"
        )

    def test_usa_create_notification(self):
        """El bloque debe usar create_notification de notification_service."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        assert idx > 0, "F-082: debe haber un bloque que notifique al equipo economico"
        bloque = content[idx:idx + 2000]
        assert "create_notification" in bloque, (
            "F-082: debe usar create_notification de notification_service"
        )

    def test_notifica_a_roles_economicos(self):
        """Debe notificar a cobranza/admin/superadmin/mae."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        bloque = content[idx:idx + 2000]
        assert "COBRANZA" in bloque, "F-082: debe notificar al rol COBRANZA"
        assert "ADMIN" in bloque or "SUPERADMIN" in bloque, (
            "F-082: debe notificar a ADMIN o SUPERADMIN"
        )

    def test_tipo_alerta_error(self):
        """La notification debe ser tipo error (no info) para que se destaque."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        bloque = content[idx:idx + 2000]
        assert "tipo_alerta=\"error\"" in bloque or "tipo_alerta='error'" in bloque, (
            "F-082: la notification debe ser tipo 'error' para que se destaque en el frontend"
        )

    def test_no_bloquea_el_flujo_principal(self):
        """Si la notification falla, el flujo principal no debe romperse."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        bloque = content[idx:idx + 3000]
        # Debe haber un try/except afuera Y un try/except adentro (por destinatario)
        # Para no romper el flujo si algo falla
        assert bloque.count("try:") >= 2, (
            f"F-082: el bloque de notification debe tener al menos 2 try (exterior + interior). Encontrados: {bloque.count('try:')}"
        )
        assert bloque.count("except") >= 2, (
            f"F-082: el bloque de notification debe tener al menos 2 except (exterior + interior). Encontrados: {bloque.count('except')}"
        )

    def test_referencia_a_script_de_fix(self):
        """El mensaje debe apuntar al script de fix manual."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        bloque = content[idx:idx + 2000]
        assert "fix-enrollments-desincronizados" in bloque, (
            "F-082: el mensaje de la notification debe apuntar al script de fix "
            "fix-enrollments-desincronizados.py"
        )

    def test_comentario_menciona_medardo_y_jerry(self):
        """El comentario debe mencionar los casos que originaron el fix."""
        content = read(PAYMENT_SERVICE_FILE)
        idx = content.find("F-082 (2026-07-28): notificar")
        # Buscar en un rango mas amplio (2500 chars antes) para incluir el comentario completo
        bloque = content[max(0, idx - 2500):idx + 2000]
        assert "Medardo" in bloque, (
            "F-082: el comentario debe mencionar a Medardo (caso que origino el fix)"
        )
        assert "Jerry" in bloque, (
            "F-082: el comentario debe mencionar a Jerry Fletcher (caso adicional)"
        )
