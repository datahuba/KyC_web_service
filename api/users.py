from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends, Query
from models.user import User
from schemas.user import UserCreate, UserResponse, UserUpdate
from services import user_service
from beanie import PydanticObjectId

# Importamos las nuevas dependencias creadas en el ISSUE L
from api.dependencies import require_superadmin, require_cpd

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math
from typing import Optional

@router.get(
    "/teachers",
    response_model=List[UserResponse],
    summary="Listar Docentes Activos"
)
async def get_teachers(
    current_user: User = Depends(require_cpd)  # <-- CORRECCIÓN: El CPD ya tiene permiso
) -> Any:
    """
    Obtiene solo los usuarios ACTIVOS que son docentes
    
    **Requiere:** CPD, Admin o SuperAdmin
    """
    users = await user_service.get_active_users()
    return users


@router.get(
    "/",
    response_model=PaginatedResponse[UserResponse],
    summary="Listar Usuarios Admin"
)
async def read_users(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    current_user: User = Depends(require_superadmin) # <-- CORRECCIÓN: Solo SuperAdmin
) -> Any:
    """
    Listar usuarios administradores y personal de la jerarquía
    
    **Requiere:** SOLO SuperAdmin
    """
    users, total_count = await user_service.get_users(page=page, per_page=per_page)
    
    # Calcular metadatos
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
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
    summary="Crear Usuario Admin"
)
async def create_user(
    *,
    user_in: UserCreate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Crear nuevo usuario en la jerarquía
    
    **Requiere:** SOLO SuperAdmin
    """
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
    summary="Ver Usuario Admin"
)
async def read_user(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    return user

@router.put(
    "/{id}",
    response_model=UserResponse,
    summary="Actualizar Usuario Admin"
)
async def update_user(
    *,
    id: PydanticObjectId,
    user_in: UserUpdate,
    current_user: User = Depends(require_superadmin)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user = await user_service.update_user(user=user, user_in=user_in)
    return user

@router.delete(
    "/{id}",
    response_model=UserResponse,
    summary="Eliminar Usuario Admin"
)
async def delete_user(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    user = await user_service.delete_user(id=id)
    return user
