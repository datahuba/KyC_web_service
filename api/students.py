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

@router.get("/", response_model=PaginatedResponse[StudentResponse])
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
    Recuperar estudiantes con filtros y paginación.
    
    Requiere: ADMIN o SUPERADMIN
    
    Filtros:
    - q: Búsqueda de texto
    - activo: true/false
    - estado_titulo: pendiente, verificado, rechazado, sin_titulo
    - curso_id: ID de un curso
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

@router.post("/", response_model=StudentResponse)
async def create_student(
    *,
    student_in: StudentCreate,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Crear nuevo estudiante.
    
    Requiere: ADMIN o SUPERADMIN
    """
    student = await student_service.create_student(student_in=student_in)
    return student

@router.get("/{id}", response_model=StudentResponse)
async def read_student(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener estudiante por ID.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden ver cualquier estudiante
    - STUDENT: Solo puede ver su propio perfil
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

@router.put("/me", response_model=StudentResponse)
async def update_student_self(
    *,
    student_in: StudentUpdateSelf,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Actualizar el perfil del estudiante autenticado.
    
    Requiere: Autenticación como STUDENT
    
    El estudiante solo puede actualizar:
    - celular (número de teléfono)
    - domicilio (dirección)
    
    Para subir archivos (CV, foto, carnet, etc.), usar los endpoints:
    - POST /students/me/upload/photo
    - POST /students/me/upload/cv
    - POST /students/me/upload/carnet
    - POST /students/me/upload/afiliacion
    
    NO puede cambiar: nombre, email, registro, activo, tipo de estudiante, password, etc.
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


@router.post("/me/change-password", response_model=StudentResponse)
async def change_password(
    *,
    password_data: ChangePassword,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Cambiar contraseña del estudiante autenticado (seguro).
    
    Requiere: Autenticación como STUDENT
    
    Seguridad:
    - Verifica la contraseña actual
    - Requiere confirmar la nueva contraseña (2 veces)
    - Mínimo 5 caracteres para la nueva contraseña
    
    Proceso:
    1. El estudiante envía su contraseña actual
    2. El sistema verifica que sea correcta
    3. El estudiante envía la nueva contraseña 2 veces
    4. El sistema valida que coincidan
    5. Se actualiza la contraseña (hasheada)
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


@router.put("/{id}", response_model=StudentResponse)
async def update_student_admin(
    *,
    id: PydanticObjectId,
    student_in: StudentUpdateAdmin,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Actualizar cualquier estudiante (solo admins).
    
    Requiere: ADMIN o SUPERADMIN
    
    Los administradores pueden actualizar:
    - Datos personales (nombre, email, carnet, extensión, etc.)
    - Tipo de estudiante (interno/externo)
    - Estado (activo/inactivo)
    - Cursos inscritos
    - Título profesional (datos del título)
    
    Para subir archivos, usar los endpoints dedicados:
    - POST /students/{id}/upload/photo
    - POST /students/{id}/upload/cv
    - POST /students/{id}/upload/carnet
    - POST /students/{id}/upload/afiliacion
    - POST /students/{id}/upload/titulo (solo admins)
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    student = await student_service.update_student(student=student, student_in=student_in)
    return student


@router.delete("/{id}", response_model=StudentResponse)
async def delete_student(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Eliminar estudiante.
    
    Requiere: ADMIN o SUPERADMIN (solo SUPERADMIN puede eliminar)
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

@router.post("/{id}/upload/photo", response_model=StudentResponse)
async def upload_student_photo(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir foto de perfil del estudiante
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden subir foto a cualquier estudiante
    - STUDENT: Solo puede subir su propia foto
    
    Formatos permitidos: JPG, PNG, WEBP
    Tamaño máximo: 5MB
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

