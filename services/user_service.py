"""
Servicio de Usuarios
====================

Lógica de negocio para operaciones CRUD de usuarios del sistema.
"""

from typing import List, Optional
from beanie import PydanticObjectId
from models.user import User
from schemas.user import UserCreate, UserUpdate
from models.enums import UserRole
from beanie.operators import Or

async def get_users(page: int = 1, per_page: int = 10) -> tuple[List[User], int]:
    """
    Obtener lista de usuarios administradores con paginación.
    Trae a toda la jerarquía administrativa, excluyendo estrictamente a Docentes.
    """
    query = User.find(
        Or(
            User.rol == UserRole.ADMIN,
            User.rol == UserRole.SUPERADMIN,
            User.rol == UserRole.MAE,
            User.rol == UserRole.CPD,
            User.rol == UserRole.COBRANZA,
            # ISSUE-R-ROLES: estos 2 roles se agregaron al enum pero nunca se
            # sumaron a este filtro — quedaban invisibles en /users/ pese a
            # poder crearse desde UserForm.svelte. Bug encontrado al verificar
            # ISSUE-R-VISTA-CURSOS (agrupación Globales/Asignados a Curso).
            User.rol == UserRole.ENCARGADO_CURSO,
            User.rol == UserRole.COORDINADOR
        )
    )
    total_count = await query.count()
    skip = (page - 1) * per_page
    users = await query.sort("-created_at").skip(skip).limit(per_page).to_list()
    return users, total_count


async def get_active_users() -> List[User]:
    """
    Obtener todos los usuarios activos que sean DOCENTES reales.
    """
    return await User.find(
        User.activo == True,
        User.rol == UserRole.DOCENTE
    ).sort("username").to_list()


async def get_user(id: PydanticObjectId) -> Optional[User]:
    """Obtener usuario por ID"""
    return await User.get(id)


async def get_user_by_username(username: str) -> Optional[User]:
    """Obtener usuario por username"""
    return await User.find_one(User.username == username)


async def get_user_by_email(email: str) -> Optional[User]:
    """Obtener usuario por email"""
    return await User.find_one(User.email == email)


async def get_user_by_email_excluding_id(email: str, user_id: PydanticObjectId) -> Optional[User]:
    """Buscar usuario por email excluyendo un ID específico (para updates)."""
    existing = await User.find_one(User.email == email)
    if existing and existing.id != user_id:
        return existing
    return None


async def get_user_by_username_excluding_id(username: str, user_id: PydanticObjectId) -> Optional[User]:
    """Buscar usuario por username excluyendo un ID específico (para updates)."""
    existing = await User.find_one(User.username == username)
    if existing and existing.id != user_id:
        return existing
    return None


async def create_user(user_in: UserCreate) -> User:
    """
    Crear nuevo usuario (hasheo automático).

    GAP-1 (audio 2026-07-08): si no se especifica `password` pero sí `carnet`,
    se genera la contraseña inicial con la convención institucional
    'Uagrm.<CI>' (ej. CI 1234567 -> 'Uagrm.1234567'). El schema `UserCreate`
    ya garantiza que al menos uno de los dos esté presente.
    """
    from core.security import get_password_hash

    user_data = user_in.model_dump()
    password_plano = user_data.get("password")
    if not password_plano:
        password_plano = f"Uagrm.{user_data['carnet']}"
    user_data["password"] = get_password_hash(password_plano)

    user = User(**user_data)
    await user.insert()
    return user


async def update_user(
    user: User,
    user_in: UserUpdate
) -> User:
    """Actualizar usuario existente"""
    update_data = user_in.model_dump(exclude_unset=True)
    
    if "password" in update_data:
        from core.security import get_password_hash
        update_data["password"] = get_password_hash(update_data["password"])

    if "email" in update_data and update_data["email"]:
        # ISSUE-A-VERIFICACION: si el correo realmente cambió, la verificación
        # anterior (si existía) ya no aplica al nuevo correo.
        if update_data["email"].strip().lower() != (user.email or "").strip().lower():
            update_data["email_verificado"] = False
            update_data["fecha_verificacion_email"] = None
    
    for field, value in update_data.items():
        setattr(user, field, value)
    
    await user.save()
    return user


async def delete_user(id: PydanticObjectId) -> User:
    """Eliminar usuario"""
    user = await User.get(id)
    if user:
        await user.delete()
    return user


async def assign_course_to_users(course_id: PydanticObjectId, encargados_ids: List[str]) -> None:
    """
    Asigna un curso a una lista de usuarios (Encargados de Curso/Coordinadores),
    y lo remueve de aquellos que ya no estén en la lista.
    Valida el límite máximo de 5 cursos.
    """
    # Buscar a todos los encargados que actualmente tienen el curso
    current_encargados = await User.find(
        User.cursos_asignados == course_id,
        Or(User.rol == UserRole.ENCARGADO_CURSO, User.rol == UserRole.COORDINADOR)
    ).to_list()
    
    current_ids = {str(u.id): u for u in current_encargados}
    new_ids = set(encargados_ids)
    
    # Usuarios a los que se les debe remover el curso
    to_remove_ids = set(current_ids.keys()) - new_ids
    for uid in to_remove_ids:
        u = current_ids[uid]
        if course_id in (u.cursos_asignados or []):
            u.cursos_asignados.remove(course_id)
            await u.save()
            
    # Usuarios a los que se les debe agregar el curso
    for uid in new_ids:
        if uid in current_ids:
            continue # ya lo tiene
            
        u = await User.get(PydanticObjectId(uid))
        if not u or u.rol not in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
            continue
            
        if not u.cursos_asignados:
            u.cursos_asignados = []
            
        if course_id not in u.cursos_asignados:
            if len(u.cursos_asignados) >= 5:
                raise ValueError(f"El usuario {u.username} ya tiene el máximo de 5 programas asignados.")
            u.cursos_asignados.append(course_id)
            await u.save()

