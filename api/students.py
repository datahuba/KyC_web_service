from datetime import datetime
from typing import List, Any, Union, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query, status
from pydantic import BaseModel, Field
from models.student import Student
from models.user import User
from schemas.student import StudentCreate, StudentResponse, StudentUpdateSelf, StudentUpdateAdmin, ChangePassword
from services import student_service
from beanie import PydanticObjectId

# IMPORTAMOS NUESTRAS LLAVES DE SEGURIDAD GRANULARES DE LA UAGRM
from api.dependencies import require_superadmin, require_cpd, require_staff, require_cobranza, get_current_user, require_encargado_curso

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
    per_page: int = Query(10, ge=1, le=5000, description="Elementos por página"),
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
    current_user: User = Depends(require_encargado_curso) # <-- CPD, ADMIN, ENCARGADO, COORDINADOR PUEDEN CREAR ALUMNOS
) -> Any:
    """Crear nuevo estudiante"""
    try:
        student = await student_service.create_student(student_in=student_in)
        return student
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get(
    "/me",
    response_model=StudentResponse,
    summary="Ver Mi Perfil (Estudiante autenticado)"
)
async def read_student_self(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    FIX-ERRORES-500: devuelve el perfil del estudiante autenticado.
    Importante: este endpoint debe declararse ANTES de /{id} para que
    no se matchee con id="me" (que rompe PydanticObjectId y causaba
    500 por un ValueError no serializable en exc.errors()).
    """
    # F-081: get_current_user retorna Union[User, Student]. Si el token es
    # de un User (admin/staff), no tiene perfil de Student — devolver 403
    # en vez de causar 500 al intentar serializar el User como Student.
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Este endpoint es solo para estudiantes. Use /auth/me para su perfil."
        )
    return current_user


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


# ========================================================================
# ISSUE-P-RECORDATORIO-PAGO (2026-07-08, reunión de postgrado contaduría):
# Cobranza necesita poder enviar un recordatorio de pago manual a un
# estudiante específico desde su perfil (in-app + correo real, no bloqueante
# si el estudiante no tiene email o SMTP falla).
# ========================================================================
class RecordatorioPagoRequest(BaseModel):
    mensaje: str = Field(..., min_length=5, max_length=1000, description="Texto del recordatorio a enviar al estudiante")


@router.post(
    "/{id}/recordatorio-pago",
    status_code=status.HTTP_200_OK,
    summary="Enviar Recordatorio de Pago Manual (Cobranza)"
)
async def enviar_recordatorio_pago(
    *,
    id: PydanticObjectId,
    payload: RecordatorioPagoRequest,
    current_user: User = Depends(require_cobranza)  # <-- COBRANZA, CPD, ADMIN, SUPERADMIN
) -> Any:
    """
    Envía un recordatorio de pago manual al estudiante `id`: notificación
    in-app (siempre) + correo real si tiene email registrado y SMTP está
    configurado (no bloqueante si falla o no hay email).
    """
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")

    from services.notification_service import create_notification
    await create_notification(
        destinatario_id=student.id,
        tipo_destinatario="student",
        titulo="Recordatorio de Pago",
        mensaje=payload.mensaje,
        tipo_alerta="warning",
        ruta="/app/payments"
    )

    email_enviado = False
    if student.email:
        try:
            from core.email_utils import send_email, build_recordatorio_pago_email
            from core.config import settings

            portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/payments"
            html = build_recordatorio_pago_email(
                nombre=student.nombre or student.registro,
                mensaje=payload.mensaje,
                portal_link=portal_link
            )
            email_enviado = await send_email(
                student.email,
                "Recordatorio de Pago · Posgrado UAGRM",
                html
            )
        except Exception as e:
            print(f"Error enviando correo de recordatorio de pago: {str(e)}")

    return {
        "success": True,
        "notificacion_in_app": True,
        "email_enviado": email_enviado,
        "detail": "Recordatorio enviado correctamente."
    }


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
    try:
        student = await student_service.update_student(student=current_user, student_in=student_in)
        return student
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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

    if password_data.current_password == password_data.new_password:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe ser diferente a la actual")
    
    current_user.password = get_password_hash(password_data.new_password)
    await current_user.save()
    return current_user


@router.post(
    "/me/accept-terms",
    response_model=StudentResponse,
    summary="Aceptar Términos y Condiciones (ISSUE-Q-PRE)"
)
async def accept_terms(
    *,
    current_user: Student = Depends(get_current_user)
) -> Any:
    """
    Registra la aceptación del reglamento de Posgrado por parte del estudiante.

    Se exige en el primer inicio de sesión (bloqueado por el frontend hasta
    que se llame este endpoint). Es idempotente: llamarlo de nuevo no falla
    ni pisa la fecha de la primera aceptación.
    """
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo estudiantes")
    student = await student_service.accept_terms(student=current_user)
    return student


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
    try:
        student = await student_service.update_student(student=student, student_in=student_in)
        return student
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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


async def _subir_documento_estudiante(file: UploadFile, folder: str, public_id: str) -> str:
    """Sube un documento del estudiante (CV/Carnet/Afiliación) aceptando PDF o
    imagen (JPG/PNG/WEBP), ya que muchos suben fotos del documento. Devuelve la URL."""
    from core.cloudinary_utils import upload_pdf, upload_image
    image_types = ["image/jpeg", "image/jpg", "image/png", "image/webp"]
    if file.content_type in image_types:
        return await upload_image(file, folder, public_id)
    elif file.content_type == "application/pdf":
        return await upload_pdf(file, folder, public_id)
    raise HTTPException(400, f"Formato no permitido: {file.content_type}. Sube el documento como PDF o imagen (JPG/PNG).")


@router.post("/{id}/upload/cv", response_model=StudentResponse)
async def upload_student_cv(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    cv_url = await _subir_documento_estudiante(file, f"students/{id}/cv", f"cv_{id}")
    student.cv_url = cv_url
    student.cv_estado = "verificado"
    student.cv_motivo_rechazo = None
    await student.save()
    return student

@router.post("/{id}/upload/carnet", response_model=StudentResponse)
async def upload_student_carnet(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    carnet_url = await _subir_documento_estudiante(file, f"students/{id}/carnet", f"carnet_{id}")
    student.carnet_url = carnet_url
    student.carnet_estado = "verificado"
    student.carnet_motivo_rechazo = None
    await student.save()
    return student

@router.post("/{id}/upload/afiliacion", response_model=StudentResponse)
async def upload_student_afiliacion(*, id: PydanticObjectId, file: UploadFile, current_user: Union[User, Student] = Depends(get_current_user)) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    afiliacion_url = await _subir_documento_estudiante(file, f"students/{id}/afiliacion", f"afiliacion_{id}")
    student.afiliacion_url = afiliacion_url
    student.afiliacion_estado = "verificado"
    student.afiliacion_motivo_rechazo = None
    await student.save()
    return student

@router.post("/{id}/upload/titulo", response_model=StudentResponse)
async def upload_student_titulo(
    *, id: PydanticObjectId, file: UploadFile, titulo: str = Form(...), numero_titulo: str = Form(...),
    año_expedicion: str = Form(...), universidad: str = Form(...), current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    if isinstance(current_user, Student) and current_user.id != id: raise HTTPException(403, "No tienes permiso")
    
    folder = f"students/{id}/titulo"
    public_id = f"titulo_{id}"
    titulo_url = await _subir_documento_estudiante(file, folder, public_id)
    
    student.titulo = {
        "titulo": titulo, "numero_titulo": numero_titulo, "año_expedicion": año_expedicion,
        "universidad": universidad, "estado": "verificado", "titulo_url": titulo_url, "url": titulo_url, "motivo_rechazo": None
    }
    await student.save()

    # Notificar a revisores (CPD, Admin, Superadmin y Encargados)
    try:
        from services.notification_service import create_notification
        from beanie.operators import Or as _Or
        from models.enrollment import Enrollment

        nombre_est = student.nombre or student.registro
        enrollments = await Enrollment.find(Enrollment.estudiante_id == student.id).to_list()
        curso_ids = [e.curso_id for e in enrollments]

        revisores = await User.find(
            User.activo == True,
            _Or(
                User.rol == UserRole.CPD,
                User.rol == UserRole.ADMIN,
                User.rol == UserRole.SUPERADMIN,
                User.rol == UserRole.ENCARGADO_CURSO
            )
        ).to_list()

        for revisor in revisores:
            if revisor.rol == UserRole.ENCARGADO_CURSO:
                if not any(c_id in revisor.cursos_asignados for c_id in curso_ids):
                    continue
            await create_notification(
                destinatario_id=revisor.id,
                tipo_destinatario="user",
                titulo="Título Profesional por revisar",
                mensaje=f"{nombre_est} subió su Título Profesional ('{titulo}') y requiere tu revisión.",
                tipo_alerta="info",
                ruta="/app/students",
                referencia_tipo="student",
                referencia_id=student.id
            )
    except Exception as e:
        print(f"Error notificando subida de titulo a revisores: {str(e)}")

    return student

@router.put("/{id}/titulo/verificar", response_model=StudentResponse)
async def verificar_titulo_estudiante(
    *, id: PydanticObjectId, titulo: Optional[str] = Form(None), numero_titulo: Optional[str] = Form(None),
    año_expedicion: Optional[str] = Form(None), universidad: Optional[str] = Form(None), 
    current_user: User = Depends(require_encargado_curso) # <-- ENCARGADO DE CURSO Y SUPERIORES VERIFICAN TÍTULOS ACADÉMICOS
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
async def rechazar_titulo_estudiante(*, id: PydanticObjectId, motivo: str = Form(...), current_user: User = Depends(require_encargado_curso)) -> Any:
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    
    if not student.titulo:
        student.titulo = {"titulo": None, "numero_titulo": None, "año_expedicion": None, "universidad": None, "estado": "rechazado", "url": None, "motivo_rechazo": motivo}
    else:
        student.titulo["estado"] = "rechazado"
        student.titulo["motivo_rechazo"] = motivo
        
    await student.save()
    return student

@router.put("/{id}/documentos/{tipo}/verificar", response_model=StudentResponse)
async def verificar_documento_estudiante(
    id: PydanticObjectId,
    tipo: str,
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    if tipo not in ["cv", "carnet", "afiliacion"]:
        raise HTTPException(400, "Tipo de documento inválido")
        
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    
    if tipo == "cv":
        student.cv_estado = "verificado"
        student.cv_motivo_rechazo = None
    elif tipo == "carnet":
        student.carnet_estado = "verificado"
        student.carnet_motivo_rechazo = None
    elif tipo == "afiliacion":
        student.afiliacion_estado = "verificado"
        student.afiliacion_motivo_rechazo = None
        
    await student.save()
    return student

@router.put("/{id}/documentos/{tipo}/rechazar", response_model=StudentResponse)
async def rechazar_documento_estudiante(
    id: PydanticObjectId,
    tipo: str,
    motivo: str = Form(...),
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    if tipo not in ["cv", "carnet", "afiliacion"]:
        raise HTTPException(400, "Tipo de documento inválido")
        
    student = await student_service.get_student(id=id)
    if not student: raise HTTPException(404, "Estudiante no encontrado")
    
    if tipo == "cv":
        student.cv_estado = "rechazado"
        student.cv_motivo_rechazo = motivo
    elif tipo == "carnet":
        student.carnet_estado = "rechazado"
        student.carnet_motivo_rechazo = motivo
    elif tipo == "afiliacion":
        student.afiliacion_estado = "rechazado"
        student.afiliacion_motivo_rechazo = motivo
        
    await student.save()
    return student


# ============================================================================
# ISSUE G: Selector en Importación Masiva
# ============================================================================
@router.post("/import/excel", summary="Importar Estudiantes de forma Masiva desde Excel")
async def import_students(
    file: UploadFile = File(...), 
    curso_id: Optional[PydanticObjectId] = Form(None), # Curso opcional para auto-inscribir a los estudiantes importados
    current_user: User = Depends(require_cpd)
) -> Any:
    if not file.filename.lower().endswith(('.xlsx', '.xls', '.csv')):
        raise HTTPException(400, "Formato no permitido. Sube un archivo .xlsx, .xls o .csv")
    contents = await file.read()
    try:
        return await student_service.import_students_from_excel(contents, curso_id, file.filename)
    except ValueError as e:
        raise HTTPException(400, str(e))


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


@router.get(
    "/{id}/financial-summary",
    response_model=dict,
    summary="Resumen Financiero del Estudiante"
)
async def read_student_financial_summary(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    Obtener ficha de estado de cuenta unificada del estudiante (Total Invertido, Pagado, En Proceso, Saldo Pendiente).
    Excluye explícitamente al rol CPD según políticas de segregación de funciones.
    """
    # 1. Si el usuario actual es un Estudiante, solo puede consultar su propia ficha
    if isinstance(current_user, Student) and current_user.id != id:
        raise HTTPException(
            status_code=403,
            detail="Acceso denegado: No tienes permiso para visualizar el estado financiero de otro estudiante."
        )
    
    # 2. Si el usuario es un personal de la institución (User), validar segregación de funciones (CPD restringido)
    if isinstance(current_user, User):
        from models.enums import UserRole
        if current_user.rol == UserRole.CPD:
            raise HTTPException(
                status_code=403,
                detail="Acceso denegado: El rol de Gestión Académica (CPD) no tiene permisos para visualizar datos financieros."
            )
            
    student = await student_service.get_student(id=id)
    if not student:
        raise HTTPException(status_code=404, detail="Estudiante no encontrado")
        
    summary = await student_service.get_student_financial_summary(student_id=id)
    return summary

