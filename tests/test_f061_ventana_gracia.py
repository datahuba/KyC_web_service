# -*- coding: utf-8 -*-
"""
F-061 (2026-07-23) · Tests para Ventana de Gracia de Pasivo
===========================================================

Regla de Kevin (2026-07-23): "Si el estudiante pide volverse pasivo dentro
de los primeros N días desde su inscripción, no se cobra multa de
reincorporación. Pasada esa ventana, sí se cobra MULTA_REINCORPORACION_BS."

Settings:
- VENTANA_GRACIA_PASIVO_DIAS (default 30, configurable por .env)
- MULTA_REINCORPORACION_BS (default 300, configurable por .env)

Comportamiento esperado:
- dias_desde_inscripcion <= VENTANA_GRACIA_PASIVO_DIAS  → multa_aplicada_bs = 0
- dias_desde_inscripcion >  VENTANA_GRACIA_PASIVO_DIAS  → multa_aplicada_bs = MULTA_REINCORPORACION_BS
- fecha_inscripcion ausente (legacy)                   → multa_aplicada_bs = 0 (asumimos dentro)
"""
import os
import re
import pytest
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "core" / "config.py"
SERVICE_FILE = Path(__file__).parent.parent / "services" / "passive_request_service.py"
MODEL_FILE = Path(__file__).parent.parent / "models" / "passive_request.py"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestF061VentanaGraciaConfig:
    """F-061: el setting VENTANA_GRACIA_PASIVO_DIAS debe existir en config.py."""

    def test_setting_existe(self):
        """VENTANA_GRACIA_PASIVO_DIAS debe estar definido en core/config.py."""
        content = read(CONFIG_FILE)
        match = re.search(
            r"VENTANA_GRACIA_PASIVO_DIAS:\s*int\s*=\s*Field\(default=(\d+),",
            content,
        )
        assert match, (
            "F-061: Falta el setting VENTANA_GRACIA_PASIVO_DIAS en core/config.py. "
            "Es la pieza clave de la ventana de gracia configurable."
        )

    def test_setting_default_30_dias(self):
        """El default debe ser 30 días (1 mes) según la convención de Kevin."""
        content = read(CONFIG_FILE)
        match = re.search(
            r"VENTANA_GRACIA_PASIVO_DIAS:\s*int\s*=\s*Field\(default=(\d+),",
            content,
        )
        assert match, "F-061: setting no encontrado"
        default = int(match.group(1))
        assert default == 30, (
            f"F-061: El default de VENTANA_GRACIA_PASIVO_DIAS debe ser 30 días "
            f"(1 mes, igual que DIAS_INACTIVIDAD_MORA). Encontrado: {default}."
        )

    def test_setting_es_env_overridable(self):
        """El setting debe ser override-able por variable de entorno."""
        content = read(CONFIG_FILE)
        match = re.search(
            r"VENTANA_GRACIA_PASIVO_DIAS:\s*int\s*=\s*Field\(default=\d+,\s*env=\"VENTANA_GRACIA_PASIVO_DIAS\"\)",
            content,
        )
        assert match, (
            "F-061: VENTANA_GRACIA_PASIVO_DIAS debe ser override-able vía "
            "env var 'VENTANA_GRACIA_PASIVO_DIAS' (como el resto de settings)."
        )


class TestF061Modelo:
    """F-061: el modelo PassiveRequest debe tener los campos de auditoría."""

    def test_dias_desde_inscripcion_al_solicitar_existe(self):
        """El modelo debe guardar el snapshot de días desde inscripción."""
        content = read(MODEL_FILE)
        assert "dias_desde_inscripcion_al_solicitar" in content, (
            "F-061: PassiveRequest debe tener el campo "
            "'dias_desde_inscripcion_al_solicitar' (snapshot para auditoría)."
        )

    def test_multa_aplicada_bs_existe(self):
        """El modelo debe guardar el monto de multa aplicada (o 0)."""
        content = read(MODEL_FILE)
        assert "multa_aplicada_bs" in content, (
            "F-061: PassiveRequest debe tener el campo 'multa_aplicada_bs' "
            "(0 si está en ventana de gracia, MULTA_REINCORPORACION_BS si no)."
        )

    def test_campos_son_optional(self):
        """Los campos deben ser Optional (None default) para compatibilidad con registros legacy."""
        content = read(MODEL_FILE)
        # buscar las dos definiciones con regex tolerante a comentarios
        for field in ["dias_desde_inscripcion_al_solicitar", "multa_aplicada_bs"]:
            # buscar la línea completa de la definición
            pattern = (
                rf"{re.escape(field)}\s*:\s*Optional\["  # noqa
            )
            match = re.search(pattern, content)
            assert match, (
                f"F-061: '{field}' debe ser Optional[...]. "
                f"Verifica que esté declarado como 'Optional[float]' o similar."
            )


