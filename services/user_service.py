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
    """Obtener lista de usuarios con paginación"""
    query = User.find_all()
    total_count = await query.count()
    skip = (page - 1) * per_page
    users = await query.sort("-created_at").skip(skip).limit(per_page).to_list()
    return users, total_count


async def get_active_users() -> List[User]:
    """Obtener todos los usuarios activos (potenciales docentes)"""
    return await User.find(User.activo == True).sort("username").to_list()


async def get_user(id: PydanticObjectId) -> Optional[User]:
    """Obtener usuario por ID"""
    return await User.get(id)


async def get_user_by_username(username: str) -> Optional[User]:
    """Obtener usuario por username"""
    return await User.find_one(User.username == username)


async def get_user_by_email(email: str) -> Optional[User]:
    """Obtener usuario por email"""
    return await User.find_one(User.email == email)


async def create_user(user_in: UserCreate) -> User:
    """
    Crear nuevo usuario
    
    La contraseña se hashea automáticamente antes de guardar.
    """
    from core.security import get_password_hash
    
    user_data = user_in.model_dump()
    user_data["password"] = get_password_hash(user_data["password"])
    
    user = User(**user_data)
    await user.insert()
    return user


async def update_user(
    user: User,
    user_in: UserUpdate
) -> User:
    """Actualizar usuario existente"""
    update_data = user_in.model_dump(exclude_unset=True)
    
    # Si se actualiza la contraseña, hashearla
    if "password" in update_data:
        from core.security import get_password_hash
        update_data["password"] = get_password_hash(update_data["password"])
    
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
