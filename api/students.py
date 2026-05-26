from typing import List, Any, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdateSelf, StudentUpdateAdmin, ChangePassword
from services import student_service
from beanie import PydanticObjectId

# IMPORTAMOS NUESTRAS LLAVES DE SEGURIDAD GRANULARES DE LA UAGRM
from api.dependencies import require_superadmin, require_cpd, require_staff, get_current_user

router = APIRouter()

from schemas.common import PaginatedResponse, PaginationMeta
import math

@router.get(
    "/",
    response_model=PaginatedResponse[StudentResponse],
    summary="Listar Estudiantes"
)
async def read_students(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Buscar por nombre, email, carnet o registro"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo/inactivo"),
    estado_titulo: Optional[str] = Query(None, description="Filtrar por estado del título"),
    curso_id: Optional[PydanticObjectId] = Query(None, description="Filtrar por curso inscrito"),
    current_user: User = Depends(require_staff) # <-- TODOS LOS ADMINISTRATIVOS (MAE, COBRANZA, CPD) PUEDEN LEER LA TABLA
) -> Any:
    """Listar estudiantes con paginación y filtros avanzados"""
    students, total_count = await student_service.get_students(
        page=page, per_page=per_page, q=q, activo=activo, estado_titulo=estado_titulo, curso_id=curso_id
    )
    
    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0
    return {
        "data": students,
        "meta": PaginationMeta(
            page=page, limit=per_page, totalItems=total_count, totalPages=total_pages,
            hasNextPage=(page < total_pages), hasPrevPage=(page > 1)
        )
    }

@router.post(
    "/",
    response_model=StudentResponse,
    status_code=201,
    summary="Crear Estudiante"
)
async def create_student(
    *,
    student_in: StudentCreate,
    current_user: User = Depends(require_cpd) # <-- SOLO EL CPD (Y ADMINS) PUEDEN CREAR ALUMNOS
) -> Any:
    """Crear nuevo estudiante"""
    student = await student_service.create_student(student_in=student_in)
    return student

