"""
Dependencias de FastAPI
=======================

Dependencias para autenticación y autorización en endpoints.
"""

from typing import Optional, Union
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from beanie import PydanticObjectId

from core.security import decode_access_token
from models.user import User
from models.student import Student
from models.enums import UserRole

# Security scheme para JWT (auto_error=False permite bypass en modo desarrollo)
security = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Union[User, Student]:
    """
    Obtener el usuario actual desde el token JWT
    
    En modo desarrollo (DEVELOPMENT_MODE=true), retorna un usuario admin mock
    sin requerir autenticación.
    
    Returns:
        User o Student autenticado
        
    Raises:
        HTTPException 401: Si el token es inválido o el usuario no existe
    """
    from core.config import settings
    
    # Modo desarrollo: bypass de autenticación
    if settings.DEVELOPMENT_MODE:
        # Retornar un usuario SUPERADMIN mock para desarrollo
        mock_user = User(
            id=PydanticObjectId("000000000000000000000001"),
            username="dev_admin",
            password="mock_password",
            email="dev@example.com",
            rol=UserRole.SUPERADMIN,
            activo=True
        )
        return mock_user
    
    # Modo producción: autenticación normal
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Se requiere autenticación",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    payload = decode_access_token(token)
    
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_id: str = payload.get("sub")
    user_type: str = payload.get("user_type")
    
    if user_id is None or user_type is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Buscar usuario según el tipo
    if user_type == "user":
        user = await User.get(PydanticObjectId(user_id))
        if user is None or not user.activo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Usuario no encontrado o inactivo"
            )
        return user
    elif user_type == "student":
        student = await Student.get(PydanticObjectId(user_id))
        if student is None or not student.activo:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Estudiante no encontrado o inactivo"
            )
        return student
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tipo de usuario inválido"
        )


def require_superadmin(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea SUPERADMIN
    
    Solo usuarios de tipo User con rol SUPERADMIN pueden pasar
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de SUPERADMIN"
        )
    
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de SUPERADMIN"
        )
    
    return current_user


def require_admin(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> User:
    """
    Requiere que el usuario sea ADMIN o SUPERADMIN
    
    Solo usuarios de tipo User con rol ADMIN o SUPERADMIN pueden pasar
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de ADMIN o superior"
        )
    
    if current_user.rol not in [UserRole.ADMIN, UserRole.SUPERADMIN]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requiere rol de ADMIN o superior"
        )
    
    return current_user


def get_current_active_user(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Union[User, Student]:
    """
    Obtener usuario activo (cualquier rol autenticado)
    
    Alias para get_current_user, útil para endpoints que aceptan cualquier usuario autenticado
    """
    return current_user


def check_student_access(
    resource_student_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> bool:
    """
    Verificar si el usuario puede acceder a un recurso de estudiante
    
    - SUPERADMIN/ADMIN: Pueden acceder a cualquier recurso
    - STUDENT: Solo puede acceder a sus propios recursos
    
    Args:
        resource_student_id: ID del estudiante dueño del recurso
        current_user: Usuario actual
        
    Returns:
        True si tiene acceso
        
    Raises:
        HTTPException 403: Si no tiene acceso
    """
    # Admins tienen acceso total
    if isinstance(current_user, User):
        return True
    
    # Estudiantes solo acceden a sus propios recursos
    if isinstance(current_user, Student):
        if current_user.id != resource_student_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para acceder a este recurso"
            )
        return True
    
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso denegado"
    )
