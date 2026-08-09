"""
Endpoints de Autenticación
==========================

Login y gestión de tokens.
"""

from datetime import datetime
from core.timezone_utils import utcnow_naive
from typing import Any
from fastapi import APIRouter, HTTPException, Depends, status, Request
from beanie import PydanticObjectId

from core.security import (
    verify_password,
    create_access_token,
    create_password_reset_token,
    create_email_verification_token,
    decode_access_token,
    get_password_hash,
)
from core.config import settings
from core.email_utils import send_email, build_password_reset_email, build_email_verification_email
from core.rate_limit import check_rate_limit
from schemas.auth import (
    LoginRequest,
    TokenResponse,
    CurrentUserResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyEmailRequest,
)
from beanie.operators import Or
from models.user import User
from models.student import Student
from api.dependencies import get_current_user
from typing import Union

router = APIRouter()


@router.post("/forgot-password", summary="Solicitar restablecimiento de contraseña")
async def forgot_password(data: ForgotPasswordRequest, request: Request) -> Any:
    """
    Envía (de forma automática) un enlace de restablecimiento al correo si existe
    una cuenta (User o Student) con ese email. Respuesta genérica por seguridad.
    """
    # AUDITORÍA (ALTO): sin límite, un atacante podía disparar envíos de
    # correo masivos/spam a cualquier email con solo probar direcciones.
    check_rate_limit(request, "forgot-password", max_intentos=5, ventana_segundos=15 * 60)

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
        await send_email(email, "Restablece tu contraseña - Posgrado UAGRM", html)

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


@router.post("/verify-email", summary="Confirmar correo electrónico")
async def verify_email(data: VerifyEmailRequest) -> Any:
    """
    ISSUE-A-VERIFICACION: valida el token del correo y marca la cuenta
    (User o Student) como email_verificado=True. NO bloquea el acceso al
    sistema si no se verifica -- es informativo/de confianza, no un gate.
    """
    payload = decode_access_token(data.token)
    if not payload or payload.get("purpose") != "email_verification":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El enlace es inválido o ha expirado. Solicita uno nuevo desde tu perfil."
        )

    user_id = payload.get("sub")
    user_type = payload.get("user_type")
    email_en_token = payload.get("email")
    if not user_id or not user_type or not email_en_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Enlace inválido.")

    if user_type == "user":
        target = await User.get(PydanticObjectId(user_id))
    else:
        target = await Student.get(PydanticObjectId(user_id))

    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta no encontrada.")

    # Si el correo cambió después de generar el enlace, el enlace viejo ya no aplica.
    if (target.email or "").strip().lower() != email_en_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Este enlace corresponde a un correo que ya no está vigente en tu cuenta. Solicita uno nuevo."
        )

    if not target.email_verificado:
        target.email_verificado = True
        target.fecha_verificacion_email = utcnow_naive()
        await target.save()

    return {"message": "Correo verificado correctamente."}