@router.get(
    "/{id}",
    response_model=StudentResponse,
    summary="Ver Estudiante"
)
async def read_student(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Ver perfil de un estudiante"""
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(status_code=403, detail="No tienes permiso")
    return student

@router.put(
    "/me",
    response_model=StudentResponse,
    summary="Actualizar Mi Perfil"
)
async def update_student_self(
    *,
    student_in: StudentUpdateSelf,
    current_user: Student = Depends(get_current_user)
) -> Any:
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo estudiantes")
    student = await student_service.update_student(student=current_user, student_in=student_in)
    return student


@router.post(
    "/me/change-password",
    response_model=StudentResponse,
    summary="Cambiar Mi Contraseña"
)
async def change_password(
    *,
    password_data: ChangePassword,
    current_user: Student = Depends(get_current_user)
) -> Any:
    from core.security import verify_password, get_password_hash
    if not verify_password(password_data.current_password, current_user.password):
        raise HTTPException(status_code=400, detail="La contraseña actual es incorrecta")
    
    current_user.password = get_password_hash(password_data.new_password)
    await current_user.save()
    return current_user


@router.put(
    "/{id}",
    response_model=StudentResponse,
    summary="Actualizar Estudiante (Admin)"
)
async def update_student_admin(
    *,
    id: PydanticObjectId,
    student_in: StudentUpdateAdmin,
    current_user: User = Depends(require_cpd) # <-- SOLO EL CPD ACTUALIZA DATOS ACADÉMICOS
) -> Any:
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    student = await student_service.update_student(student=student, student_in=student_in)
    return student


@router.delete(
    "/{id}",
    response_model=StudentResponse,
    summary="Eliminar Estudiante"
)
async def delete_student(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin) # <-- SOLO EL SUPERADMIN PUEDE BORRAR
) -> Any:
    """Eliminar estudiante (Retención de Auditoría Operativa)"""
    from models.enums import UserRole
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Solo SUPERADMIN puede eliminar estudiantes")
    
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
    
    from models.enrollment import Enrollment
    try:
        from models.payment import Payment
    except ImportError:
        Payment = None

    enrollments = await Enrollment.find(Enrollment.estudiante_id == id).to_list()
    enrollment_ids = [e.id for e in enrollments]

    if enrollment_ids and Payment:
        # SOLO PURGAMOS LOS PENDIENTES
        await Payment.find({"enrollment_id": {"$in": enrollment_ids}, "estado_pago": "pendiente"}).delete()
        await Payment.find({"estudiante_id": id, "estado_pago": "pendiente"}).delete()

    await Enrollment.find(Enrollment.estudiante_id == id).delete()
    student = await student_service.delete_student(id=id)
    return student


@router.post(
    "/{id}/upload/photo",
    response_model=StudentResponse,
    summary="Subir Foto de Perfil"
)
async def upload_student_photo(
    *,
    id: PydanticObjectId,
    file: UploadFile,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    from core.cloudinary_utils import upload_image
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/photo"
    public_id = f"photo_{id}"
    foto_url = await upload_image(file, folder, public_id)
    student.foto_url = foto_url
    await student.save()
    return student


@router.post("/{id}/upload/cv", response_model=StudentResponse)
async def upload_student_cv(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    from core.cloudinary_utils import upload_pdf
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/cv"
    public_id = f"cv_{id}"
    student.cv_url = await upload_pdf(file, folder, public_id)
    await student.save()
    return student

@router.post("/{id}/upload/carnet", response_model=StudentResponse)
async def upload_student_carnet(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    from core.cloudinary_utils import upload_pdf
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/carnet"
    public_id = f"carnet_{id}"
    student.carnet_url = await upload_pdf(file, folder, public_id)
    await student.save()
    return student

@router.post("/{id}/upload/afiliacion", response_model=StudentResponse)
async def upload_student_afiliacion(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    from core.cloudinary_utils import upload_pdf
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/afiliacion"
    public_id = f"afiliacion_{id}"
    student.afiliacion_url = await upload_pdf(file, folder, public_id)
    await student.save()
    return student

@router.post("/{id}/upload/titulo", response_model=StudentResponse)
async def upload_student_titulo(
    *, id: PydanticObjectId, file: UploadFile, titulo: str = Form(...), numero_titulo: str = Form(...),
    año_expedicion: str = Form(...), universidad: str = Form(...), current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    from core.cloudinary_utils import upload_pdf
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/titulo"
    public_id = f"titulo_{id}"
    titulo_url = await upload_pdf(file, folder, public_id)
    
    student.titulo = {
        "titulo": titulo, "numero_titulo": numero_titulo, "año_expedicion": año_expedicion,
        "universidad": universidad, "estado": "pendiente", "url": titulo_url, "motivo_rechazo": None
    }
    await student.save()
    return student

@router.put("/{id}/titulo/verificar", response_model=StudentResponse)
async def verificar_titulo_estudiante(
    *, id: PydanticObjectId, titulo: Optional[str] = Form(None), numero_titulo: Optional[str] = Form(None),
    año_expedicion: Optional[str] = Form(None), universidad: Optional[str] = Form(None), 
    current_user: User = Depends(require_cpd) # <-- CPD VERIFICA TÍTULOS ACADÉMICOS
) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    
    if not student.titulo:
        student.titulo = {"titulo": titulo, "numero_titulo": numero_titulo, "año_expedicion": año_expedicion, "universidad": universidad, "estado": "verificado", "url": None, "motivo_rechazo": None}
    else:
        if titulo: student.titulo["titulo"] = titulo
        if numero_titulo: student.titulo["numero_titulo"] = numero_titulo
        if año_expedicion: student.titulo["año_expedicion"] = año_expedicion
        if universidad: student.titulo["universidad"] = universidad
        student.titulo["estado"] = "verificado"
        student.titulo["motivo_rechazo"] = None
        
    await student.save()
    return student

@router.put("/{id}/titulo/rechazar", response_model=StudentResponse)
async def rechazar_titulo_estudiante(*, id: PydanticObjectId, motivo: str = Form(...), current_user: User = Depends(require_cpd)) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    
    if not student.titulo:
        student.titulo = {"titulo": None, "numero_titulo": None, "año_expedicion": None, "universidad": None, "estado": "rechazado", "url": None, "motivo_rechazo": motivo}
    else:
        student.titulo["estado"] = "rechazado"
        student.titulo["motivo_rechazo"] = motivo
        
    await student.save()
    return student

@router.post("/import/excel", summary="Importar Estudiantes de forma Masiva desde Excel")
async def import_students(file: UploadFile = File(...), current_user: User = Depends(require_cpd)) -> Any:
    if not file.filename.endswith(('.xlsx', '.xls')): raise HTTPException(400, "Formato no permitido")
    contents = await file.read()
    try:
        return await student_service.import_students_from_excel(contents)
    except ValueError as e:
        raise HTTPException(400, str(e))

from pydantic import BaseModel
class BulkDeleteRequest(BaseModel):
    ids: List[PydanticObjectId]

@router.post("/bulk-delete", summary="Eliminar Estudiantes en Lote (Cascada)")
async def bulk_delete_students(*, payload: BulkDeleteRequest, current_user: User = Depends(require_superadmin)) -> Any:
    from models.enums import UserRole
    from models.enrollment import Enrollment
    try: from models.payment import Payment
    except ImportError: Payment = None
        
    if current_user.rol != UserRole.SUPERADMIN: raise HTTPException(403, "Solo SUPERADMIN")
    if not payload.ids: raise HTTPException(400, "Debe proporcionar IDs")
        
    enrollments = await Enrollment.find({"estudiante_id": {"$in": payload.ids}}).to_list()
    enrollment_ids = [e.id for e in enrollments]
    
    if Payment:
        # SOLO PURGAMOS LOS PENDIENTES
        if enrollment_ids: await Payment.find({"enrollment_id": {"$in": enrollment_ids}, "estado_pago": "pendiente"}).delete()
        await Payment.find({"estudiante_id": {"$in": payload.ids}, "estado_pago": "pendiente"}).delete()
        
    await Enrollment.find({"estudiante_id": {"$in": payload.ids}}).delete()
    await Student.find({"_id": {"$in": payload.ids}}).delete()
    
    return {"message": f"Se eliminaron {len(payload.ids)} estudiantes.", "deleted_count": len(payload.ids)}