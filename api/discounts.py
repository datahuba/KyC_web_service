from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends
from models.discount import Discount
from models.user import User
from schemas.discount import DiscountCreate, DiscountResponse, DiscountUpdate
from services import discount_service
from beanie import PydanticObjectId

# Nuevas dependencias de seguridad del ISSUE L
from api.dependencies import require_superadmin, require_cobranza, require_staff

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[DiscountResponse],
    summary="Listar Descuentos"
)
async def read_discounts(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    current_user: User = Depends(require_staff) # <-- TODOS LOS ADMINISTRATIVOS PUEDEN LEER
) -> Any:
    """Listar descuentos con paginación"""
    discounts, total_count = await discount_service.get_discounts(page=page, per_page=per_page)
    
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
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
    summary="Crear Descuento"
)
async def create_discount(
    *,
    discount_in: DiscountCreate,
    current_user: User = Depends(require_cobranza) # <-- COBRANZA CREA DESCUENTOS
) -> Any:
    """Crear nuevo descuento"""
    discount = await discount_service.create_discount(discount_in=discount_in)
    return discount

@router.get(
    "/{id}",
    response_model=DiscountResponse,
    summary="Ver Descuento"
)
async def read_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_staff) # <-- LECTURA GLOBAL
) -> Any:
    """Ver detalles de un descuento"""
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount

@router.put(
    "/{id}",
    response_model=DiscountResponse,
    summary="Actualizar Descuento"
)
async def update_discount(
    *,
    id: PydanticObjectId,
    discount_in: DiscountUpdate,
    current_user: User = Depends(require_cobranza) # <-- COBRANZA ACTUALIZA
) -> Any:
    """Actualizar descuento existente"""
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    discount = await discount_service.update_discount(discount=discount, discount_in=discount_in)
    return discount

@router.delete(
    "/{id}",
    response_model=DiscountResponse,
    summary="Eliminar Descuento"
)
async def delete_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin) # <-- SOLO SUPERADMIN BORRA
) -> Any:
    """Eliminar descuento"""
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
    current_user: User = Depends(require_cobranza) # <-- COBRANZA ASIGNA BECAS
) -> Any:
    """Agregar un estudiante a un descuento"""
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
    current_user: User = Depends(require_cobranza) # <-- COBRANZA RETIRA BECAS
) -> Any:
    """Remover un estudiante de un descuento"""
    discount = await discount_service.remove_student_from_discount(
        discount_id=id,
        student_id=student_id
    )
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount
