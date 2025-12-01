"""
Servicio de Descuentos
======================

Lógica de negocio para operaciones CRUD de descuentos.
"""

from typing import List, Optional
from beanie import PydanticObjectId
from models.discount import Discount
from schemas.discount import DiscountCreate, DiscountUpdate


async def get_discounts(skip: int = 0, limit: int = 100) -> List[Discount]:
    """Obtener lista de descuentos"""
    return await Discount.find_all().skip(skip).limit(limit).to_list()


async def get_discount(id: PydanticObjectId) -> Optional[Discount]:
    """Obtener descuento por ID"""
    return await Discount.get(id)


async def create_discount(discount_in: DiscountCreate) -> Discount:
    """Crear nuevo descuento"""
    discount = Discount(**discount_in.model_dump())
    await discount.insert()
    return discount


async def update_discount(
    discount: Discount,
    discount_in: DiscountUpdate
) -> Discount:
    """Actualizar descuento existente"""
    update_data = discount_in.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(discount, field, value)
    
    await discount.save()
    return discount


async def delete_discount(id: PydanticObjectId) -> Discount:
    """Eliminar descuento"""
    discount = await Discount.get(id)
    if discount:
        await discount.delete()
    return discount


async def get_discounts_by_student(student_id: PydanticObjectId) -> List[Discount]:
    """Obtener todos los descuentos aplicables a un estudiante"""
    return await Discount.find(
        Discount.lista_estudiantes == student_id,
        Discount.activo == True
    ).to_list()


async def add_student_to_discount(
    discount_id: PydanticObjectId,
    student_id: PydanticObjectId
) -> Discount:
    """Agregar un estudiante a un descuento"""
    discount = await Discount.get(discount_id)
    if discount and student_id not in discount.lista_estudiantes:
        discount.lista_estudiantes.append(student_id)
        await discount.save()
    return discount


async def remove_student_from_discount(
    discount_id: PydanticObjectId,
    student_id: PydanticObjectId
) -> Discount:
    """Remover un estudiante de un descuento"""
    discount = await Discount.get(discount_id)
    if discount and student_id in discount.lista_estudiantes:
        discount.lista_estudiantes.remove(student_id)
        await discount.save()
    return discount
