"""
Schemas de Usuario
==================

Define los schemas Pydantic para operaciones CRUD de usuarios del sistema.

Schemas incluidos:
-----------------
1. UserCreate: Para crear nuevos usuarios
2. UserResponse: Para mostrar usuarios (sin password)
3. UserUpdate: Para actualizar usuarios
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, EmailStr
from models.enums import UserRole
from models.base import PyObjectId

class UserCreate(BaseModel):
    """
    Schema para crear un nuevo usuario
    
    Uso: POST /users/
    """
    username: str = Field(..., min_length=3, description="Nombre de usuario único")
    email: EmailStr = Field(..., description="Correo electrónico único")
    password: str = Field(..., min_length=8, description="Contraseña (será hasheada)")
    rol: UserRole = Field(default=UserRole.ADMIN, description="Rol de usuario")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "username": "admin1",
                "email": "admin@kyc.com",
                "password": "secure_password_123",
                "rol": "admin"
            }
        }
    }

class UserResponse(BaseModel):
    """
    Schema para mostrar información de un usuario
    
    Uso: GET /users/{id}
    """
    id: PyObjectId = Field(..., alias="_id")
    username: str
    email: EmailStr
    rol: UserRole
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439015",
                "username": "secretaria1",
                "email": "sec@kyc.com",
                "rol": "admin",
                "activo": True,
                "ultimo_acceso": "2024-02-01T10:00:00",
                "created_at": "2024-01-01T10:00:00",
                "updated_at": "2024-01-01T10:00:00"
            }
        }
    }

class UserUpdate(BaseModel):
    """
    Schema para actualizar un usuario existente
    
    Uso: PATCH /users/{id}
    """
    username: Optional[str] = Field(None, min_length=3)
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)
    rol: Optional[UserRole] = None
    activo: Optional[bool] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "activo": False
            }
        }
    }
