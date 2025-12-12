from typing import List, Any, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, Form, Query
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdateSelf, StudentUpdateAdmin, ChangePassword
from services import student_service
from beanie import PydanticObjectId
from api.dependencies import require_admin, get_current_user

router = APIRouter()

@router.get("/", response_model=List[StudentResponse])
async def read_students(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1),
    q: Optional[str] = Query(None, description="Buscar por nombre, email, carnet o registro"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    estado_titulo: Optional[str] = Query(None, description="Filtrar por estado del título (pendiente, verificado, etc)"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso inscrito"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Recuperar estudiantes con filtros.
    
    Requiere: ADMIN o SUPERADMIN
    
    Filtros:
    - q: Búsqueda de texto
    - activo: true/false
    - estado_titulo: pendiente, verificado, rechazado, sin_titulo
    - curso_id: ID de un curso
    """
    students = await student_service.get_students(
        skip=skip,
        limit=limit,
        q=q,
        activo=activo,
        estado_titulo=estado_titulo,
        curso_id=curso_id
    )
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
    # Usar nombre descriptivo como public_id
    safe_name = student.nombre.replace(' ', '_').replace('/', '_')
    public_id = f"CV_{safe_name}"
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
    # Usar nombre descriptivo como public_id
    safe_name = student.nombre.replace(' ', '_').replace('/', '_')
    public_id = f"Carnet_{safe_name}"
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
    # Usar nombre descriptivo como public_id
    safe_name = student.nombre.replace(' ', '_').replace('/', '_')
    public_id = f"Afiliacion_{safe_name}"
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
    titulo: str = Form(...),
    numero_titulo: str = Form(...),
    año_expedicion: str = Form(...),
    universidad: str = Form(...),
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Subir título profesional del estudiante
    
    Requiere: Autenticación
    - STUDENT: Puede subir su propio título (queda PENDIENTE de validación)
    - ADMIN: Puede subir título a cualquier estudiante (queda VERIFICADO automáticamente)
    
    El estudiante debe proporcionar:
    - file: PDF del título
    - titulo: Nombre del título (ej: "Licenciatura en Ingeniería")
    - numero_titulo: Número del título
    - año_expedicion: Año de expedición
    - universidad: Universidad emisora
    
    Formato: PDF
    Tamaño máximo: 10MB
    """
    from core.cloudinary_utils import upload_pdf
    from models.title import Title
    from models.enums import EstadoTitulo
    from datetime import datetime
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    # Verificar permisos
    is_admin = isinstance(current_user, User)
    is_own_student = isinstance(current_user, Student) and current_user.id == id
    
    if not is_admin and not is_own_student:
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para subir título a este estudiante"
        )
    
    # Subir PDF a Cloudinary
    folder = f"students/{id}/documents"
    safe_name = student.nombre.replace(' ', '_').replace('/', '_')
    public_id = f"Titulo_{safe_name}"
    titulo_url = await upload_pdf(file, folder, public_id)
    
    # Crear objeto Title con estado según quién lo sube
    if is_admin:
        # Admin sube → VERIFICADO automáticamente
        student.titulo = Title(
            titulo=titulo,
            numero_titulo=numero_titulo,
            año_expedicion=año_expedicion,
            universidad=universidad,
            titulo_url=titulo_url,
            estado=EstadoTitulo.VERIFICADO,
            verificado_por=current_user.username,
            fecha_verificacion=datetime.utcnow()
        )
    else:
        # Estudiante sube → PENDIENTE de validación
        student.titulo = Title(
            titulo=titulo,
            numero_titulo=numero_titulo,
            año_expedicion=año_expedicion,
            universidad=universidad,
            titulo_url=titulo_url,
            estado=EstadoTitulo.PENDIENTE
        )
    
    await student.save()
    return student


@router.put("/{id}/titulo/verificar", response_model=StudentResponse)
async def verificar_titulo(
    *,
    id: PydanticObjectId,
    titulo: Optional[str] = Form(None),
    numero_titulo: Optional[str] = Form(None),
    año_expedicion: Optional[str] = Form(None),
    universidad: Optional[str] = Form(None),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Verificar y aprobar el título de un estudiante
    
    Requiere: ADMIN o SUPERADMIN
    
    El admin puede:
    - Aprobar el título tal como está (sin enviar datos)
    - Corregir datos antes de aprobar (enviar datos corregidos)
    
    Parámetros opcionales:
    - titulo: Corregir nombre del título
    - numero_titulo: Corregir número
    - año_expedicion: Corregir año
    - universidad: Corregir universidad
    """
    from models.enums import EstadoTitulo
    from datetime import datetime
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    if not student.titulo:
        raise HTTPException(status_code=400, detail="El estudiante no tiene título para verificar")
    
    if student.titulo.estado == EstadoTitulo.VERIFICADO:
        raise HTTPException(status_code=400, detail="El título ya está verificado")
    
    # Actualizar datos si el admin los proporcionó
    if titulo:
        student.titulo.titulo = titulo
    if numero_titulo:
        student.titulo.numero_titulo = numero_titulo
    if año_expedicion:
        student.titulo.año_expedicion = año_expedicion
    if universidad:
        student.titulo.universidad = universidad
    
    # Marcar como verificado
    student.titulo.estado = EstadoTitulo.VERIFICADO
    student.titulo.verificado_por = current_user.username
    student.titulo.fecha_verificacion = datetime.utcnow()
    student.titulo.motivo_rechazo = None  # Limpiar motivo de rechazo si existía
    
    await student.save()
    return student


@router.put("/{id}/titulo/rechazar", response_model=StudentResponse)
async def rechazar_titulo(
    *,
    id: PydanticObjectId,
    motivo: str = Form(..., description="Razón del rechazo"),
    current_user: User = Depends(require_admin)
) -> Any:
    """
    Rechazar el título de un estudiante
    
    Requiere: ADMIN o SUPERADMIN
    
    El admin debe proporcionar un motivo del rechazo para que
    el estudiante sepa qué corregir.
    
    Ejemplos de motivos:
    - "Documento ilegible"
    - "Falta información"
    - "Documento no corresponde a un título"
    """
    from models.enums import EstadoTitulo
    from datetime import datetime
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    if not student.titulo:
        raise HTTPException(status_code=400, detail="El estudiante no tiene título para rechazar")
    
    # Marcar como rechazado
    student.titulo.estado = EstadoTitulo.RECHAZADO
    student.titulo.verificado_por = current_user.username
    student.titulo.fecha_verificacion = datetime.utcnow()
    student.titulo.motivo_rechazo = motivo
    
    await student.save()
    return student
