"""
Módulo de Seguridad
===================

Funciones para autenticación y manejo de contraseñas.
"""

from datetime import datetime, timedelta
from core.timezone_utils import utcnow_naive
from typing import Optional
from jose import JWTError, jwt
import bcrypt
from core.config import settings


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verificar si una contraseña coincide con su hash
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Contraseña hasheada
        
    Returns:
        True si coinciden, False si no
    """
    password_bytes = plain_password.encode('utf-8')
    hashed_bytes = hashed_password.encode('utf-8')
    return bcrypt.checkpw(password_bytes, hashed_bytes)


def get_password_hash(password: str) -> str:
    """
    Hashear una contraseña usando bcrypt
    
    Args:
        password: Contraseña en texto plano
        
    Returns:
        Contraseña hasheada
    """
    password_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password_bytes, salt)
    return hashed.decode('utf-8')


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crear un token JWT
    
    Args:
        data: Datos a incluir en el token (ej: {"sub": user_id, "role": "admin"})
        expires_delta: Tiempo de expiración personalizado
        
    Returns:
        Token JWT como string
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = utcnow_naive() + expires_delta
    else:
        expire = utcnow_naive() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def create_password_reset_token(user_id: str, user_type: str) -> str:
    """
    Crear un token de un solo propósito para restablecer la contraseña.
    Expira según PASSWORD_RESET_EXPIRE_MINUTES.
    """
    return create_access_token(
        {"sub": user_id, "user_type": user_type, "purpose": "password_reset"},
        expires_delta=timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES)
    )


def create_email_verification_token(user_id: str, user_type: str, email: str) -> str:
    """
    ISSUE-A-VERIFICACION: token de un solo propósito para confirmar un correo.
    Incluye el email en el payload (no solo el user_id) para que, si el usuario
    cambia de correo antes de hacer clic en un enlace viejo, ese enlace viejo
    quede invalidado automáticamente al no coincidir con el email actual.
    """
    return create_access_token(
        {"sub": user_id, "user_type": user_type, "purpose": "email_verification", "email": email.strip().lower()},
        expires_delta=timedelta(minutes=settings.EMAIL_VERIFICATION_EXPIRE_MINUTES)
    )


def decode_access_token(token: str) -> Optional[dict]:
    """
    Decodificar y validar un token JWT
    
    Args:
        token: Token JWT
        
    Returns:
        Payload del token si es válido, None si no
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None
