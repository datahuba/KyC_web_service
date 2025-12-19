"""
API de Configuración de Pagos
==============================

Endpoints para gestionar la configuración de pagos del sistema (QR y cuenta bancaria).

Permisos:
---------
- POST /payment-config/: ADMIN/SUPERADMIN
- GET /payment-config/: Cualquier usuario autenticado
- PUT /payment-config/: ADMIN/SUPERADMIN
- DELETE /payment-config/: ADMIN/SUPERADMIN

IMPORTANTE: Solo puede existir UNA configuración activa a la vez (singleton).
"""

from typing import Any, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, File
from models.user import User
from models.student import Student
from models.payment_config import PaymentConfig
from schemas.payment_config import PaymentConfigResponse
from services import payment_config_service
from api.dependencies import require_admin, get_current_user

router = APIRouter()


@router.post(
    "/",
    response_model=PaymentConfigResponse,
    status_code=201,
    summary="Crear Configuración de Pago",
    responses={
        201: {"description": "Configuración creada exitosamente con QR subido"},
        400: {"description": "Ya existe una configuración activa - usar PUT para actualizar"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def create_payment_config(
    *,
    file: UploadFile = File(..., description="Imagen del QR de pago (JPG, PNG, WEBP)"),
    numero_cuenta: str = Form(..., description="Número de cuenta bancaria"),
    banco: Optional[str] = Form(None, description="Nombre del banco"),
    titular: Optional[str] = Form(None, description="Titular de la cuenta"),
    tipo_cuenta: Optional[str] = Form(None, description="Tipo de cuenta (Ahorro, Corriente, etc.)"),
    notas: Optional[str] = Form(None, description="Notas adicionales"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear configuración de pagos del sistema
    
    **Requiere:** Admin o SuperAdmin
    
    **IMPORTANTE:** Solo puede existir UNA configuración activa.
    
    **Campos obligatorios:**
    - `file`: Imagen del QR (JPG, PNG, WEBP, máx 5MB)
    - `numero_cuenta`: Número de cuenta bancaria
    
    **El sistema automáticamente:**
    - ✅ Valida la imagen
    - ✅ Sube QR a Cloudinary
    - ✅ Guarda configuración en MongoDB
    
    Los estudiantes verán esta info al realizar pagos.
    """
    from core.cloudinary_utils import upload_image
    
    try:
        # Verificar que no exista ya una configuración
        existing = await payment_config_service.get_payment_config()
        if existing:
            raise HTTPException(
                status_code=400,
                detail="Ya existe una configuración de pagos activa. Use PUT para actualizar."
            )
        
        # Subir imagen del QR a Cloudinary
        folder = "payment_config"
        public_id = "qr_payment"
        qr_url = await upload_image(file, folder, public_id)
        
        # Crear configuración
        config = PaymentConfig(
            numero_cuenta=numero_cuenta,
            banco=banco,
            titular=titular,
            tipo_cuenta=tipo_cuenta,
            qr_url=qr_url,
            notas=notas,
            creado_por=current_user.username,
            actualizado_por=current_user.username,
            is_active=True
        )
        
        await config.insert()
        return config
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al crear configuración: {str(e)}")


@router.get(
    "/",
    response_model=PaymentConfigResponse,
    summary="Ver Configuración de Pago",
    responses={
        200: {"description": "Configuración actual con QR y datos bancarios"},
        404: {"description": "No existe configuración"}
    }
)
async def get_payment_config(
    *,
    current_user: User | Student = Depends(get_current_user)
) -> Any:
    """
    Ver configuración de pago actual
    
    **Requiere:** Usuario autenticado
    
    **Para estudiantes:** Ver QR, cuenta bancaria y datos de pago
    """
    config = await payment_config_service.get_payment_config()
    
    if not config:
        raise HTTPException(
            status_code=404,
            detail="No existe una configuración de pagos. Contacte al administrador."
        )
    
    return config


@router.put(
    "/",
    response_model=PaymentConfigResponse,
    summary="Actualizar Configuración de Pago",
    responses={
        200: {"description": "Configuración actualizada exitosamente"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "No existe configuración - usar POST"}
    }
)
async def update_payment_config(
    *,
    file: Optional[UploadFile] = File(None, description="Nueva imagen del QR (opcional)"),
    numero_cuenta: Optional[str] = Form(None, description="Número de cuenta bancaria"),
    banco: Optional[str] = Form(None, description="Nombre del banco"),
    titular: Optional[str] = Form(None, description="Titular de la cuenta"),
    tipo_cuenta: Optional[str] = Form(None, description="Tipo de cuenta"),
    notas: Optional[str] = Form(None, description="Notas adicionales"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar configuración de pagos
    
    **Requiere:** Admin o SuperAdmin
    
    **Todos los campos son opcionales.**  
    Solo se actualizan los proporcionados.
    
    **Casos comunes:**
    - Cambiar QR: Subir nuevo `file`
    - Cambiar cuenta: Modificar `numero_cuenta`
    """
    from core.cloudinary_utils import upload_image
    
    try:
        # Obtener configuración actual
        config = await payment_config_service.get_payment_config()
        if not config:
            raise HTTPException(
                status_code=404,
                detail="No existe una configuración para actualizar. Use POST para crear."
            )
        
        # Si se proporciona nueva imagen, subirla a Cloudinary
        if file:
            folder = "payment_config"
            public_id = "qr_payment"
            qr_url = await upload_image(file, folder, public_id)
            config.qr_url = qr_url
        
        # Actualizar campos si se proporcionaron
        if numero_cuenta is not None:
            config.numero_cuenta = numero_cuenta
        if banco is not None:
            config.banco = banco
        if titular is not None:
            config.titular = titular
        if tipo_cuenta is not None:
            config.tipo_cuenta = tipo_cuenta
        if notas is not None:
            config.notas = notas
        
        # Actualizar auditoría
        config.actualizado_por = current_user.username
        await config.save()
        
        return config
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al actualizar configuración: {str(e)}")


@router.delete(
    "/",
    response_model=PaymentConfigResponse,
    summary="Eliminar Configuración de Pago",
    responses={
        200: {"description": "Configuración marcada como inactiva"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "No existe configuración para eliminar"}
    }
)
async def delete_payment_config(
    *,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Eliminar configuración de pagos
    
    **Requiere:** Admin o SuperAdmin
    
    **IMPORTANTE:** NO elimina permanentemente, solo desactiva.
    
    **⚠️ ADVERTENCIA:** Los estudiantes no podrán realizar pagos sin configuración activa.
    """
    config = await payment_config_service.delete_payment_config()
    
    if not config:
        raise HTTPException(
            status_code=404,
            detail="No existe una configuración de pagos para eliminar"
        )
    
    return config
