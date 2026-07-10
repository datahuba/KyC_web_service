from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List
from datetime import datetime
from models.base import PyObjectId

class LoginRequest(BaseModel):
    username: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str = Field(..., description="Token recibido en el correo")
    new_password: str = Field(..., min_length=5, description="Nueva contraseña (mínimo 5 caracteres)")


class VerifyEmailRequest(BaseModel):
    """ISSUE-A-VERIFICACION: confirma el correo con el token recibido."""
    token: str = Field(..., description="Token recibido en el correo de verificación")

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

    # ISSUE-Q-PRE: si el estudiante ya aceptó el reglamento de Posgrado.
    # Siempre True para personal administrativo/docente (no aplica a ellos).
    terminos_aceptados: bool = True

    # ISSUE-P-SEGMENTACION: expone la segmentación de cursos del propio usuario
    # para que el frontend pueda ocultar cursos no asignados en selectores
    # (ej. filtro de curso en /app/payments para Cobranza/Encargado de Curso).
    # Lista vacía = sin restricción (acceso total, comportamiento por defecto).
    nombre_funcional: Optional[str] = None
    cursos_asignados: List[PyObjectId] = Field(default_factory=list)

    # ISSUE-R-PERFIL-GENERICO: subtipo del coordinador (financiero/academico/investigacion).
    # El frontend lo usa para habilitar las vistas económicas solo al financiero.
    subtipo_coordinador: Optional[str] = None

    # ISSUE-A-VERIFICACION: no bloqueante, solo informativo para mostrar un
    # banner sugiriendo verificar el correo (no impide el uso del sistema).
    email_verificado: bool = False

    perfil_completado: bool = True # Para mostrar banner recordatorio a estudiantes

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True
    }
    