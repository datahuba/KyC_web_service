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
    nombre_completo: str = Field(..., min_length=1, description="Nombre completo")
    rol: UserRole = Field(default=UserRole.ADMIN, description="Rol de usuario")
    
    class Config:
        schema_extra = {
            "example": {
                "username": "secretaria1",
                "email": "sec@kyc.com",
                "password": "secure_password_123",
                "nombre_completo": "María González",
                "rol": "secretaria"
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
    nombre_completo: str
    rol: UserRole
    activo: bool
    ultimo_acceso: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    
    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439015",
                "username": "secretaria1",
                "email": "sec@kyc.com",
                "nombre_completo": "María González",
                "rol": "secretaria",
                "activo": True,
                "ultimo_acceso": "2024-02-01T10:00:00",
                "created_at": "2024-01-01T10:00:00",
                "updated_at": "2024-01-01T10:00:00"
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
    nombre_completo: Optional[str] = Field(None, min_length=1)
    rol: Optional[UserRole] = None
    activo: Optional[bool] = None
    
    class Config:
        schema_extra = {
            "example": {
                "nombre_completo": "María G. de López",
                "activo": False
            }
        }
