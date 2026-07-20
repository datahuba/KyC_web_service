import asyncio
import logging
import sys
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from core.config import settings
from core.database import init_db
from api.api import api_router

# TECH-004: Sentry (error tracking). Si SENTRY_DSN no está configurado, la
# llamada a init() es un no-op — Sentry queda deshabilitado sin afectar el
# funcionamiento. Para activarlo: crear proyecto en sentry.io → setear
# SENTRY_DSN en .env del backend.
if settings.SENTRY_DSN:
    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.starlette import StarletteIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            environment=settings.SENTRY_ENVIRONMENT,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            integrations=[
                FastApiIntegration(),
                StarletteIntegration(),
                LoggingIntegration(level=logging.INFO, event_level=logging.ERROR),
            ],
            # Capturar info del entorno sin datos sensibles
            send_default_pii=False,
        )
        print(f"[sentry] Inicializado (env={settings.SENTRY_ENVIRONMENT}, traces={settings.SENTRY_TRACES_SAMPLE_RATE})", file=sys.stdout)
    except ImportError:
        print("[sentry] sentry-sdk no instalado. pip install sentry-sdk[fastapi] para activarlo.", file=sys.stdout)
    except Exception as e:
        print(f"[sentry] Error inicializando: {e}", file=sys.stdout)

logger = logging.getLogger("kyc.congelado_job")

# Configurar el logger de kyc.* (FIX 2026-07-17): sin handler ni nivel
# explícito, los logger.info() se perdían silenciosamente aunque la task
# se estuviera ejecutando. Agregamos un handler de stdout y forzamos nivel
# INFO, salvo que se haya configurado otra cosa en el root.
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    ))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # evitar duplicación si el root también loguea

# ISSUE-P-CONGELADO / ISSUE-R-NOTIFICACION-MORA: job periódico (cada 24h) que
# revisa inactividad de pagos, notifica mora preventiva y marca abandono
# automático como último recurso. Corre en background sin dependencias
# nuevas (asyncio.create_task); también existe el endpoint manual
# POST /enrollments/jobs/verificar-inactividad para disparo bajo demanda.
_INTERVALO_JOB_CONGELADO_SEGUNDOS = 24 * 60 * 60


async def _job_verificar_inactividad_periodico():
    from services import congelado_service

    logger.info(
        f"[job-congelado] INICIADO — primera ejecución en "
        f"{_INTERVALO_JOB_CONGELADO_SEGUNDOS // 3600}h, "
        f"luego cada {_INTERVALO_JOB_CONGELADO_SEGUNDOS // 3600}h"
    )
    while True:
        # IMPORTANTE: se espera el intervalo COMPLETO antes de la primera
        # ejecución. Con uvicorn --reload en desarrollo, el evento de
        # startup se dispara en CADA guardado de archivo; si esta corrida
        # fuera inmediata, el job real (sin acotar) se ejecutaría contra la
        # base de datos compartida (la misma de producción) en cada reload,
        # afectando inscripciones reales sin ninguna intención de hacerlo.
        await asyncio.sleep(_INTERVALO_JOB_CONGELADO_SEGUNDOS)
        try:
            resultado = await congelado_service.verificar_inactividad_pagos()
            logger.info(f"[job-congelado] ejecución OK: {resultado}")
        except Exception as e:
            logger.exception(f"[job-congelado] Error en la verificación periódica: {e}")

app = FastAPI(
    title=settings.APP_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Compresión Gzip para todas las respuestas mayores a 1000 bytes (1 KB)
# Reduce drásticamente el tamaño de los payloads JSON grandes de la API
app.add_middleware(GZipMiddleware, minimum_size=1000)

# CORS. En producción la app es same-origin (nginx enruta /api/ bajo el mismo
# host), por lo que normalmente no haría falta. Pero durante/después de la
# migración de dominio (datahuba.com -> postgrado.datahuba.com) puede haber
# llamadas cross-origin entre ambos, así que se habilitan explícitamente los
# orígenes conocidos. En DEBUG (local) se permite todo.
_cors_origins = [
    "https://datahuba.com",
    "https://www.datahuba.com",
    "https://postgrado.datahuba.com",
]
_frontend_origin = (settings.FRONTEND_URL or "").rstrip("/")
if _frontend_origin and _frontend_origin not in _cors_origins:
    _cors_origins.append(_frontend_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.DEBUG else _cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# TECH-004: handler global de excepciones. Sentry captura automáticamente
# las excepciones no manejadas, pero este handler las registra con un
# mensaje consistente en logs del servidor también, y devuelve un 500
# genérico al cliente (sin filtrar detalles internos).
from fastapi import Request
from fastapi.responses import JSONResponse


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Loggear con traceback
    import traceback
    logger.error(
        f"[500] {request.method} {request.url.path}: {type(exc).__name__}: {exc}\n"
        f"{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor. El equipo técnico ha sido notificado."},
    )

@app.on_event("startup")
async def start_db():
    await init_db()
    # ISSUE-P-CONGELADO: lanza el job periódico en background, sin bloquear
    # el arranque del servidor ni requerir un scheduler externo. Desactivable
    # vía JOB_CONGELADO_ACTIVO=False en .env (recomendado en desarrollo local
    # con --reload, para no correr el job real contra la base compartida con
    # producción en cada guardado de archivo).
    if settings.JOB_CONGELADO_ACTIVO:
        task = asyncio.create_task(_job_verificar_inactividad_periodico())
        # Guardar referencia para evitar garbage collection (best practice en
        # Python 3.12+, donde las tasks sin referencia pueden ser GCed antes
        # de su primera await).
        _job_verificar_inactividad_periodico._task = task  # type: ignore
        logger.info("[job-congelado] task creada y referenciada")
    else:
        logger.warning("[job-congelado] DESACTIVADO por JOB_CONGELADO_ACTIVO=False")

@app.get("/")
async def root():
    return {"message": "Welcome to KyC Payment System API"}

app.include_router(api_router, prefix=settings.API_V1_STR)
