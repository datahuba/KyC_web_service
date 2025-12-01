"""
Modelo de Usuario
=================

Gestiona los usuarios del sistema (administradores, staff, etc).
Colección MongoDB: users
"""

from datetime import datetime
from typing import Optional
from pydantic import Field, EmailStr
from .base import MongoBaseModel
from .enums import UserRole

class User(MongoBaseModel):
    """
    Modelo de Usuario del Sistema
    
    Representa a cualquier usuario que puede hacer login en el sistema administrativo.
    Nota: Los estudiantes tienen su propio modelo (Student), aunque podrían unificarse en el futuro.
    """
    
    username: str = Field(..., min_length=3, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico único")
    password: str = Field(..., description="Contraseña hasheada")
    
    rol: UserRole = Field(default=UserRole.ADMIN, description="Rol para permisos")
    activo: bool = Field(default=True, description="Si el usuario puede acceder al sistema")
    ultimo_acceso: Optional[datetime] = Field(None, description="Fecha del último login exitoso")
    
    class Settings:
        name = "users"

    class Config:
        schema_extra = {
            "example": {
                "username": "admin",
                "email": "admin@kyc.com",
                "password": "hashed_secret_password",
                "rol": "admin",
                "activo": True
            }
        }
