"""
Servicio de Descuentos
======================

Lógica de negocio para operaciones CRUD de descuentos.
"""

from typing import List, Optional
from beanie import PydanticObjectId
from models.discount import Discount
from schemas.discount import DiscountCreate, DiscountUpdate


async def get_discounts(page: int = 1, per_page: int = 10) -> tuple[List[Discount], int]:
    """Obtener lista de descuentos con paginación"""
    query = Discount.find_all()
    total_count = await query.count()
    skip = (page - 1) * per_page
    discounts = await query.sort("-created_at").skip(skip).limit(per_page).to_list()
    return discounts, total_count


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
    """
    Eliminar descuento.

    AUDITORÍA (MEDIO #8): antes no limpiaba ninguna referencia -- si el
    descuento estaba en uso, Enrollment.descuento_curso_id/descuento_estudiante_id
    y Course.descuento_id quedaban apuntando a un ObjectId huérfano tras el
    delete. No se puede reconstruir el precio real ya cobrado (los totales de
    Enrollment ya están congelados como snapshot), así que solo se limpia la
    REFERENCIA para que dejen de apuntar a un documento inexistente; los
    montos financieros históricos no se tocan.
    """
    from models.enrollment import Enrollment
    from models.course import Course

    discount = await Discount.get(id)
    if not discount:
        return discount

    await Enrollment.find(Enrollment.descuento_curso_id == id).update(
        {"$set": {"descuento_curso_id": None}}
    )
    await Enrollment.find(Enrollment.descuento_estudiante_id == id).update(
        {"$set": {"descuento_estudiante_id": None}}
    )
    await Course.find(Course.descuento_id == id).update(
        {"$set": {"descuento_id": None}}
    )

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
