"""
Endpoints de Autenticación
==========================

Login y gestión de tokens.
"""

from datetime import datetime
from typing import Any
from fastapi import APIRouter, HTTPException, Depends, status
from beanie import PydanticObjectId

from core.security import verify_password, create_access_token
from schemas.auth import LoginRequest, TokenResponse, CurrentUserResponse
from models.user import User
from models.student import Student
from api.dependencies import get_current_user
from typing import Union

router = APIRouter()


@router.post("/login", response_model=TokenResponse)
async def login_user(login_data: LoginRequest) -> Any:
    """
    Login para usuarios administrativos (User model)
    
    Autentica con username y password, devuelve JWT token
    """
    # Buscar usuario por username
    user = await User.find_one(User.username == login_data.username)
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar contraseña
    if not verify_password(login_data.password, user.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar que esté activo
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )
    
    # Actualizar último acceso
    user.ultimo_acceso = datetime.utcnow()
    await user.save()
    
    # Crear token
    access_token = create_access_token(
        data={
            "sub": str(user.id),
            "user_type": "user",
            "role": user.rol.value
        }
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_type="user",
        user_id=str(user.id),
        role=user.rol.value
    )


@router.post("/login/student", response_model=TokenResponse)
async def login_student(login_data: LoginRequest) -> Any:
    """
    Login para estudiantes (Student model)
    
    Autentica con registro (username) y password, devuelve JWT token
    """
    # Buscar estudiante por registro
    student = await Student.find_one(Student.registro == login_data.username)
    
    if not student:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar contraseña
    if not verify_password(login_data.password, student.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Verificar que esté activo
    if not student.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Estudiante inactivo"
        )
    
    # Crear token
    access_token = create_access_token(
        data={
            "sub": str(student.id),
            "user_type": "student",
            "role": "student"
        }
    )
    
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_type="student",
        user_id=str(student.id),
        role="student"
    )


@router.get("/me", response_model=CurrentUserResponse)
async def get_me(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener información del usuario actual
    
    Requiere autenticación
    """
    if isinstance(current_user, User):
        return CurrentUserResponse(
            _id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            role=current_user.rol.value,
            user_type="user",
            activo=current_user.activo,
            ultimo_acceso=current_user.ultimo_acceso
        )
    else:  # Student
        return CurrentUserResponse(
            _id=current_user.id,
            username=current_user.registro,
            email=current_user.email,
            role="student",
            user_type="student",
            activo=current_user.activo,
            ultimo_acceso=None
        )
