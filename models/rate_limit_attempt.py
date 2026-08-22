"""
F-FIX-RATE-LIMIT-MULTIWORKER (2026-08-22, encontrado en la auditoria completa)
================================================================================

`core/rate_limit.py` guardaba los intentos de login/forgot-password/etc en
un dict en memoria del proceso, con un docstring que asumia explicitamente
"un unico contenedor... sin multiples replicas/workers" — la MISMA premisa
falsa que causo el bug de multi-worker del ticket SSE (ver
F-FIX-SSE-TICKET-MULTIWORKER). Produccion corre `uvicorn --workers 4`: el
limite efectivo de intentos de fuerza bruta era hasta 4 veces mas debil de
lo configurado, porque un atacante que cae en workers distintos resetea el
contador de cada uno independientemente.

Este modelo persiste cada intento en Mongo (compartido por los 4 workers).
TTL de limpieza de respaldo a 20 minutos — mayor que la ventana mas larga
usada hoy (15 min), asi que ningun intento vigente se borra antes de dejar
de contar.
"""

from datetime import datetime
from pydantic import Field
from beanie import Document

from core.timezone_utils import utcnow_naive


class RateLimitAttempt(Document):
    clave: str = Field(..., description="'{bucket}:{ip}', ej. 'login:190.12.34.56'")
    timestamp: datetime = Field(default_factory=utcnow_naive)

    class Settings:
        name = "rate_limit_attempts"
        from pymongo import IndexModel, ASCENDING

        indexes = [
            IndexModel([("clave", ASCENDING), ("timestamp", ASCENDING)], name="clave_timestamp"),
            IndexModel([("timestamp", ASCENDING)], expireAfterSeconds=1200, name="ttl_timestamp_20min"),
        ]
