from datetime import datetime
from core.timezone_utils import utcnow_naive
from typing import List, Any
from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from models.discount import Discount
from models.user import User
from schemas.discount import DiscountCreate, DiscountResponse, DiscountUpdate
from services import discount_service
from beanie import PydanticObjectId
from core.cloudinary_utils import upload_image, upload_pdf

# Nuevas dependencias de seguridad del ISSUE L
# ISSUE-P-DESCUENTO-ROL: la gestión de descuentos (crear/editar/asignar) pasa de
# Cobranza a Administrativo (require_admin).
# ISSUE-P-DESCUENTO-CPD (2026-07-08, reunión de postgrado contaduría): se
# revierte a CPD como único responsable de crear/editar/asignar descuentos
# ("no hay un usuario inferior ni superior que lo haga, solamente CPD").
# require_cpd ya incluye CPD/ADMIN/SUPERADMIN por jerarquía, así que Admin y
# Superadmin conservan acceso; lo que cambia es que CPD (antes sin acceso de
# escritura desde ISSUE-P-DESCUENTO-ROL) ahora sí puede gestionar descuentos.
from api.dependencies import require_superadmin, require_cpd, require_staff

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
    current_user: User = Depends(require_cpd) # <-- CPD CREA DESCUENTOS (ISSUE-P-DESCUENTO-CPD)
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
    current_user: User = Depends(require_cpd) # <-- CPD ACTUALIZA (ISSUE-P-DESCUENTO-CPD)
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
    current_user: User = Depends(require_cpd) # <-- CPD ASIGNA BECAS (ISSUE-P-DESCUENTO-CPD)
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
    current_user: User = Depends(require_cpd) # <-- CPD RETIRA BECAS (ISSUE-P-DESCUENTO-CPD)
) -> Any:
    """Remover un estudiante de un descuento"""
    discount = await discount_service.remove_student_from_discount(
        discount_id=id,
        student_id=student_id
    )
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")
    return discount


@router.post(
    "/{id}/resolucion",
    response_model=DiscountResponse,
    summary="Subir Documento de Resolución del Descuento"
)
async def subir_resolucion_descuento(
    *,
    id: PydanticObjectId,
    file: UploadFile = File(...),
    current_user: User = Depends(require_cpd)  # <-- CPD, ADMIN, SUPERADMIN (ISSUE-P-DESCUENTO-RESOLUCION)
) -> Any:
    """
    Sube (o reemplaza) el documento de resolución que respalda este descuento
    (ISSUE-P-DESCUENTO-RESOLUCION, 2026-07-08). No bloqueante: el descuento
    puede crearse primero y el respaldo subirse en cualquier momento
    posterior, mismo patrón que /enrollments/{id}/beca-respaldo.
    """
    discount = await discount_service.get_discount(id=id)
    if not discount:
        raise HTTPException(status_code=404, detail="Descuento no encontrado")

    try:
        folder = f"discounts/{id}/resolucion"
        public_id = "resolucion"

        image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
        if file.content_type in image_types:
            url = await upload_image(file, folder, public_id)
        elif file.content_type == "application/pdf":
            url = await upload_pdf(file, folder, public_id)
        else:
            raise HTTPException(400, f"Formato no permitido: {file.content_type}")

        discount.resolucion_url = url
        discount.updated_at = utcnow_naive()
        await discount.save()
        return discount
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error: {str(e)}")
