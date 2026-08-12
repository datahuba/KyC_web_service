"""
Modelo Account (R36 - Multi-Perfil, 2026-08-08, Kevin)

Una persona puede tener VARIOS perfiles (Student, User con diferentes roles)
pero todos comparten la misma identidad (username + password).

Ejemplo REAL (encontrado 2026-08-09 por Kevin):
- Sandra Zabala tiene SZSCOBRANZA (rol=cobranza) Y SZSENCARGADO (rol=encargado_curso)
- Mismo email sandrazabala.2909@gmail.com, mismo carnet 6379343
- PERO usernames DIFERENTES (porque username es unique en User)
- Con multi-perfil, Sandra tendria 1 sola cuenta con 2 roles
"""
from datetime import datetime
from typing import Optional
import pymongo
from pydantic import BaseModel, Field, EmailStr

from .base import MongoBaseModel, PyObjectId
from core.timezone_utils import utcnow_naive


class Account(MongoBaseModel):
    """Identidad unificada de una persona en el sistema."""
    username: str = Field(..., min_length=3, description="Username unico (login)")
    email: EmailStr = Field(..., description="Email de contacto")
    password: str = Field(..., description="Contrasena hasheada (bcrypt)")
    carnet_identidad: Optional[str] = Field(None, description="CI de la persona")
    nombre_completo: Optional[str] = Field(None, description="Nombre real de la persona")
    activo: bool = Field(default=True, description="Si False, no puede hacer login")

    created_at: datetime = Field(default_factory=utcnow_naive)
    last_login_at: Optional[datetime] = Field(None, description="Ultimo login (cualquier perfil)")

    class Settings:
        name = "accounts"
        indexes = [
            pymongo.IndexModel([("username", pymongo.ASCENDING)], unique=True),
            pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=False),
            pymongo.IndexModel([("carnet_identidad", pymongo.ASCENDING)], unique=False),
        ]


class ProfileInfo(BaseModel):
    """Informacion de un perfil asociado a un Account (response del login multi-perfil)."""
    profile_type: str
    profile_id: str
    display_name: str
    extra: dict = {}
