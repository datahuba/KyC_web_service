from typing import List, Any, Union
from fastapi import APIRouter, Depends, HTTPException, UploadFile
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdateSelf, StudentUpdateAdmin
from services import student_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[StudentResponse])
async def read_students(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Recuperar estudiantes.
    
    Requiere: ADMIN o SUPERADMIN
    """
    students = await student_service.get_students(skip=skip, limit=limit)
    return students

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

@router.put("/{id}", response_model=StudentResponse)
async def update_student(
    *,
    id: PydanticObjectId,
    student_in: Union[StudentUpdateSelf, StudentUpdateAdmin],
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Actualizar estudiante.
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden actualizar cualquier estudiante (StudentUpdateAdmin)
    - STUDENT: Solo puede actualizar su propio perfil (StudentUpdateSelf)
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Si es estudiante, solo puede actualizar su propio perfil
    if isinstance(current_user, Student):
        if current_user.id != id:
            raise HTTPException(
                status_code=403,
                detail="No tienes permiso para actualizar este estudiante"
            )
        # Validar que el estudiante use StudentUpdateSelf
        if not isinstance(student_in, StudentUpdateSelf):
            raise HTTPException(
                status_code=403,
                detail="Los estudiantes solo pueden usar StudentUpdateSelf"
            )
    
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


@router.post("/{id}/upload/cv", response_model=StudentResponse)
async def upload_student_cv(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir CV del estudiante
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden subir CV a cualquier estudiante
    - STUDENT: Solo puede subir su propio CV
    
    Formato: PDF
    Tamaño máximo: 10MB
    """
    from core.cloudinary_utils import upload_pdf
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Verificar permisos
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para subir archivos a este estudiante"
        )
    
    # Subir PDF a Cloudinary
    folder = f"students/{id}/documents"
    public_id = f"cv_{id}"
    cv_url = await upload_pdf(file, folder, public_id)
    
    # Actualizar URL en el estudiante
    student.cv_url = cv_url
    await student.save()
    
    return student


@router.post("/{id}/upload/carnet", response_model=StudentResponse)
async def upload_student_carnet(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir carnet de identidad del estudiante
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden subir carnet a cualquier estudiante
    - STUDENT: Solo puede subir su propio carnet
    
    Formato: PDF
    Tamaño máximo: 10MB
    """
    from core.cloudinary_utils import upload_pdf
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Verificar permisos
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para subir archivos a este estudiante"
        )
    
    # Subir PDF a Cloudinary
    folder = f"students/{id}/documents"
    public_id = f"carnet_{id}"
    ci_url = await upload_pdf(file, folder, public_id)
    
    # Actualizar URL en el estudiante
    student.ci_url = ci_url
    await student.save()
    
    return student


@router.post("/{id}/upload/afiliacion", response_model=StudentResponse)
async def upload_student_afiliacion(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir certificado de afiliación profesional del estudiante
    
    Requiere: Autenticación
    - ADMIN/SUPERADMIN: Pueden subir afiliación a cualquier estudiante
    - STUDENT: Solo puede subir su propia afiliación
    
    Formato: PDF
    Tamaño máximo: 10MB
    """
    from core.cloudinary_utils import upload_pdf
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Verificar permisos
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para subir archivos a este estudiante"
        )
    
    # Subir PDF a Cloudinary
    folder = f"students/{id}/documents"
    public_id = f"afiliacion_{id}"
    afiliacion_url = await upload_pdf(file, folder, public_id)
    
    # Actualizar URL en el estudiante
    student.afiliacion_url = afiliacion_url
    await student.save()
    
    return student


@router.post("/{id}/upload/titulo", response_model=StudentResponse)
async def upload_student_titulo(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Subir título profesional del estudiante
    
    Requiere: ADMIN o SUPERADMIN
    
    Solo administradores pueden subir títulos (documentos oficiales)
    
    Formato: PDF
    Tamaño máximo: 10MB
    """
    from core.cloudinary_utils import upload_pdf
    from models.title import Title
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Subir PDF a Cloudinary
    folder = f"students/{id}/documents"
    public_id = f"titulo_{id}"
    titulo_url = await upload_pdf(file, folder, public_id)
    
    # Si no tiene título, crear uno nuevo
    if not student.titulo:
        student.titulo = Title(
            titulo="Título pendiente de actualizar",
            numero_titulo="",
            año_expedicion="",
            universidad="",
            titulo_url=titulo_url
        )
    else:
        # Actualizar URL del título existente
        student.titulo.titulo_url = titulo_url
    
    await student.save()
    
    return student
