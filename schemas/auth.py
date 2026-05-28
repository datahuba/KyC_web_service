from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime
from models.base import PyObjectId

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user_type: str
    user_id: str
    role: str

class CurrentUserResponse(BaseModel):
    id: PyObjectId = Field(..., alias="_id")
    username: str
    email: EmailStr
    role: str
    user_type: str
    activo: bool
    ultimo_acceso: Optional[datetime] = None
    
    # NUEVOS CAMPOS AÑADIDOS PARA SOPORTAR NOMBRE Y REGISTRO EN ESTUDIANTES
    nombre: Optional[str] = None
    registro: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True
    }
    