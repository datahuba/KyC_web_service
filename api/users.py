from typing import List, Any, Optional
from fastapi import APIRouter, HTTPException, Depends, Query, status, UploadFile, File, Form
from models.user import User
from schemas.user import UserCreate, UserResponse, UserUpdate
from services import user_service
from beanie import PydanticObjectId
from models.course import Course

# Importamos las nuevas dependencias creadas en el ISSUE L
from api.dependencies import require_superadmin, require_cpd, get_current_user, require_encargado_curso
from models.enums import UserRole

# Para el cambio de contraseña (Bug 5)
from core.security import verify_password, get_password_hash
from pydantic import BaseModel, Field

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math
from core.cloudinary_utils import upload_pdf


class UserChangePassword(BaseModel):
    current_password: str = Field(..., description="Contraseña actual")
    new_password: str = Field(..., description="Nueva contraseña")
    confirm_password: str = Field(..., description="Confirmación de nueva contraseña")


@router.get(
    "/teachers",
    response_model=List[UserResponse],
    summary="Listar Docentes Activos"
)
async def get_teachers(
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    """
    Obtiene solo los usuarios ACTIVOS que son docentes
    
    **Requiere:** CPD, Admin, SuperAdmin, o Encargado/Coordinador
    """
    users = await user_service.get_active_users()
    
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if not current_user.cursos_asignados:
            return []
        courses = await Course.find({"_id": {"$in": current_user.cursos_asignados}}).to_list()
        allowed_teacher_ids = set()
        for course in courses:
            for modulo in course.modulos:
                if modulo.docente_id:
                    allowed_teacher_ids.add(modulo.docente_id)
        users = [u for u in users if u.id in allowed_teacher_ids]
        
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

    # NOTA: el email NO se valida como único a propósito. Una misma persona puede
    # tener varios perfiles funcionales (ej. Cobranza + Encargado del mismo
    # programa) con el mismo correo de contacto; cada perfil se distingue e
    # inicia sesión por su `username` único. (Antes se rechazaba con "Email ya
    # existe" — se removió para permitir perfiles por función que comparten correo.)

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

    # BUG 7 FIX: Protección contra Auto-desactivación y Auto-degradación de permisos
    if current_user.id == user.id:
        # 1. El superadmin no puede marcar su cuenta como inactiva
        if user_in.activo is not None and user_in.activo is False:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Operación prohibida: No puedes desactivar tu propia cuenta administrativa."
            )
        
        # 2. El superadmin no puede rebajarse de rol a sí mismo (ej. de superadmin a docente)
        if user_in.role is not None and user_in.role != user.role:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, 
                detail="Operación prohibida: No puedes alterar tu propio nivel de privilegios."
            )

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
        
    # BUG 7 FIX: Protección extrema contra el borrado físico de la propia cuenta
    if current_user.id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Operación prohibida: Un superadministrador no puede eliminar su propia cuenta en sesión."
        )
        
    user = await user_service.delete_user(id=id)
    return user


@router.post("/{id}/cv/upload", response_model=UserResponse)
async def upload_teacher_cv(
    id: PydanticObjectId,
    file: UploadFile = File(...),
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if not current_user.cursos_asignados:
            raise HTTPException(status_code=403, detail="No tienes cursos asignados para gestionar docentes")
        courses = await Course.find({"_id": {"$in": current_user.cursos_asignados}}).to_list()
        allowed_teacher_ids = set()
        for course in courses:
            for modulo in course.modulos:
                if modulo.docente_id:
                    allowed_teacher_ids.add(modulo.docente_id)
        if id not in allowed_teacher_ids:
            raise HTTPException(status_code=403, detail="Este docente no pertenece a tus cursos asignados")
    
    cv_url = await upload_pdf(
        file=file,
        folder="users/cv",
        public_id=f"cv_{user.id}"
    )
    
    user.cv_url = cv_url
    user.cv_estado = "pendiente"
    user.cv_motivo_rechazo = None
    await user.save()
    
    return user


@router.put("/{id}/cv/verificar", response_model=UserResponse)
async def verificar_cv_docente(
    id: PydanticObjectId,
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if not current_user.cursos_asignados:
            raise HTTPException(status_code=403, detail="No tienes cursos asignados para gestionar docentes")
        courses = await Course.find({"_id": {"$in": current_user.cursos_asignados}}).to_list()
        allowed_teacher_ids = set()
        for course in courses:
            for modulo in course.modulos:
                if modulo.docente_id:
                    allowed_teacher_ids.add(modulo.docente_id)
        if id not in allowed_teacher_ids:
            raise HTTPException(status_code=403, detail="Este docente no pertenece a tus cursos asignados")
        
    user.cv_estado = "verificado"
    user.cv_motivo_rechazo = None
        
    await user.save()
    return user

@router.put("/{id}/cv/rechazar", response_model=UserResponse)
async def rechazar_cv_docente(
    id: PydanticObjectId,
    motivo: str = Form(...),
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    user = await user_service.get_user(id=id)
    if not user:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
    if current_user.rol in [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]:
        if not current_user.cursos_asignados:
            raise HTTPException(status_code=403, detail="No tienes cursos asignados para gestionar docentes")
        courses = await Course.find({"_id": {"$in": current_user.cursos_asignados}}).to_list()
        allowed_teacher_ids = set()
        for course in courses:
            for modulo in course.modulos:
                if modulo.docente_id:
                    allowed_teacher_ids.add(modulo.docente_id)
        if id not in allowed_teacher_ids:
            raise HTTPException(status_code=403, detail="Este docente no pertenece a tus cursos asignados")

    user.cv_estado = "rechazado"
    user.cv_motivo_rechazo = motivo
        
    await user.save()
    return user


@router.post(
    "/me/change-password",
    summary="Cambiar Mi Contraseña (Personal/Docentes)"
)
async def change_my_password(
    *,
    data: UserChangePassword,
    current_user: User = Depends(get_current_user)
) -> Any:
    """
    Cambiar la contraseña del usuario administrativo actual (Docentes, CPD, Cobranzas, Admin, MAE)
    """
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Ruta solo para personal administrativo")
        
    # Verificar contraseña actual
    if not verify_password(data.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
        
    if data.new_password != data.confirm_password:
        raise HTTPException(status_code=400, detail="Las nuevas contraseñas no coinciden")
        
    if len(data.new_password) < 5:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 5 caracteres")

    if data.current_password == data.new_password:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente a la actual")
        
    current_user.password = get_password_hash(data.new_password)
    await current_user.save()
    
    return {"message": "Contraseña actualizada correctamente"}
