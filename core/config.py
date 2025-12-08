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
    
    
    model_config = {
        "env_file": ".env",
        "case_sensitive": True
    }

settings = Settings()
