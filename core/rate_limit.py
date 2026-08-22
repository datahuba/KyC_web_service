"""
Rate Limiting en Mongo (compartido por los 4 workers)
=======================================================

AUDITORÍA (ALTO #8 - seguridad): /auth/login, /auth/login/student y
/auth/forgot-password no tenían ningún límite de intentos, dejando fuerza
bruta de contraseñas completamente viable. Ya estaba reconocido como deuda
técnica en ISSUE-D del backlog (Cloudflare WAF/Rate Limiting a nivel de
infraestructura), pero eso es una tarea de infraestructura pendiente y no
cubre el corto plazo. Esta es una barrera mínima a nivel de aplicación
mientras se implementa ISSUE-D.

F-FIX-RATE-LIMIT-MULTIWORKER (2026-08-22, encontrado en la auditoria
completa): la primera versión de este archivo guardaba los intentos en un
dict en memoria de proceso, asumiendo explícitamente "un único contenedor,
sin múltiples workers" — premisa falsa (producción corre
`uvicorn --workers 4`), el mismo error que causó el bug de multi-worker
del ticket SSE. El límite efectivo era hasta 4 veces más débil de lo
configurado. Ahora los intentos se persisten en `RateLimitAttempt`
(MongoDB), compartido por los 4 workers.
"""

from fastapi import HTTPException, Request, status

from core.timezone_utils import utcnow_naive
from models.rate_limit_attempt import RateLimitAttempt


def _client_ip(request: Request) -> str:
    # Respeta X-Forwarded-For si el proxy (Nginx) lo setea; si no, usa la IP directa.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def check_rate_limit(request: Request, bucket: str, max_intentos: int, ventana_segundos: int) -> None:
    """
    Lanza HTTPException 429 si la IP superó `max_intentos` dentro de la
    ventana de tiempo para este `bucket` (nombre lógico del endpoint).

    Best-effort, no estrictamente atómico (cuenta y después inserta) —
    aceptable para una barrera anti-fuerza-bruta, no es un límite de
    concurrencia que necesite garantía dura.
    """
    from datetime import timedelta

    ahora = utcnow_naive()
    clave = f"{bucket}:{_client_ip(request)}"
    corte = ahora - timedelta(seconds=ventana_segundos)

    vigentes = await RateLimitAttempt.find(
        RateLimitAttempt.clave == clave,
        RateLimitAttempt.timestamp > corte,
    ).count()

    if vigentes >= max_intentos:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos. Espera unos minutos antes de volver a intentarlo."
        )

    await RateLimitAttempt(clave=clave, timestamp=ahora).insert()
