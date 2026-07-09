import asyncio
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from core.config import settings
from core.database import init_db
from api.api import api_router

logger = logging.getLogger("kyc.congelado_job")

# ISSUE-P-CONGELADO / ISSUE-R-NOTIFICACION-MORA: job periódico (cada 24h) que
# revisa inactividad de pagos, notifica mora preventiva y marca abandono
# automático como último recurso. Corre en background sin dependencias
# nuevas (asyncio.create_task); también existe el endpoint manual
# POST /enrollments/jobs/verificar-inactividad para disparo bajo demanda.
_INTERVALO_JOB_CONGELADO_SEGUNDOS = 24 * 60 * 60


async def _job_verificar_inactividad_periodico():
    from services import congelado_service

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
            logger.info(f"[job-congelado] {resultado}")
        except Exception as e:
            logger.error(f"[job-congelado] Error en la verificación periódica: {str(e)}")

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

@app.on_event("startup")
async def start_db():
    await init_db()
    # ISSUE-P-CONGELADO: lanza el job periódico en background, sin bloquear
    # el arranque del servidor ni requerir un scheduler externo. Desactivable
    # vía JOB_CONGELADO_ACTIVO=False en .env (recomendado en desarrollo local
    # con --reload, para no correr el job real contra la base compartida con
    # producción en cada guardado de archivo).
    if settings.JOB_CONGELADO_ACTIVO:
        asyncio.create_task(_job_verificar_inactividad_periodico())
    else:
        logger.warning("[job-congelado] DESACTIVADO por JOB_CONGELADO_ACTIVO=False")

@app.get("/")
async def root():
    return {"message": "Welcome to KyC Payment System API"}

app.include_router(api_router, prefix=settings.API_V1_STR)
