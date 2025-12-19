from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends
from models.user import User
from schemas.user import UserCreate, UserResponse, UserUpdate
from services import user_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from models.enums import UserRole
from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[UserResponse],
    summary="Listar Usuarios Admin",
    responses={
        200: {"description": "Lista de usuarios admin con paginación"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def read_users(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Listar usuarios administradores
    
    **Requiere:** Admin o SuperAdmin
    
    **Retorna:** Lista de usuarios del sistema (Admin/SuperAdmin)
    """
    users, total_count = await user_service.get_users(page=page, per_page=per_page)
    
    # Calcular metadatos
    total_pages = math.ceil(total_count / per_page)
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": users,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=has_next,
            hasPrevPage=has_prev
        )
    }

@router.post(
    "/",
    response_model=UserResponse,
    status_code=201,
    summary="Crear Usuario Admin",
    responses={
        201: {"description": "Usuario creado exitosamente"},
        400: {"description": "Username o email ya existe"},
        403: {"description": "Sin permisos - Solo SuperAdmin"}
    }
)
async def create_user(
    *,
    user_in: UserCreate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Crear nuevo usuario administrador
    
    **Requiere:** SOLO SuperAdmin
    
    **Roles disponibles:** Admin, SuperAdmin
    """
    # Verificar que username y email sean únicos
    existing_user = await user_service.get_user_by_username(user_in.username)
    if existing_user:
        raise HTTPException(status_code=400, detail="Username ya existe")
    
    existing_email = await user_service.get_user_by_email(user_in.email)
    if existing_email:
        raise HTTPException(status_code=400, detail="Email ya existe")
    
    user = await user_service.create_user(user_in=user_in)
    return user

@router.get(
    "/{id}",
    response_model=UserResponse,
    summary="Ver Usuario Admin",
    responses={
        200: {"description": "Detalles del usuario"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Usuario no encontrado"}
    }
)
async def read_user(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Ver detalles de un usuario administrador
    
    **Requiere:** Admin o SuperAdmin
    """
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user

@router.put(
    "/{id}",
    response_model=UserResponse,
    summary="Actualizar Usuario Admin",
    responses={
        200: {"description": "Usuario actualizado exitosamente"},
        403: {"description": "Sin permisos - Solo SuperAdmin"},
        404: {"description": "Usuario no encontrado"}
    }
)
async def update_user(
    *,
    id: PydanticObjectId,
    user_in: UserUpdate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Actualizar usuario administrador
    
    **Requiere:** SOLO SuperAdmin
    """
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user = await user_service.update_user(user=user, user_in=user_in)
    return user

@router.delete(
    "/{id}",
    response_model=UserResponse,
    summary="Eliminar Usuario Admin",
    responses={
        200: {"description": "Usuario eliminado exitosamente"},
        403: {"description": "Sin permisos - Solo SuperAdmin"},
        404: {"description": "Usuario no encontrado"}
    }
)
async def delete_user(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar usuario administrador
    
    **Requiere:** SOLO SuperAdmin
    """
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user = await user_service.delete_user(id=id)
    return user
