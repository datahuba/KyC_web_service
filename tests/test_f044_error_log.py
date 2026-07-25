"""
F-044 (2026-07-22) · Tests del Visor de Errores 500
====================================================

Contexto: errores 500 solo se veían en logs del contenedor. Esto dejó
pasar bugs críticos como F-046 (NameError en `subir_nota_borrador`)
durante días.

Solución: capturar errores 500 en MongoDB (colección `error_logs` con
TTL 7 días) + endpoint `GET /api/v1/admin/errors/recent` para que
admin/superadmin los vea.

Este test verifica:
1. El modelo `ErrorLog` existe y está bien configurado.
2. La colección MongoDB se llama `error_logs`.
3. Hay un índice TTL de 7 días.
4. El endpoint `/admin/errors/recent` existe y requiere rol admin/superadmin.
5. El global exception handler en `main.py` llama a `_persist_error_log`.
"""

import pytest
from pathlib import Path


class TestF044ErrorLogModelo:
    """F-044: modelo ErrorLog."""

    def test_modelo_existe(self):
        from models.error_log import ErrorLog
        assert ErrorLog is not None

    def test_coleccion_se_llama_error_logs(self):
        from models.error_log import ErrorLog
        assert ErrorLog.Settings.name == "error_logs"

    def test_tiene_indice_ttl_7_dias(self):
        """El modelo debe configurar TTL de 604800s (7 días) en timestamp."""
        # F-044 (2026-07-22): verificamos que el código fuente usa
        # `expireAfterSeconds=604800` en el modelo, ya sea via Indexed
        # en el campo o via índice en Settings.
        src = Path("models/error_log.py").read_text(encoding="utf-8")
        assert "604800" in src, (
            "F-044: El modelo ErrorLog debe tener un índice TTL de 604800s (7 días). "
            "Sin esto los errores se acumulan para siempre."
        )
        # Verificar que está relacionado con timestamp
        # (puede ser `Indexed(datetime, expireAfterSeconds=604800)` o `expireAfterSeconds=604800` en Settings.indexes)
        assert "expireAfterSeconds" in src, (
            "F-044: Debe haber configuración `expireAfterSeconds` en el modelo."
        )
        # Verificar que el campo timestamp está presente
        assert "timestamp" in src, (
            "F-044: El modelo debe tener campo `timestamp` para aplicar el TTL."
        )

    def test_tiene_campos_requeridos(self):
        """Verificar que el modelo tiene los campos principales."""
        from models.error_log import ErrorLog
        campos_esperados = [
            "timestamp", "path", "method", "status_code",
            "error_type", "message", "stack_trace",
            "user_id", "user_email",
        ]
        for campo in campos_esperados:
            assert campo in ErrorLog.model_fields, (
                f"F-044: Falta campo `{campo}` en el modelo ErrorLog."
            )

    def test_modelo_esta_en_models_init(self):
        """El modelo debe estar exportado en models/__init__.py."""
        from models import ErrorLog
        assert ErrorLog is not None

    def test_modelo_esta_en_database_init(self):
        """El modelo debe estar registrado en init_beanie de core/database.py."""
        db_content = Path("core/database.py").read_text(encoding="utf-8")
        assert "ErrorLog" in db_content, (
            "F-044: El modelo ErrorLog debe estar en `init_beanie(...)` de core/database.py."
        )


class TestF044GlobalExceptionHandler:
    """F-044: el global exception handler en main.py persiste los errores."""

    def test_main_py_tiene_persist_error_log(self):
        main_content = Path("main.py").read_text(encoding="utf-8")
        assert "_persist_error_log" in main_content, (
            "F-044: main.py debe tener la función `_persist_error_log` que guarda "
            "el error en MongoDB."
        )

    def test_main_py_llama_persist_en_global_handler(self):
        """El global exception handler debe llamar a _persist_error_log."""
        main_content = Path("main.py").read_text(encoding="utf-8")
        # Buscar dentro del global_exception_handler
        idx = main_content.find("async def global_exception_handler")
        assert idx > 0, "No se encontró `async def global_exception_handler` en main.py"
        bloque = main_content[idx:idx + 3000]
        assert "_persist_error_log" in bloque, (
            "F-044: El global exception handler debe llamar a `_persist_error_log(request, exc, status_code=500)`."
        )

    def test_main_py_persist_importa_error_log_model(self):
        """La función _persist_error_log debe importar ErrorLog."""
        main_content = Path("main.py").read_text(encoding="utf-8")
        assert "from models.error_log import ErrorLog" in main_content, (
            "F-044: La función _persist_error_log debe importar el modelo ErrorLog."
        )


class TestF044AdminRouter:
    """F-044: endpoint /api/v1/admin/errors/recent."""

    @pytest.fixture
    def admin_content(self):
        return Path("api/admin.py").read_text(encoding="utf-8")

    def test_admin_router_archivo_existe(self):
        assert Path("api/admin.py").exists(), "Falta el archivo api/admin.py"

    def test_admin_router_registrado_en_api(self):
        """api/api.py debe incluir el router de admin."""
        api_content = Path("api/api.py").read_text(encoding="utf-8")
        assert "admin.router" in api_content, (
            "F-044: api/api.py debe incluir el router de admin."
        )
        assert 'prefix="/admin"' in api_content, (
            "F-044: El router de admin debe tener prefix='/admin'."
        )

    def test_admin_router_tiene_endpoint_recent(self, admin_content):
        """El router debe tener endpoint GET /errors/recent."""
        assert '"/errors/recent"' in admin_content, (
            "F-044: El router admin debe tener endpoint GET /errors/recent."
        )
        assert '"/errors/{error_id}"' in admin_content, (
            "F-044: El router admin debe tener endpoint GET /errors/{error_id}."
        )

    def test_admin_router_requiere_admin_o_superadmin(self, admin_content):
        """Los endpoints deben estar protegidos para admin/superadmin."""
        assert "require_admin_or_superadmin" in admin_content, (
            "F-044: Debe haber una función `require_admin_or_superadmin` que valide el rol."
        )
        assert "UserRole.SUPERADMIN" in admin_content, (
            "F-044: La función de protección debe verificar UserRole.SUPERADMIN."
        )
        assert "UserRole.ADMIN" in admin_content, (
            "F-044: La función de protección debe verificar UserRole.ADMIN."
        )

    def test_admin_router_tiene_ttl_en_schema(self, admin_content):
        """El endpoint debe permitir filtrar por ventana de tiempo (hours)."""
        assert "hours: int = Query" in admin_content, (
            "F-044: El endpoint debe aceptar parámetro `hours` para filtrar ventana de tiempo."
        )

    def test_admin_router_incluye_stats(self, admin_content):
        """La respuesta debe incluir estadísticas agregadas (by_type, by_path)."""
        assert "by_type" in admin_content, (
            "F-044: El endpoint debe incluir stats.by_type (conteo por tipo de error)."
        )
        assert "top_paths" in admin_content, (
            "F-044: El endpoint debe incluir stats.top_paths (paths con más errores)."
        )
