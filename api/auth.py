"""
Endpoints de Autenticación
==========================

Login y gestión de tokens.
"""

from datetime import datetime
from typing import Any
from fastapi import APIRouter, HTTPException, Depends, status
from beanie import PydanticObjectId

from core.security import (
    verify_password,
    create_access_token,
    create_password_reset_token,
    decode_access_token,
    get_password_hash,
)
from core.config import settings
from core.email_utils import send_email, build_password_reset_email
from schemas.auth import (
    LoginRequest,
    TokenResponse,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
)
from beanie.operators import Or
from models.user import User
from models.student import Student
from api.dependencies import get_current_user
from typing import Union

router = APIRouter()


@router.post("/forgot-password", summary="Solicitar restablecimiento de contraseña")
async def forgot_password(data: ForgotPasswordRequest) -> Any:
    """
    Envía (de forma automática) un enlace de restablecimiento al correo si existe
    una cuenta (User o Student) con ese email. Respuesta genérica por seguridad.
    """
    email = data.email.strip().lower()

    user = await User.find_one(User.email == email)
    student = await Student.find_one(Student.email == email) if not user else None
    target = user or student

    if target:
        user_type = "user" if user else "student"
        token = create_password_reset_token(str(target.id), user_type)
        reset_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/reset-password?token={token}"
        nombre = getattr(target, "nombre", None) or getattr(target, "username", None) or "usuario"
        html = build_password_reset_email(nombre, reset_link, settings.PASSWORD_RESET_EXPIRE_MINUTES)
        await send_email(email, "Restablece tu contraseña - Postgrado UAGRM", html)

    return {
        "message": "Si el correo está registrado, recibirás un enlace para restablecer tu contraseña."
    }


@router.post("/reset-password", summary="Restablecer contraseña con token")
async def reset_password(data: ResetPasswordRequest) -> Any:
    """Valida el token del correo y actualiza la contraseña de la cuenta."""
    payload = decode_access_token(data.token)
    if not payload or payload.get("purpose") != "password_reset":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace es inválido o ha expirado. Solicita uno nuevo."
        )

    user_id = payload.get("sub")
    user_type = payload.get("user_type")
    if not user_id or not user_type:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enlace inválido.")

    if user_type == "user":
        target = await User.get(PydanticObjectId(user_id))
    else:
        target = await Student.get(PydanticObjectId(user_id))

    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada.")

    target.password = get_password_hash(data.new_password)
    await target.save()

    return {"message": "Contraseña actualizada correctamente. Ya puedes iniciar sesión."}


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login Admin",
    responses={
        200: {"description": "Login exitoso, retorna JWT token"},
        401: {"description": "Credenciales incorrectas"},
        403: {"description": "Usuario inactivo"}
    }
)
async def login_user(login_data: LoginRequest) -> Any:
    """
    Login para administradores
    
    **Acceso público** (no requiere autenticación)
    
    **Credenciales:**
    - `username`: Username del admin
    - `password`: Contraseña
    
    **Retorna:** JWT Token de acceso
    """
    # Buscar usuario por username o email (el formulario del frontend acepta ambos)
    identificador = login_data.username.strip()
    user = await User.find_one(
        Or(
            User.username == identificador,
            User.email == identificador.lower()
        )
    )
    
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


@router.post(
    "/login/student",
    response_model=TokenResponse,
    summary="Login Estudiante",
    responses={
        200: {"description": "Login exitoso, retorna JWT token"},
        401: {"description": "Credenciales incorrectas"},
        403: {"description": "Estudiante inactivo"}
    }
)
async def login_student(login_data: LoginRequest) -> Any:
    """
    Login para estudiantes
    
    **Acceso público** (no requiere autenticación)
    
    **Credenciales:**
    - `username`: Número de registro del estudiante
    - `password`: Contraseña (inicialmente = carnet)
    
    **Retorna:** JWT Token de acceso
    """
    # Buscar estudiante por registro o email (el formulario del frontend acepta ambos)
    identificador = login_data.username.strip()
    student = await Student.find_one(
        Or(
            Student.registro == identificador,
            Student.email == identificador.lower()
        )
    )
    
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


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Ver Mi Perfil",
    responses={
        200: {"description": "Información del usuario autenticado"},
        401: {"description": "No autenticado - Token inválido o expirado"}
    }
)
async def get_me(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Ver información del usuario autenticado
    
    **Requiere:** Token JWT válido
    
    **Retorna:** Datos del usuario actual (Admin o Estudiante)
    """
    if isinstance(current_user, User):
        return CurrentUserResponse(
            _id=current_user.id,
            username=current_user.username,
            email=current_user.email,
            role=current_user.rol.value,
            user_type="user",
            activo=current_user.activo,
            ultimo_acceso=current_user.ultimo_acceso,
            nombre=current_user.username,  # Fallback de nombre para el personal administrativo
            registro=None
        )
    else:  # Student
        return CurrentUserResponse(
            _id=current_user.id,
            username=current_user.registro,
            email=current_user.email,
            role="student",
            user_type="student",
            activo=current_user.activo,
            ultimo_acceso=None,
            nombre=current_user.nombre,  # Inyección del nombre real desde la ficha del estudiante
            registro=current_user.registro,  # Inyección del código de registro oficial
            terminos_aceptados=current_user.terminos_aceptados  # ISSUE-Q-PRE
        )
    