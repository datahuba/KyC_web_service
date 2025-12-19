from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends
from models.discount import Discount
from models.user import User
from schemas.discount import DiscountCreate, DiscountResponse, DiscountUpdate
from services import discount_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[DiscountResponse],
    summary="Listar Descuentos",
    responses={
        200: {"description": "Lista de descuentos con paginación"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def read_discounts(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Listar descuentos con paginación
    
    **Requiere:** Admin o SuperAdmin
    
    **Retorna:** Descuentos disponibles para asignar a estudiantes
    """
    discounts, total_count = await discount_service.get_discounts(page=page, per_page=per_page)
    
    # Calcular metadatos
    total_pages = math.ceil(total_count / per_page)
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": discounts,
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
    response_model=DiscountResponse,
    status_code=201,
    summary="Crear Descuento",
    responses={
        201: {"description": "Descuento creado exitosamente"},
        400: {"description": "Error de validación"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def create_discount(
    *,
    discount_in: DiscountCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo descuento
    
    **Requiere:** Admin o SuperAdmin
    
    **Campos:**
    - `nombre`: Nombre del descuento  
    - `porcentaje`: Porcentaje (0-100)
    """
    discount = await discount_service.create_discount(discount_in=discount_in)
    return discount

@router.get(
    "/{id}",
    response_model=DiscountResponse,
    summary="Ver Descuento",
    responses={
        200: {"description": "Detalles del descuento"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Descuento no encontrado"}
    }
)
async def read_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Ver detalles de un descuento
    
    **Requiere:** Admin o SuperAdmin
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount

@router.put(
    "/{id}",
    response_model=DiscountResponse,
    summary="Actualizar Descuento",
    responses={
        200: {"description": "Descuento actualizado exitosamente"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Descuento no encontrado"}
    }
)
async def update_discount(
    *,
    id: PydanticObjectId,
    discount_in: DiscountUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar descuento existente
    
    **Requiere:** Admin o SuperAdmin
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    discount = await discount_service.update_discount(discount=discount, discount_in=discount_in)
    return discount

@router.delete(
    "/{id}",
    response_model=DiscountResponse,
    summary="Eliminar Descuento",
    responses={
        200: {"description": "Descuento eliminado exitosamente"},
        403: {"description": "Sin permisos - Solo SuperAdmin"},
        404: {"description": "Descuento no encontrado"}
    }
)
async def delete_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar descuento
    
    **Requiere:** SOLO SuperAdmin
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    discount = await discount_service.delete_discount(id=id)
    return discount

@router.post("/{id}/students/{student_id}", response_model=DiscountResponse)
async def add_student_to_discount(
    *,
    id: PydanticObjectId,
    student_id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Agregar un estudiante a un descuento.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discount = await discount_service.add_student_to_discount(
        discount_id=id,
        student_id=student_id
    )
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount

@router.delete("/{id}/students/{student_id}", response_model=DiscountResponse)
async def remove_student_from_discount(
    *,
    id: PydanticObjectId,
    student_id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Remover un estudiante de un descuento.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discount = await discount_service.remove_student_from_discount(
        discount_id=id,
        student_id=student_id
    )
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount
