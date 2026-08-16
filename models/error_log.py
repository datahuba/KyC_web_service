"""
F-044 (2026-07-22) · Modelo de Log de Errores 500
=================================================

Contexto: errores 500 solo se ven en logs del contenedor (no llegan al
usuario, no se notifican al equipo técnico). Esto dejó pasar bugs críticos
silenciosamente (ej: F-046 NameError en `subir_nota_borrador` que rompió
el guardado de notas durante días sin que nos diéramos cuenta).

Solución: capturar TODOS los errores 500 en una colección MongoDB con
TTL de 7 días (auto-limpieza). Endpoint para que admin/superadmin los vea.

Colección MongoDB: error_logs
TTL: 604800 segundos (7 días)
"""

from datetime import datetime
from typing import Optional
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class ErrorLog(MongoBaseModel):
    """
    Log de error 500 capturado en producción.

    Se crea desde el global exception handler en main.py.
    Se consulta desde GET /api/v1/admin/errors/recent (solo superadmin/admin).

    Campos:
    -------
    - timestamp: cuándo ocurrió (auto)
    - path: URL del request (ej: /api/v1/enrollments/xxx/modulos/0/nota)
    - method: GET/POST/PATCH/etc
    - status_code: 500, 502, etc
    - error_type: nombre de la excepción (ej: NameError, ValueError)
    - message: mensaje del error
    - stack_trace: traceback completo (para debugging)
    - user_id: ID del user/student que hizo el request (None si anónimo)
    - user_type: 'user', 'student' o 'anonymous'
    - user_email: email del usuario (para búsqueda rápida)
    - request_body: body del request (opcional, puede tener PII)
    - query_params: query string del request
    - environment: 'production' / 'staging' / 'development'
    """

    timestamp: datetime = Field(default_factory=datetime.utcnow)  # F-085: default_factory explícito (el default `Indexed(...)` no es serializable por Beanie)
    path: str = Field(..., description="URL del request")
    method: str = Field(..., description="HTTP method")
    status_code: int = Field(..., description="HTTP status code")
    error_type: str = Field(..., description="Nombre de la excepción")
    message: str = Field(..., description="Mensaje del error")
    stack_trace: Optional[str] = Field(
        default=None,
        description="Traceback completo (puede ser largo)",
    )
    user_id: Optional[PyObjectId] = Field(
        default=None,
        description="ID del user/student que hizo el request",
    )
    user_type: Optional[str] = Field(
        default=None,
        description="'user', 'student' o 'anonymous'",
    )
    user_email: Optional[str] = Field(
        default=None,
        description="Email del usuario (para búsqueda rápida)",
    )
    request_body: Optional[str] = Field(
        default=None,
        description="Body del request (JSON serializado, truncado a 2000 chars)",
    )
    query_params: Optional[str] = Field(
        default=None,
        description="Query string del request",
    )
    environment: str = Field(
        default="production",
        description="'production' / 'staging' / 'development'",
    )
    # F-XXX (2026-07-29): estado de resolución del error. Cuando el admin/
    # superadmin marca un error como resuelto, queda con `resolved=True` y
    # `resolved_by` + `resolved_at`. El visor filtra por `resolved=false` por
    # default para enfocarse en errores que aún requieren atención.
    resolved: bool = Field(
        default=False,
        description="True si el admin marcó este error como resuelto",
    )
    resolved_by: Optional[str] = Field(
        default=None,
        description="Username del admin/superadmin que marcó el error como resuelto",
    )
    resolved_at: Optional[datetime] = Field(
        default=None,
        description="Timestamp de cuándo se marcó como resuelto",
    )
    resolution_note: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Nota opcional del admin (ej: 'Fixed in commit abc123')",
    )

    class Settings:
        name = "error_logs"
        # F-085 (2026-07-28): TTL de 7 días. Antes el campo `timestamp` usaba
        # el default de Beanie con TTL inline, que (a) no generaba el índice
        # TTL en MongoDB y (b) era un NewType no serializable que rompía
        # el handler F-044 silenciosamente. Se mueve el TTL a Settings.indexes
        # con un IndexModel explícito.
        from pymongo import IndexModel, ASCENDING
        indexes = [
            IndexModel([("timestamp", ASCENDING)], expireAfterSeconds=604800, name="ttl_timestamp_7d"),
            "path",
            "error_type",
            "status_code",
            # F-XXX (2026-07-29): índice para filtrar rápido por "no resueltos".
            IndexModel([("resolved", ASCENDING), ("timestamp", ASCENDING)], name="resolved_timestamp"),
        ]
