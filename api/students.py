from typing import List, Any, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, Query
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdateSelf, StudentUpdateAdmin, ChangePassword
from services import student_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math

@router.get(
    "/",
    response_model=PaginatedResponse[StudentResponse],
    summary="Listar Estudiantes",
    responses={
        200: {"description": "Lista de estudiantes con paginación y filtros"},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def read_students(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Buscar por nombre, email, carnet o registro"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    estado_titulo: Optional[str] = Query(None, description="Filtrar por estado del título (pendiente, verificado, etc)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso inscrito"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Listar estudiantes con paginación y filtros avanzados
    
    **Requiere:** Admin o SuperAdmin
    
    **Filtros disponibles:**
    - `q`: Búsqueda por nombre, email, carnet o registro
    - `activo`: true/false - Filtrar por estado
    - `estado_titulo`: pendiente, verificado, rechazado, sin_titulo
    - `curso_id`: Ver estudiantes de un curso específico
    
    **Paginación:**
    - `page`: Página actual (default: 1)
    - `per_page`: Elementos por página (default: 10, max: 100)
    """
    students, total_count = await student_service.get_students(
        page=page,
        per_page=per_page,
        q=q,
        activo=activo,
        estado_titulo=estado_titulo,
        curso_id=curso_id
    )
    
    # Calcular metadatos
    total_pages = math.ceil(total_count / per_page)
    has_next = page < total_pages
    has_prev = page > 1
    
    return {
        "data": students,
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
    response_model=StudentResponse,
    status_code=201,
    summary="Crear Estudiante",
    responses={
        201: {"description": "Estudiante creado exitosamente. Password inicial = carnet"},
        400: {"description": "Error de validación: registro duplicado, etc."},
        403: {"description": "Sin permisos - Solo Admin"}
    }
)
async def create_student(
    *,
    student_in: StudentCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo estudiante
    
    **Requiere:** Admin o SuperAdmin
    
    **Campos mínimos:**
    - registro (username)
    - carnet (CI)
    - nombre
    - email
    
    **Automáticamente:**
    - Password inicial = carnet (el estudiante debe cambiarlo después)
    - Activo = true
    - Lista de cursos = []
    """
    student = await student_service.create_student(student_in=student_in)
    return student

@router.get(
    "/{id}",
    response_model=StudentResponse,
    summary="Ver Estudiante",
    responses={
        200: {"description": "Datos del estudiante"},
        403: {"description": "Sin permisos - Admin o el mismo estudiante"},
        404: {"description": "Estudiante no encontrado"}
    }
)
async def read_student(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Ver perfil de un estudiante
    
    **Permisos:**
    - **Admin:** Puede ver cualquier estudiante
    - **Estudiante:** Solo puede ver su propio perfil
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Si es estudiante, solo puede ver su propio perfil
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para ver este estudiante"
        )
    
    return student

@router.put(
    "/me",
    response_model=StudentResponse,
    summary="Actualizar Mi Perfil",
    responses={
        200: {"description": "Perfil actualizado exitosamente"},
        403: {"description": "Solo estudiantes"}
    }
)
async def update_student_self(
    *,
    student_in: StudentUpdateSelf,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Actualizar perfil del estudiante autenticado
    
    **Requiere:** Estudiante autenticado
    
    **Puede actualizar:**
    - celular
    - domicilio
    
    **NO puede cambiar:**
    - nombre, email, registro, password, tipo de estudiante, etc.
    
    **Para cambiar password:** Usar `POST /students/me/change-password`
    """
    # Verificar que sea un estudiante
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Este endpoint es solo para estudiantes. Los admins deben usar PUT /students/{id}"
        )
    
    # Actualizar el perfil del estudiante autenticado
    student = await student_service.update_student(student=current_user, student_in=student_in)
    return student


@router.post(
    "/me/change-password",
    response_model=StudentResponse,
    summary="Cambiar Mi Contraseña",
    responses={
        200: {"description": "Contraseña cambiada exitosamente"},
        400: {"description": "Contraseña actual incorrecta o validación fallida"},
        403: {"description": "Solo estudiantes"}
    }
)
async def change_password(
    *,
    password_data: ChangePassword,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Cambiar contraseña del estudiante autenticado (seguro)
    
    **Requiere:** Estudiante autenticado
    
    **Proceso seguro:**
    1. Verifica la contraseña actual
    2. Requiere confirmar la nueva contraseña (2 veces)
    3. Mínimo 5 caracteres
    4. Se hashea automáticamente
    """
    from core.security import verify_password, get_password_hash
     
    # Verificar que la contraseña actual sea correcta
    if not verify_password(password_data.current_password, current_user.password):
        raise HTTPException(
            status_code=400,
            detail="La contraseña actual es incorrecta"
        )
    
    # Actualizar la contraseña (ya viene validada que new_password == confirm_password)
    current_user.password = get_password_hash(password_data.new_password)
    await current_user.save()
    
    return current_user


@router.put(
    "/{id}",
    response_model=StudentResponse,
    summary="Actualizar Estudiante (Admin)",
    responses={
        200: {"description": "Estudiante actualizado exitosamente"},
        403: {"description": "Sin permisos - Solo Admin"},
        404: {"description": "Estudiante no encontrado"}
    }
)
async def update_student_admin(
    *,
    id: PydanticObjectId,
    student_in: StudentUpdateAdmin,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar cualquier estudiante
    
    **Requiere:** Admin o SuperAdmin
    
    **Los administradores pueden actualizar:**
    - Datos personales (nombre, email, carnet, etc.)
    - Tipo de estudiante (interno/externo)
    - Estado (activo/inactivo)
    - Password (para resetear)
    - Cursos inscritos
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    student = await student_service.update_student(student=student, student_in=student_in)
    return student


@router.delete(
    "/{id}",
    response_model=StudentResponse,
    summary="Eliminar Estudiante",
    responses={
        200: {"description": "Estudiante eliminado exitosamente"},
        403: {"description": "Sin permisos - Solo SuperAdmin"},
        404: {"description": "Estudiante no encontrado"}
    }
)
async def delete_student(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Eliminar estudiante
    
    **Requiere:** SOLO SuperAdmin
    
    **Nota:** Los Admin normales NO pueden eliminar estudiantes.
    """
    # Solo SUPERADMIN puede eliminar
    from models.enums import UserRole
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo SUPERADMIN puede eliminar estudiantes"
        )
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    student = await student_service.delete_student(id=id)
    return student


# ============================================================================
# ENDPOINTS DE SUBIDA DE ARCHIVOS
# ============================================================================

@router.post(
    "/{id}/upload/photo",
    response_model=StudentResponse,
    summary="Subir Foto de Perfil",
    responses={
        200: {"description": "Foto subida exitosamente"},
        400: {"description": "Formato no permitido"},
        403: {"description": "Sin permisos - Admin o el mismo estudiante"},
        404: {"description": "Estudiante no encontrado"}
    }
)
async def upload_student_photo(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir foto de perfil del estudiante
    
    **Permisos:**
    - **Admin:** Puede subir foto a cualquier estudiante
    - **Estudiante:** Solo puede subir su propia foto
    
    **Formatos permitidos:** JPG, PNG, WEBP  
    **Tamaño máximo:** 5MB
    """
    from core.cloudinary_utils import upload_image
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Verificar permisos
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para subir archivos a este estudiante"
        )
    
    # Subir imagen a Cloudinary
    folder = f"students/{id}/photo"
    public_id = f"photo_{id}"
    foto_url = await upload_image(file, folder, public_id)
    
    # Actualizar URL en el estudiante
    student.foto_url = foto_url
    await student.save()
    
    return student

