from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field

class Settings(BaseSettings):
    """
    Configuración global de la aplicación
    
    Lee variables de entorno automáticamente.
    Prioridad:
    1. Variables de entorno del sistema
    2. Archivo .env
    3. Valores por defecto
    """
    
    # App
    APP_NAME: str = "KyC Payment System"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False
    DEVELOPMENT_MODE: bool = Field(default=False, env="DEVELOPMENT_MODE")
    
    # MongoDB
    MONGODB_URL: str = Field(..., env="MONGODB_URL")
    DATABASE_NAME: str = Field("kyc_db", env="DATABASE_NAME")
    
    # Security
    SECRET_KEY: str = Field(..., env="SECRET_KEY")
    ALGORITHM: str =  Field(..., env="ALGORITHM")
    ACCESS_TOKEN_EXPIRE_MINUTES: int =  Field(..., env="ACCESS_TOKEN_EXPIRE_MINUTES")
    
    # Cloudinary
    CLOUDINARY_CLOUD_NAME: str = Field(..., env="CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY: str = Field(..., env="CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET: str = Field(..., env="CLOUDINARY_API_SECRET")

    # Email / SMTP (opcional). Si no está configurado, el flujo de reseteo funciona
    # pero el enlace se registra en los logs en lugar de enviarse por correo.
    SMTP_HOST: Optional[str] = Field(default=None, env="SMTP_HOST")
    SMTP_PORT: int = Field(default=587, env="SMTP_PORT")
    SMTP_USER: Optional[str] = Field(default=None, env="SMTP_USER")
    SMTP_PASSWORD: Optional[str] = Field(default=None, env="SMTP_PASSWORD")
    SMTP_FROM: Optional[str] = Field(default=None, env="SMTP_FROM")
    SMTP_FROM_NAME: str = Field(default="Posgrado UAGRM", env="SMTP_FROM_NAME")
    SMTP_USE_TLS: bool = Field(default=True, env="SMTP_USE_TLS")

    # URL pública del frontend (para construir enlaces en correos)
    FRONTEND_URL: str = Field(default="http://localhost:5173", env="FRONTEND_URL")
    PASSWORD_RESET_EXPIRE_MINUTES: int = Field(default=30, env="PASSWORD_RESET_EXPIRE_MINUTES")
    # ISSUE-A-VERIFICACION: más largo que el reset de password porque no es
    # sensible (solo confirma que el correo es accesible, no cambia credenciales).
    EMAIL_VERIFICATION_EXPIRE_MINUTES: int = Field(default=1440, env="EMAIL_VERIFICATION_EXPIRE_MINUTES")  # 24h

    # ISSUE-P-CONGELADO: montos y plazos configurables sin tocar código
    TASA_CONGELAMIENTO_BS: float = Field(default=150.0, env="TASA_CONGELAMIENTO_BS")
    MULTA_REINCORPORACION_BS: float = Field(default=300.0, env="MULTA_REINCORPORACION_BS")
    # F-051 (2026-07-22, regla de Kevin): "1 mes sin pagar = en mora;
    # 2 meses = abandono automático". Antes era 20/30 días, ahora 30/60.
    DIAS_INACTIVIDAD_MORA: int = Field(default=30, env="DIAS_INACTIVIDAD_MORA")  # 1 mes
    DIAS_INACTIVIDAD_ABANDONO: int = Field(default=60, env="DIAS_INACTIVIDAD_ABANDONO")  # 2 meses
    # F-061 (2026-07-23, regla de Kevin): ventana de gracia para volverse
    # pasivo voluntario SIN multa. Mientras `dias_desde_inscripcion <= ventana`,
    # el pasivo se aprueba sin multa de reincorporación. Pasada la ventana, se
    # cobra `MULTA_REINCORPORACION_BS` al reactivar. Default 30 días (1 mes)
    # según la convención usada para mora.
    VENTANA_GRACIA_PASIVO_DIAS: int = Field(default=30, env="VENTANA_GRACIA_PASIVO_DIAS")  # 1 mes
    # Apaga el job automático en background (útil en desarrollo local para no
    # afectar la base compartida con producción por accidente en cada reload).
    # Por defecto ACTIVO; poner en False explícitamente en .env local si se
    # está iterando sobre este código con --reload.
    JOB_CONGELADO_ACTIVO: bool = Field(default=True, env="JOB_CONGELADO_ACTIVO")

    # TECH-004: Sentry (error tracking en producción). Si no se configura
    # SENTRY_DSN, Sentry no hace nada (no-op) — la integración es segura de
    # agregar sin afectar el funcionamiento. Para activarlo, crear un proyecto
    # en https://sentry.io y setear SENTRY_DSN en .env.
    SENTRY_DSN: Optional[str] = Field(default=None, env="SENTRY_DSN")
    SENTRY_TRACES_SAMPLE_RATE: float = Field(default=0.1, env="SENTRY_TRACES_SAMPLE_RATE")
    SENTRY_ENVIRONMENT: str = Field(default="production", env="SENTRY_ENVIRONMENT")

    # F-CACHE-SHARED (2026-08-08, Kevin): cache en memoria para lookups
    # frecuentes de students y enrollments. El cuello de los endpoints de
    # pagos NO era el query de payments sino los N+1 lookups de students +
    # enrollments que enrich hace en cada request. Con este cache, los
    # mismos IDs solo se buscan 1 vez cada TTL segundos (compartido entre
    # todos los requests concurrentes del proceso).
    # TTL: 30-60s es seguro porque los datos no son criticos en tiempo real
    # (nombre del estudiante, cantidad de cuotas). Un cambio de nombre
    # tarda hasta 60s en verse, aceptable para una lista de pagos.
    CACHE_ENABLED: bool = Field(default=True, env="CACHE_ENABLED")
    CACHE_TTL_STUDENTS_SECONDS: int = Field(default=60, env="CACHE_TTL_STUDENTS_SECONDS")
    CACHE_TTL_ENROLLMENTS_SECONDS: int = Field(default=30, env="CACHE_TTL_ENROLLMENTS_SECONDS")
    CACHE_MAX_ENTRIES: int = Field(default=1000, env="CACHE_MAX_ENTRIES")

    # F-PERF-DASHBOARD-PRECOMPUTE (2026-08-08, Kevin): background job que
    # pre-computa el dashboard cada X segundos para usuarios activos. Esto
    # elimina el cold del dashboard (1-13s) en la mayoria de los casos
    # porque el cache ya esta caliente cuando el user hace request.
    # - DASHBOARD_PRECOMPUTE_INTERVAL_SECONDS: cada cuanto se ejecuta
    #   el job. Default 240s (4 min) < TTL 300s (5 min) para garantizar
    #   que el cache siempre tenga data fresca cuando el user lo pida.
    # - DASHBOARD_PRECOMPUTE_ENABLED: kill switch. False desactiva el job.
    DASHBOARD_PRECOMPUTE_ENABLED: bool = Field(default=True, env="DASHBOARD_PRECOMPUTE_ENABLED")
    DASHBOARD_PRECOMPUTE_INTERVAL_SECONDS: int = Field(default=240, env="DASHBOARD_PRECOMPUTE_INTERVAL_SECONDS")

    model_config = {
        "env_file": ".env",
        "case_sensitive": True
    }

settings = Settings()
