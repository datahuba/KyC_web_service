"""
Modelo Account (R36 - Multi-Perfil, 2026-08-08, Kevin)

Una persona puede tener VARIOS perfiles (Student, User con diferentes roles)
pero todos comparten la misma identidad (username + password).

Caso de uso (Kevin):
"cada area que es estudiantes docentes y administrativos puedan tener
usuarios con las mismas contraseñas ya que eso puede pasar pero obviamente
son perfiles diferentes eso no hay que olvidarlo"

Ejemplo:
- María es estudiante de DIPL-IA-2026 (perfil Student)
- María es docente del mismo programa (perfil User, rol=docente)
- Con el mismo username y password puede acceder a ambos perfiles
- Un selector de perfil (frontend) le permite elegir con qué perfil entrar

Arquitectura:
- Account: tabla central con identidad (username, password, email, carnet)
- Student.account_id: link al Account
- User.account_id: link al Account
- Login: busca en Account, valida password, devuelve lista de perfiles

Migración:
- Por cada (Student.username + User.username) unico, crear 1 Account
- Vincular account_id en Student y User
- Script: scripts/migrate-to-account.py (dry-run + apply)
"""
from datetime import datetime
from typing import Optional
import pymongo
from pydantic import BaseModel, Field, EmailStr

from .base import MongoBaseModel, PyObjectId
from core.timezone_utils import utcnow_naive


class Account(MongoBaseModel):
    """
    Identidad unificada de una persona en el sistema.
    
    Mantiene la autenticacion centralizada. Una persona puede tener varios
    perfiles (Student + User) pero todos comparten la misma cuenta.
    
    R36 (2026-08-08, Kevin): cada area (estudiantes, docentes, administrativos)
    pueden tener usuarios con las mismas contraseñas porque son perfiles
    diferentes de la misma persona.
    """
    username: str = Field(
        ...,
        min_length=3,
        description="Username unico (login) - el mismo para todos los perfiles de la persona",
    )
    email: EmailStr = Field(
        ...,
        description="Email de contacto. Puede ser el mismo para todos los perfiles.",
    )
    password: str = Field(
        ...,
        description="Contrasena hasheada (bcrypt). UNA sola para todos los perfiles.",
    )
    carnet_identidad: Optional[str] = Field(
        None,
        description="CI de la persona. Opcional pero util para matching entre Student y User.",
    )
    nombre_completo: Optional[str] = Field(
        None,
        description="Nombre real de la persona (para mostrar en selector de perfil)",
    )
    activo: bool = Field(
        default=True,
        description="Si False, no puede hacer login en ningun perfil",
    )

    # Metadata
    created_at: datetime = Field(default_factory=utcnow_naive)
    last_login_at: Optional[datetime] = Field(
        None,
        description="Ultimo login (cualquier perfil). Util para detectar cuentas abandonadas.",
    )

    class Settings:
        name = "accounts"
        indexes = [
            # Username unico: es el identificador de login
            pymongo.IndexModel([("username", pymongo.ASCENDING)], unique=True),
            # Email NO es unico: una persona puede tener varios profiles con
            # el mismo email (mismo contacto, diferentes roles)
            pymongo.IndexModel([("email", pymongo.ASCENDING)], unique=False),
            # CI NO es unico: un CI puede tener varios profiles (estudiante +
            # docente, etc). Util para matching en migracion.
            pymongo.IndexModel([("carnet_identidad", pymongo.ASCENDING)], unique=False),
        ]
        json_schema_extra = {
            "example": {
                "username": "maria.lopez",
                "email": "maria.lopez@uagrm.edu",
                "password": "$2b$12$...",
                "carnet_identidad": "1234567",
                "nombre_completo": "Maria Lopez Garcia",
                "activo": True,
            }
        }


class ProfileInfo(BaseModel):
    """
    Informacion resumida de un perfil asociado a un Account.
    Se usa en el response del login multi-perfil para que el frontend
    muestre el selector de perfil.
    """
    profile_type: str = Field(..., description="Tipo: 'student' | 'user'")
    profile_id: str = Field(..., description="ID del Student o User")
    display_name: str = Field(..., description="Nombre a mostrar en el selector")
    extra: dict = Field(default_factory=dict, description="Datos extra (rol, curso, etc)")
