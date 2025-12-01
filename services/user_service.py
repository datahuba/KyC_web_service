"""
Servicio de Usuarios
====================

Lógica de negocio para operaciones CRUD de usuarios del sistema.
"""

from typing import List, Optional
from beanie import PydanticObjectId
from models.user import User
from schemas.user import UserCreate, UserUpdate


async def get_users(skip: int = 0, limit: int = 100) -> List[User]:
    """Obtener lista de usuarios"""
    return await User.find_all().skip(skip).limit(limit).to_list()


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
