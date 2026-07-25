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

from datetime import datetime, timedelta
from typing import Optional
from pydantic import Field
from beanie import Indexed
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

    timestamp: datetime = Indexed(datetime, expireAfterSeconds=604800)  # TTL 7 días
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

    class Settings:
        name = "error_logs"
        # F-044: TTL de 7 días se configura en el campo `timestamp` con
        # `Indexed(datetime, expireAfterSeconds=604800)` arriba.
        # Índices secundarios para queries del visor.
        indexes = [
            "path",
            "error_type",
            "status_code",
        ]