@router.post(
    "/resend-verification",
    summary="Reenviar correo de verificación",
    responses={401: {"description": "No autenticado"}}
)
async def resend_verification(
    request: Request,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    ISSUE-A-VERIFICACION: el usuario autenticado (personal o estudiante) pide
    un nuevo correo de verificación para su email actual. Protegido con
    rate limit para no permitir espamear el buzón de un tercero.
    """
    check_rate_limit(request, "resend-verification", max_intentos=3, ventana_segundos=15 * 60)

    if not current_user.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tu cuenta no tiene un correo registrado.")

    if current_user.email_verificado:
        return {"message": "Tu correo ya está verificado."}

    user_type = "user" if isinstance(current_user, User) else "student"
    token = create_email_verification_token(str(current_user.id), user_type, current_user.email)
    verify_link = f"{settings.FRONTEND_URL.rstrip('/')}/auth/verify-email?token={token}"
    nombre = getattr(current_user, "nombre", None) or getattr(current_user, "username", None) or "usuario"
    html = build_email_verification_email(nombre, verify_link, settings.EMAIL_VERIFICATION_EXPIRE_MINUTES // 60)
    enviado = await send_email(current_user.email, "Confirma tu correo - Posgrado UAGRM", html)

    return {
        "enviado": enviado,
        "message": "Te enviamos un enlace de verificación a tu correo." if enviado
                    else "No se pudo enviar el correo en este momento. Intenta de nuevo más tarde."
    }


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
async def login_user(login_data: LoginRequest, request: Request) -> Any:
    """
    Login para administradores y personal (docente/staff)

    **Acceso público** (no requiere autenticación)

    **Credenciales:**
    - `username`: Username, email o carnet (CI) del personal
    - `password`: Contraseña

    **US-002 (2026-08-03):** Si el identificador matchea un estudiante pero
    NO un usuario administrativo, retorna 403 con mensaje indicando que use
    el portal "Estudiantes". No expone si la cuenta existe.

    **Retorna:** JWT Token de acceso
    """
    # AUDITORÍA (ALTO #8 - seguridad): sin límite, fuerza bruta de contraseñas
    # era completamente viable contra este endpoint. Ver core/rate_limit.py.
    check_rate_limit(request, "login", max_intentos=10, ventana_segundos=15 * 60)

    # ISSUE-Q-LOGIN-MULTIPLE (2026-07-09): el personal (docentes principalmente)
    # puede iniciar sesión indistintamente con su username, su email o su carnet
    # (CI). Para administrativos con perfiles personalizados, username/email
    # siguen funcionando igual; el carnet solo hace match si la cuenta lo tiene.
    # US-002 (2026-08-03): endurecimiento por perfil. Si el identificador matchea
    # un Student pero NO un User, devolvemos 403 con mensaje claro para que el
    # frontend redirija al portal correcto, en vez de "credenciales incorrectas"
    # (que confundiría al usuario y no respeta la separación de perfiles).
    identificador = login_data.username.strip()
    
    # Buscar todos los usuarios que coincidan
    users = await User.find(
        Or(
            User.username == identificador,
            User.email == identificador.lower(),
            User.carnet == identificador
        )
    ).to_list()
    
    if not users:
        # US-002: ¿quizás es un carnet de estudiante intentando entrar al portal
        # administrativo? Lo verificamos para devolver un error más informativo.
        student = await Student.find_one(
            Or(
                Student.registro == identificador,
                Student.email == identificador.lower(),
                Student.carnet == identificador
            )
        )
        if student:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta cuenta es de Estudiante. Para ingresar, use el portal 'Estudiantes' desde la pantalla principal.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    # Si hay más de un usuario con el mismo email o carnet, requerir el username exacto
    if len(users) > 1 and identificador != users[0].username:
        # Verificamos si el identificador es exactamente igual a alguno de los usernames
        exact_match = next((u for u in users if u.username == identificador), None)
        if exact_match:
            user = exact_match
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Hay múltiples perfiles administrativos asociados a este correo/carnet. Por favor, inicie sesión utilizando su Nombre de Usuario específico para indicar a qué perfil desea ingresar."
            )
    else:
        user = users[0]

    
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
    user.ultimo_acceso = utcnow_naive()
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
async def login_student(login_data: LoginRequest, request: Request) -> Any:
    """
    Login para estudiantes

    **Acceso público** (no requiere autenticación)

    **Credenciales:**
    - `username`: Registro, correo o carnet (CI) del estudiante
    - `password`: Contraseña (convención por defecto: 'Uagrm.<CI>')

    **US-002 (2026-08-03):** Si el identificador matchea un usuario
    administrativo/docente pero NO un estudiante, retorna 403 con mensaje
    indicando que use el portal correspondiente. No expone si la cuenta existe.

    **Retorna:** JWT Token de acceso
    """
    # AUDITORÍA (ALTO #8 - seguridad): ver nota equivalente en login_user.
    check_rate_limit(request, "login-student", max_intentos=10, ventana_segundos=15 * 60)

    # ISSUE-Q-LOGIN-MULTIPLE (2026-07-09): el estudiante puede iniciar sesión
    # indistintamente con su número de registro, su correo o su carnet (CI).
    # La contraseña inicial por defecto es 'Uagrm.<CI>' (ya la puede cambiar).
    # US-002 (2026-08-03): endurecimiento por perfil. Si el identificador matchea
    # un User (docente/admin) pero NO un Student, devolvemos 403 con mensaje
    # claro en vez de "credenciales incorrectas".
    identificador = login_data.username.strip()
    student = await Student.find_one(
        Or(
            Student.registro == identificador,
            Student.email == identificador.lower(),
            Student.carnet == identificador
        )
    )
    
    if not student:
        # US-002: ¿quizás es una cuenta de personal/staff intentando entrar al
        # portal de Estudiantes? Lo verificamos para devolver un error más
        # informativo y no exponer que la cuenta existe.
        user = await User.find_one(
            Or(
                User.username == identificador,
                User.email == identificador.lower(),
                User.carnet == identificador
            )
        )
        if user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Esta cuenta es de Personal (docente/administrativo). Para ingresar, use el portal correspondiente desde la pantalla principal.",
                headers={"WWW-Authenticate": "Bearer"},
            )
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


# ============================================================================
# R36 (2026-08-08, Kevin): Login multi-perfil via Account
# ============================================================================
# Una persona puede tener VARIOS perfiles (Student + User con diferentes roles)
# con el mismo username y password. Este endpoint:
# 1. Busca en Account por username/email/carnet
# 2. Valida password
# 3. Carga todos los perfiles asociados (Student + User)
# 4. Si hay 1 perfil: retorna TokenResponse directo (como /login)
# 5. Si hay 2+ perfiles: retorna MultiProfileLoginResponse con lista
#    para que el frontend muestre un selector
# 6. Nuevo endpoint /login/account/select/{profile_id} para confirmar
#    cual perfil usar y obtener el token
# ============================================================================

class MultiProfileLoginResponse(BaseModel):
    """Response cuando el Account tiene multiples perfiles."""
    requires_selection: bool = True
    account_id: str
    username: str
    email: str
    carnet_identidad: Optional[str] = None
    nombre_completo: Optional[str] = None
    profiles: list = []  # [{profile_type, profile_id, display_name, extra}]


class SelectProfileRequest(BaseModel):
    """Request para confirmar el perfil a usar."""
    account_id: str
    profile_id: str  # ID del Student o User seleccionado
    profile_type: str  # "student" o "user"


@router.post(
    "/login/account",
    response_model=Union[TokenResponse, MultiProfileLoginResponse],
    summary="Login multi-perfil (R36)",
    responses={
        200: {"description": "Login exitoso (1 perfil) o selector de perfiles (multi)"},
        401: {"description": "Credenciales incorrectas"},
        403: {"description": "Cuenta inactiva"}
    }
)
async def login_account(login_data: LoginRequest, request: Request) -> Any:
    """
    R36 (2026-08-08, Kevin): Login multi-perfil via Account.

    Caso de uso: una persona es estudiante de un programa Y docente del
    mismo programa. Tiene el mismo username y password para ambos
    perfiles. Este endpoint detecta eso y devuelve la lista de perfiles
    para que el usuario elija con cual entrar.

    Si el Account tiene 1 solo perfil, retorna TokenResponse directo
    (mismo comportamiento que /login o /login/student).
    """
    from models.account import Account
    from pydantic import BaseModel as _BM
    _BM.model_rebuild()  # asegurar que MultiProfileLoginResponse esta registrado

    check_rate_limit(request, "login-account", max_intentos=10, ventana_segundos=15 * 60)

    identificador = login_data.username.strip()

    # Buscar Account por username, email o carnet
    account = await Account.find_one(
        Or(
            Account.username == identificador,
            Account.email == identificador.lower(),
            Account.carnet_identidad == identificador,
        )
    )

    if not account:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not account.activo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cuenta inactiva")

    if not verify_password(login_data.password, account.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Actualizar last_login_at
    account.last_login_at = utcnow_naive()
    await account.save()

    # Cargar todos los perfiles asociados al account
    profiles = []

    # Buscar Students
    students = await Student.find(Student.account_id == account.id).to_list()
    for s in students:
        profiles.append({
            "profile_type": "student",
            "profile_id": str(s.id),
            "display_name": f"{s.nombre or ''} {s.apellidos or ''}".strip() or s.registro,
            "extra": {
                "registro": s.registro,
                "email": s.email,
            }
        })

    # Buscar Users
    users = await User.find(User.account_id == account.id).to_list()
    for u in users:
        profiles.append({
            "profile_type": "user",
            "profile_id": str(u.id),
            "display_name": u.nombre_funcional or u.username,
            "extra": {
                "username": u.username,
                "rol": u.rol.value,
                "email": u.email,
            }
        })

    if not profiles:
        # Account sin profiles (raro, pero posible durante la migracion)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Cuenta sin perfiles asociados. Contacte al administrador.",
        )

    # Si solo 1 perfil, retornar TokenResponse directo (como /login normal)
    if len(profiles) == 1:
        p = profiles[0]
        if p["profile_type"] == "student":
            student = await Student.get(PydanticObjectId(p["profile_id"]))
            student.ultimo_acceso = utcnow_naive()
            await student.save()
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
                role="student",
            )
        else:
            user = await User.get(PydanticObjectId(p["profile_id"]))
            user.ultimo_acceso = utcnow_naive()
            await user.save()
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
                role=user.rol.value,
            )

    # Multi-perfil: devolver lista para selector
    return MultiProfileLoginResponse(
        requires_selection=True,
        account_id=str(account.id),
        username=account.username,
        email=account.email,
        carnet_identidad=account.carnet_identidad,
        nombre_completo=account.nombre_completo,
        profiles=profiles,
    )


@router.post(
    "/login/account/select",
    response_model=TokenResponse,
    summary="Seleccionar perfil despues de login multi-perfil",
    responses={
        200: {"description": "Token generado"},
        401: {"description": "Account o perfil no valido"},
    }
)
async def select_account_profile(req: SelectProfileRequest) -> Any:
    """
    R36: Despues de que /login/account devuelve varios perfiles, el
    frontend llama a este endpoint con el profile_id seleccionado
    y recibe el TokenResponse para entrar con ese perfil especifico.
    """
    from models.account import Account

    try:
        account_oid = PydanticObjectId(req.account_id)
        profile_oid = PydanticObjectId(req.profile_id)
    except Exception:
        raise HTTPException(status_code=400, detail="IDs invalidos")

    account = await Account.get(account_oid)
    if not account or not account.activo:
        raise HTTPException(status_code=401, detail="Cuenta invalida")

    if req.profile_type == "student":
        profile = await Student.get(profile_oid)
        if not profile or profile.account_id != account.id:
            raise HTTPException(status_code=401, detail="Perfil no asociado a esta cuenta")
        profile.ultimo_acceso = utcnow_naive()
        await profile.save()
        access_token = create_access_token(
            data={"sub": str(profile.id), "user_type": "student", "role": "student"}
        )
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_type="student",
            user_id=str(profile.id),
            role="student",
        )
    else:
        profile = await User.get(profile_oid)
        if not profile or profile.account_id != account.id:
            raise HTTPException(status_code=401, detail="Perfil no asociado a esta cuenta")
        profile.ultimo_acceso = utcnow_naive()
        await profile.save()
        access_token = create_access_token(
            data={"sub": str(profile.id), "user_type": "user", "role": profile.rol.value}
        )
        return TokenResponse(
            access_token=access_token,
            token_type="bearer",
            user_type="user",
            user_id=str(profile.id),
            role=profile.rol.value,
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
            registro=None,
            terminos_aceptados=current_user.terminos_aceptados,  # ISSUE-Q-PRE (2026-07-29): extendido a todo el personal
            nombre_funcional=current_user.nombre_funcional,
            cursos_asignados=current_user.cursos_asignados,  # ISSUE-P-SEGMENTACION
            subtipo_coordinador=current_user.subtipo_coordinador.value if current_user.subtipo_coordinador else None,  # ISSUE-R-PERFIL-GENERICO
            email_verificado=current_user.email_verificado  # ISSUE-A-VERIFICACION
        )
    else:  # Student
        perfil_completado = all([
            current_user.celular,
            current_user.domicilio,
            current_user.fecha_nacimiento,
            current_user.carnet
        ])

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
            terminos_aceptados=current_user.terminos_aceptados,  # ISSUE-Q-PRE
            email_verificado=current_user.email_verificado,  # ISSUE-A-VERIFICACION
            perfil_completado=perfil_completado
        )


# ISSUE-Q-PRE (2026-07-29): endpoint unificado de aceptación de TyC.
# Funciona para User (admin/docente) Y Student. Reemplaza al antiguo
# /students/me/accept-terms (que sigue activo para compatibilidad).
from services import user_service, student_service

@router.post(
    "/me/accept-terms",
    summary="Aceptar Términos y Condiciones (ISSUE-Q-PRE)",
    response_model=dict,
    responses={
        200: {"description": "Términos aceptados (o ya estaban aceptados)"},
        401: {"description": "No autenticado"}
    }
)
async def accept_terms(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Registra la aceptación del reglamento de Posgrado para el usuario autenticado.

    Funciona tanto para personal administrativo/docente (User) como para
    estudiantes (Student). Idempotente: la fecha de primera aceptación se
    preserva como evidencia histórica.
    """
    if isinstance(current_user, User):
        updated = await user_service.accept_terms(user=current_user)
    else:
        updated = await student_service.accept_terms(student=current_user)

    return {
        "ok": True,
        "user_type": "user" if isinstance(current_user, User) else "student",
        "terminos_aceptados": updated.terminos_aceptados,
        "fecha_aceptacion_terminos": updated.fecha_aceptacion_terminos,
    }
