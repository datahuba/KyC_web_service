"""
Schemas de Autenticación
========================

Schemas para login y tokens.
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from models.enums import UserRole
from models.base import PyObjectId


class LoginRequest(BaseModel):
    """Schema para solicitud de login"""
    username: str = Field(..., description="Username o registro")
    password: str = Field(..., description="Contraseña")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "admin",
                "password": "admin123"
            }
        }
    }


class TokenResponse(BaseModel):
    """Schema para respuesta de token"""
    access_token: str = Field(..., description="JWT access token")
    token_type: str = Field(default="bearer", description="Tipo de token")
    user_type: str = Field(..., description="Tipo de usuario: 'user' o 'student'")
    user_id: str = Field(..., description="ID del usuario")
    role: str = Field(..., description="Rol del usuario")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                "token_type": "bearer",
                "user_type": "user",
                "user_id": "507f1f77bcf86cd799439015",
                "role": "admin"
            }
        }
    }


class CurrentUserResponse(BaseModel):
    """Schema para información del usuario actual"""
    id: PyObjectId = Field(..., alias="_id")
    username: str
    email: str
    role: str
    user_type: str = Field(..., description="'user' o 'student'")
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439015",
                "username": "admin",
                "email": "admin@kyc.com",
                "role": "admin",
                "user_type": "user",
                "activo": True,
                "ultimo_acceso": "2024-02-01T10:00:00"
            }
        }
    }
