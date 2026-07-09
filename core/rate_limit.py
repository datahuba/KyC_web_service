"""
Rate Limiting Simple en Memoria
================================

AUDITORÍA (ALTO #8 - seguridad): /auth/login, /auth/login/student y
/auth/forgot-password no tenían ningún límite de intentos, dejando fuerza
bruta de contraseñas completamente viable. Ya estaba reconocido como deuda
técnica en ISSUE-D del backlog (Cloudflare WAF/Rate Limiting a nivel de
infraestructura), pero eso es una tarea de infraestructura pendiente y no
cubre el corto plazo. Esta es una barrera mínima a nivel de aplicación
mientras se implementa ISSUE-D.

Diseño deliberadamente simple (sin Redis ni dependencias nuevas):
- Ventana deslizante en memoria de proceso, por IP + endpoint.
- Suficiente para un solo contenedor/proceso (el despliegue actual en el VPS
  es un único contenedor `kyc-backend`, sin múltiples réplicas/workers).
- Si en el futuro se escala a múltiples workers/instancias, esto debe
  migrarse a un backend compartido (Redis) para que el límite sea global.
"""

import time
from collections import defaultdict
from typing import Dict, List

from fastapi import HTTPException, Request, status

# {clave: [timestamps de intentos recientes]}
_intentos: Dict[str, List[float]] = defaultdict(list)


def _client_ip(request: Request) -> str:
    # Respeta X-Forwarded-For si el proxy (Nginx) lo setea; si no, usa la IP directa.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(request: Request, bucket: str, max_intentos: int, ventana_segundos: int) -> None:
    """
    Lanza HTTPException 429 si la IP superó `max_intentos` dentro de la
    ventana de tiempo para este `bucket` (nombre lógico del endpoint).
    """
    ahora = time.monotonic()
    clave = f"{bucket}:{_client_ip(request)}"

    timestamps = _intentos[clave]
    corte = ahora - ventana_segundos
    vigentes = [t for t in timestamps if t > corte]

    if len(vigentes) >= max_intentos:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de volver a intentarlo."
        )

    vigentes.append(ahora)
    _intentos[clave] = vigentes
