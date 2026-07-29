"""
API de Certificados
===================

Endpoints para emisión y consulta de Certificados de Notas y No Deudor.

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md

RBAC:
- Estudiante: puede emitir sus propios certificados y descargar solo los suyos.
- Staff (CPD/Admin/Superadmin/Cobranza/MAE/Coordinador): puede ver/descargar
  cualquier certificado (auditoría).
"""

import io
from typing import Optional, Union
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_user
from models.certificate import Certificate
from models.enums import TipoCertificado
from models.student import Student
from models.user import User
from schemas.certificate import (
    CertificateEmitRequest,
    CertificateListResponse,
    CertificateOut,
    CertificateModuloOut,
)
import services.certificate_service as certificate_service

router = APIRouter()


# ========================================================================
# HELPERS de serialización
# ========================================================================

def _serializar_cert(cert: Certificate) -> CertificateOut:
    """Convierte un Certificate (Beanie doc) a CertificateOut (Pydantic schema)."""
    modulos_out = [
        CertificateModuloOut(
            nombre=m.nombre,
            nota=m.nota,
            literal=m.literal,
            estado=m.estado,
            fecha_inicio=m.fecha_inicio,
            fecha_fin=m.fecha_fin,
        )
        for m in cert.modulos_snapshot
    ]
    return CertificateOut(
        id=str(cert.id),
        tipo=cert.tipo,
        folio=certificate_service._format_folio(cert.numero, cert.anio),
        numero=cert.numero,
        anio=cert.anio,
        student_id=str(cert.student_id),
        course_id=str(cert.course_id),
        enrollment_id=str(cert.enrollment_id),
        modulos_snapshot=modulos_out,
        hasta_modulo_n=cert.hasta_modulo_n,
        programa_nombre=cert.programa_nombre,
        programa_codigo=cert.programa_codigo,
        programa_version=cert.programa_version,
        programa_edicion=cert.programa_edicion,
        estudiante_nombre=cert.estudiante_nombre,
        estudiante_registro=cert.estudiante_registro,
        estudiante_ci=cert.estudiante_ci,
        estudiante_extension=cert.estudiante_extension,
        estudiante_complemento=cert.estudiante_complemento,
        emitido_en=cert.emitido_en,
        emitido_por=cert.emitido_por,
        verificacion_code=cert.verificacion_code,
        pdf_url=cert.pdf_url,
        pdf_filename=cert.pdf_filename,
    )


def _verificar_es_estudiante_o_staff(
    current_user: Union[Student, User],
) -> None:
    """
    Helper: el endpoint requiere que el current_user sea un Student autenticado
    o un User con rol staff. Lanza 403 si no.
    """
    if isinstance(current_user, Student):
        return
    if isinstance(current_user, User):
        staff_roles = {"SUPERADMIN", "ADMIN", "CPD", "COBRANZA", "MAE", "COORDINADOR", "ENCARGADO_CURSO"}
        if current_user.rol.value in staff_roles:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Solo el estudiante dueño o el personal autorizado puede acceder a este recurso.",
    )


# ========================================================================
# ENDPOINTS
# ========================================================================

@router.post(
    "/emit",
    status_code=status.HTTP_201_CREATED,
    summary="Emitir un certificado (Notas o No Deudor)",
    description=(
        "El estudiante autenticado pide emisión de su certificado. "
        "Para 'notas': requiere programa finalizado + saldo cero. "
        "Para 'no_deudor': requiere que los módulos 1..N estén todos pagados. "
        "FIX 2026-07-29 19:11: el staff también puede emitir en nombre de "
        "un estudiante (pasando el enrollment_id del estudiante)."
    ),
)
async def emit_certificate(
    payload: CertificateEmitRequest,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateOut:
    # FIX 2026-07-29 19:11: tanto el estudiante (auto-emisión) como el
    # staff (auditoría / soporte en ventanilla) pueden emitir certificados.
    # El RBAC granular se aplica en `_obtener_curso_estudiante_enrollment`
    # (estudiante solo puede emitir para sus propios enrollments; staff
    # puede emitir para cualquier enrollment).
    if not isinstance(current_user, (Student, User)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para emitir certificados.",
        )

    if payload.tipo == TipoCertificado.NOTAS:
        if payload.hasta_modulo_n is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="El parámetro 'hasta_modulo_n' solo aplica a certificados de tipo 'no_deudor'.",
            )
        cert = await certificate_service.emitir_certificado_notas(
            enrollment_id=payload.enrollment_id,
            current_user=current_user,
        )
    elif payload.tipo == TipoCertificado.NO_DEUDOR:
        if payload.hasta_modulo_n is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Para el certificado de tipo 'no_deudor' debes indicar 'hasta_modulo_n' (1..N).",
            )
        cert = await certificate_service.emitir_certificado_no_deudor(
            enrollment_id=payload.enrollment_id,
            hasta_modulo_n=payload.hasta_modulo_n,
            current_user=current_user,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tipo de certificado no soportado: {payload.tipo}",
        )

    return _serializar_cert(cert)


@router.get(
    "/my",
    response_model=CertificateListResponse,
    summary="Lista los certificados emitidos del estudiante autenticado",
)
async def list_my_certificates(
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateListResponse:
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint es solo para estudiantes.",
        )

    certs = await Certificate.find(
        Certificate.student_id == current_user.id
    ).sort("-emitido_en").to_list()

    return CertificateListResponse(
        items=[_serializar_cert(c) for c in certs],
        total=len(certs),
    )


