from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends
from models.discount import Discount
from models.user import User
from schemas.discount import DiscountCreate, DiscountResponse, DiscountUpdate
from services import discount_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, require_superadmin

router = APIRouter()

@router.get("/", response_model=List[DiscountResponse])
async def read_discounts(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Recuperar descuentos.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discounts = await discount_service.get_discounts(skip=skip, limit=limit)
    return discounts

@router.post("/", response_model=DiscountResponse)
async def create_discount(
    *,
    discount_in: DiscountCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo descuento.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discount = await discount_service.create_discount(discount_in=discount_in)
    return discount

@router.get("/{id}", response_model=DiscountResponse)
async def read_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Obtener descuento por ID.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount

@router.put("/{id}", response_model=DiscountResponse)
async def update_discount(
    *,
    id: PydanticObjectId,
    discount_in: DiscountUpdate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar descuento.
    
    Requiere: ADMIN o SUPERADMIN
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    discount = await discount_service.update_discount(discount=discount, discount_in=discount_in)
    return discount

@router.delete("/{id}", response_model=DiscountResponse)
async def delete_discount(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin)
) -> Any:
    """
    Eliminar descuento.
    
    Requiere: SUPERADMIN
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