class TestF061LogicaCreatePassiveRequest:
    """F-061: la lógica de cálculo de multa debe estar en create_passive_request."""

    def test_calcula_dias_desde_inscripcion(self):
        """Debe calcular los días entre enrollment.fecha_inscripcion y ahora."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"async def create_passive_request\([\s\S]*?dias_desde_inscripcion\s*=\s*max\(0,\s*\(ahora\s*-\s*fecha_inscripcion\)\.days\)",
            content,
        )
        assert match, (
            "F-061: create_passive_request debe calcular dias_desde_inscripcion "
            "como max(0, (ahora - fecha_inscripcion).days) — clamp a 0 para evitar "
            "negativos si hay drift de reloj."
        )

    def test_evalua_ventana_de_gracia(self):
        """Debe comparar dias_desde_inscripcion con VENTANA_GRACIA_PASIVO_DIAS."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"en_ventana_gracia\s*=\s*dias_desde_inscripcion\s*<=\s*settings\.VENTANA_GRACIA_PASIVO_DIAS",
            content,
        )
        assert match, (
            "F-061: la comparación de la ventana de gracia debe ser "
            "'dias_desde_inscripcion <= settings.VENTANA_GRACIA_PASIVO_DIAS'. "
            "El '=' es importante: si pide justo el día 30, todavía está en ventana."
        )

    def test_multa_cero_en_ventana(self):
        """Si está en ventana de gracia, multa = 0."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"multa_aplicada\s*=\s*0\.0\s+if\s+en_ventana_gracia\s+else\s+float\(settings\.MULTA_REINCORPORACION_BS\)",
            content,
        )
        assert match, (
            "F-061: la multa debe ser 0.0 si está en ventana, "
            "o MULTA_REINCORPORACION_BS si no. Formato esperado: "
            "'multa_aplicada = 0.0 if en_ventana_gracia else float(settings.MULTA_REINCORPORACION_BS)'"
        )

    def test_maneja_legacy_sin_fecha_inscripcion(self):
        """Si fecha_inscripcion es None, no aplicar multa (asumir dentro de ventana)."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"if fecha_inscripcion:[\s\S]*?dias_desde_inscripcion\s*=\s*0",
            content,
        )
        assert match, (
            "F-061: debe manejar el caso legacy donde enrollment.fecha_inscripcion "
            "es None, asumiendo que está dentro de la ventana (dias = 0, multa = 0)."
        )

    def test_snapshotea_dias_y_multa_en_solicitud(self):
        """La solicitud creada debe tener los campos de auditoría populados."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"solicitud\s*=\s*PassiveRequest\([\s\S]*?dias_desde_inscripcion_al_solicitar=dias_desde_inscripcion,?[\s\S]*?multa_aplicada_bs=multa_aplicada,?",
            content,
        )
        assert match, (
            "F-061: al crear el PassiveRequest, debe popular los campos "
            "'dias_desde_inscripcion_al_solicitar' y 'multa_aplicada_bs' "
            "con los valores calculados (snapshot en el momento de crear)."
        )


class TestF061LogicaApprove:
    """F-061: cuando se aprueba un pasivo con multa, marcar enrollment.multa_reincorporacion_pendiente=True."""

    def test_approve_marca_multa_pendiente(self):
        """Si la solicitud tiene multa > 0, el enrollment debe marcarse con multa_reincorporacion_pendiente=True."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"if\s+\(solicitud\.multa_aplicada_bs\s+or\s+0\)\s*>\s*0:[\s\S]*?enrollment\.multa_reincorporacion_pendiente\s*=\s*True",
            content,
        )
        assert match, (
            "F-061: approve_passive_request debe setear "
            "enrollment.multa_reincorporacion_pendiente = True cuando "
            "la solicitud tenga multa > 0 (fuera de la ventana de gracia)."
        )

    def test_approve_notifica_con_detalle_multa(self):
        """El notification al estudiante debe mencionar el monto de la multa si aplica."""
        content = read(SERVICE_FILE)
        # buscar dentro de approve_passive_request: la rama if multa > 0 debe
        # construir un mensaje con el monto
        match = re.search(
            r"if\s+multa\s*>\s*0:[\s\S]*?multa de reincorporaci[oó]n[\s\S]*?\{multa",
            content,
        )
        assert match, (
            "F-061: el mensaje de notification al aprobar pasivo debe mencionar "
            "el monto de la multa cuando multa > 0. Busca un f-string como "
            "'multa de reincorporación de Bs. {multa:.0f}'."
        )


class TestF061LogicaReactivate:
    """F-061: al reactivar, el notification debe mencionar la multa pendiente si la hay."""

    def test_reactivate_advierte_de_multa_pendiente(self):
        """Si enrollment.multa_reincorporacion_pendiente=True, mencionar la multa en el notification."""
        content = read(SERVICE_FILE)
        match = re.search(
            r"if\s+getattr\(enrollment,[\s\S]*?multa_reincorporacion_pendiente,?[\s\S]*?False\):[\s\S]*?multa de reincorporaci",
            content,
        )
        assert match, (
            "F-061: reactivate_enrollment debe mencionar la multa de reincorporación "
            "en el notification si enrollment.multa_reincorporacion_pendiente = True."
        )


class TestF061ReglaNegocio:
    """F-061: documentación explícita de la regla de negocio en comentarios."""

    def test_comentario_explica_regla_kevin(self):
        """El código debe tener un comentario que explique la regla de Kevin."""
        content = read(SERVICE_FILE)
        # buscar "ventana de gracia" cerca de "Kevin"
        if "ventana de gracia" in content.lower() or "ventana_gracia" in content:
            # si está el término, suficiente
            assert "F-061" in content, (
                "F-061: el código debería tener un comentario F-061 que explique la regla."
            )
        else:
            pytest.fail("F-061: no se encontró referencia a 'ventana de gracia' en passive_request_service.py")