@router.get(
    "/by-enrollment/{enrollment_id}",
    response_model=CertificateListResponse,
    summary="Lista los certificados emitidos de una inscripción (auditoría)",
)
async def list_by_enrollment(
    enrollment_id: str,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateListResponse:
    try:
        eid = ObjectId(enrollment_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="enrollment_id inválido.",
        )

    certs = await Certificate.find(
        Certificate.enrollment_id == eid
    ).sort("-emitido_en").to_list()

    # RBAC: el estudiante solo ve los certificados de SU propia inscripción.
    # Staff ve cualquiera.
    if certs and isinstance(current_user, Student):
        if certs[0].student_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver los certificados de esta inscripción.",
            )
    elif certs and isinstance(current_user, User):
        staff_roles = {"SUPERADMIN", "ADMIN", "CPD", "COBRANZA", "MAE", "COORDINADOR"}
        if current_user.rol.value not in staff_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permiso para ver los certificados de esta inscripción.",
            )

    return CertificateListResponse(
        items=[_serializar_cert(c) for c in certs],
        total=len(certs),
    )


@router.get(
    "/admin/list",
    summary="[Staff] Lista todos los certificados emitidos con filtros",
)
async def list_certificates_admin(
    student_id: Optional[str] = None,
    course_id: Optional[str] = None,
    enrollment_id: Optional[str] = None,
    tipo: Optional[str] = None,
    anio: Optional[int] = None,
    folio: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateListResponse:
    """
    FIX 2026-07-29 19:11: Kevin pidió que la sección Certificados sea visible
    para todos (estudiantes y staff). Para el staff, esta vista de auditoría
    lista todos los certificados emitidos con filtros.
    """
    from api.dependencies import STAFF_ROLES_HELPER  # type: ignore

    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta vista es solo para personal administrativo.",
        )
    # Verificar rol staff
    from models.enums import UserRole
    staff_roles = {UserRole.ADMIN, UserRole.SUPERADMIN, UserRole.MAE,
                   UserRole.CPD, UserRole.COBRANZA, UserRole.COORDINADOR}
    if current_user.rol not in staff_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para ver todos los certificados.",
        )

    # Construir query
    query: dict = {}
    if student_id:
        try:
            query["student_id"] = ObjectId(student_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=400, detail="student_id inválido.")
    if course_id:
        try:
            query["course_id"] = ObjectId(course_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=400, detail="course_id inválido.")
    if enrollment_id:
        try:
            query["enrollment_id"] = ObjectId(enrollment_id)
        except (InvalidId, TypeError):
            raise HTTPException(status_code=400, detail="enrollment_id inválido.")
    if tipo:
        query["tipo"] = tipo
    if anio:
        query["anio"] = anio
    if folio:
        # Búsqueda por folio parcial: convertir "N° 042" o "042" a número
        folio_clean = folio.replace("N°", "").replace("/", "").strip()
        if folio_clean.isdigit():
            query["numero"] = int(folio_clean)

    # Aplicar filtro de cursos permitidos para cobranza con cursos_asignados
    # (consistente con payments.py)
    from api.dependencies import filtro_cursos_por_rol
    filtro = filtro_cursos_por_rol(current_user)
    if filtro and "curso_id" in filtro:
        # El filtro tiene {"curso_id": {"$in": [...]}}
        cursos_permitidos = filtro["curso_id"].get("$in", [])
        if cursos_permitidos:
            query["course_id"] = {"$in": cursos_permitidos}

    # Paginar
    skip = (page - 1) * per_page
    total = await Certificate.find(query).count()
    certs = await Certificate.find(query).sort("-emitido_en").skip(skip).limit(per_page).to_list()

    return CertificateListResponse(
        items=[_serializar_cert(c) for c in certs],
        total=total,
    )


@router.get(
    "/{cert_id}/pdf",
    summary="Descarga el PDF de un certificado emitido",
    response_class=StreamingResponse,
)
async def download_certificate_pdf(
    cert_id: str,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> StreamingResponse:
    try:
        cid = ObjectId(cert_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cert_id inválido.",
        )

    cert = await Certificate.get(cid)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificado no encontrado.",
        )

    # RBAC
    certificate_service.verificar_acceso_certificado(cert, current_user)

    # Descargar PDF desde Cloudinary
    try:
        pdf_bytes = await certificate_service.descargar_pdf_bytes(cert)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo recuperar el PDF del almacenamiento: {str(e)}",
        )

    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{cert.pdf_filename}"',
            "Content-Length": str(len(pdf_bytes)),
        },
    )


@router.get(
    "/{cert_id}",
    response_model=CertificateOut,
    summary="Obtiene los metadatos de un certificado emitido",
)
async def get_certificate(
    cert_id: str,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateOut:
    try:
        cid = ObjectId(cert_id)
    except (InvalidId, TypeError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cert_id inválido.",
        )

    cert = await Certificate.get(cid)
    if not cert:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificado no encontrado.",
        )

    certificate_service.verificar_acceso_certificado(cert, current_user)
    return _serializar_cert(cert)
