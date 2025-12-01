"""
Módulo de Seguridad
===================

Funciones para autenticación y manejo de contraseñas.
"""

from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from core.config import settings

# Contexto para hashear contraseñas con bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verificar si una contraseña coincide con su hash
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Contraseña hasheada
        
    Returns:
        True si coinciden, False si no
    """
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Hashear una contraseña usando bcrypt
    
    Args:
        password: Contraseña en texto plano
        
    Returns:
        Contraseña hasheada
    """
    return pwd_context.hash(password)


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
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


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
