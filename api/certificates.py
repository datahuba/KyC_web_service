"""
API de Certificados
===================

Endpoints para emisión y consulta de Certificados de Notas y No Deudor.

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md

F-CERT-APROBACION (2026-07-30): el estudiante NO descarga directo — primero
crea una solicitud que el ENCARGADO_CURSO del programa (o admin/superadmin)
debe APROBAR. Solo después de aprobada se emite el Certificate y el
estudiante puede descargarlo.

RBAC:
- Estudiante: puede crear solicitudes de sus propios certificados y descargar
  solo los suyos.
- Encargado de Curso (rol ENCARGADO_CURSO con cursos_asignados): ve y aprueba/
  rechaza las solicitudes de SUS programas.
- Admin / Superadmin: aprueban cualquier solicitud (backup).
- Resto de staff (CPD, Coordinador, MAE, Cobranza): ve la cola para auditoría
  pero no aprueba.
"""

import io
import logging
from typing import List, Optional, Union
from bson import ObjectId
from bson.errors import InvalidId
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse

from api.dependencies import get_current_user
from core.config import settings
from models.certificate import Certificate
from models.certificate_request import CertificateRequest
from models.enums import TipoCertificado
from models.student import Student
from models.user import User
from schemas.certificate import (
    CertificateEmitRequest,
    CertificateListResponse,
    CertificateOut,
    CertificateModuloOut,
)
from core.cloudinary_utils import upload_document
from schemas.certificate_request import (
    CertificateRequestAprobar,
    CertificateRequestCancelar,
    CertificateRequestConfirmarFirma,
    CertificateRequestCreate,
    CertificateRequestListResponse,
    CertificateRequestOut,
    CertificateRequestRechazar,
)
import services.certificate_service as certificate_service
import services.certificate_request_service as cert_request_service

logger = logging.getLogger(__name__)

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
    summary="[Staff] Emitir un certificado manualmente (sin solicitud)",
    description=(
        "Solo el STAFF puede usar este endpoint (cobranza, admin, superadmin, "
        "encargado de curso). Para que el estudiante obtenga un certificado "
        "por su cuenta, debe pasar por el flujo de solicitud: "
        "POST /certificates/requests/ → aprobación del encargado → "
        "descarga del PDF desde /certificates/{cert_id}/pdf.\n\n"
        "Este endpoint se mantiene para casos manuales del staff (p.ej. "
        "re-emisión de un cert rechazado, o emisión directa autorizada por "
        "la dirección).\n\n"
        "Para 'notas': requiere programa finalizado + saldo cero. "
        "Para 'no_deudor': requiere que los módulos 1..N estén todos pagados."
    ),
)
async def emit_certificate(
    payload: CertificateEmitRequest,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateOut:
    # F-CERT-APROBACION (2026-07-30): el estudiante YA NO puede emitir
    # directamente. Debe pasar por el flujo de solicitud /certificates/requests/.
    # Solo el staff puede emitir manualmente.
    if isinstance(current_user, Student):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Los estudiantes no pueden emitir certificados directamente. "
                "Crea una solicitud en POST /api/v1/certificates/requests/ y "
                "espera la aprobación del encargado del programa."
            ),
        )
    if current_user is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para emitir certificados.",
        )

    # BUG-FIX (2026-07-30): chequear ANTES de emitir si ya existe un cert
    # idéntico. Si existe, devolver 409 con el cert existente en vez de
    # re-emitir y provocar un DuplicateKeyError (500 Internal Server Error).
    # La unicidad está garantizada por el índice `uniq_enrollment_tipo` en
    # la colección de Certificate.
    existing = await _buscar_cert_duplicado(
        enrollment_id=payload.enrollment_id,
        tipo=payload.tipo,
        hasta_modulo_n=payload.hasta_modulo_n,
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ya existe un certificado de tipo '{payload.tipo}' emitido "
                f"para esta inscripción. Folio: {certificate_service._format_folio(existing.numero, existing.anio)}. "
                f"Puedes descargarlo desde la sección 'Certificados'."
            ),
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


# NOTA (2026-07-30): el pre-check de _buscar_cert_duplicado arriba cubre
# el caso común. Para defensa contra race conditions (dos requests
# simultáneos para el mismo enrollment+tipo), el índice único
# `uniq_enrollment_tipo` en la colección de Certificate lanza
# DuplicateKeyError, que se propaga como 500. Si el tráfico lo justifica
# se puede agregar un try/except DuplicateKeyError alrededor de las
# llamadas a emitir_certificado_*, pero con el pre-check la ventana
# de race condition es mínima.


# ========================================================================
# HELPER: manejo de duplicados
# ========================================================================

async def _buscar_cert_duplicado(
    enrollment_id: str, tipo: str, hasta_modulo_n: Optional[int] = None
) -> Optional[Certificate]:
    """
    Busca un certificado ya emitido para (enrollment, tipo) que coincida
    en el alcance. Útil para responder 409 con el cert existente en vez
    de re-emitir y provocar un DuplicateKeyError (500).

    Para 'notas' no se compara hasta_modulo_n (siempre es el cert final).
    Para 'no_deudor' se compara hasta_modulo_n — si ya hay uno emitido
    para el mismo alcance, es duplicado.
    """
    from beanie import PydanticObjectId

    try:
        eid = PydanticObjectId(enrollment_id)
    except Exception:
        return None

    query = Certificate.find(
        Certificate.enrollment_id == eid,
        Certificate.tipo == tipo,
    )
    if tipo == TipoCertificado.NO_DEUDOR and hasta_modulo_n is not None:
        query = query.find(Certificate.hasta_modulo_n == hasta_modulo_n)

    return await query.first_or_none()


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
        # F-2026-08-22-EC-CERTIFICADOS-READONLY (Kevin 2026-08-22): encargado_curso
        # tambien puede ver certificados de las inscripciones de SUS cursos.
        staff_roles = {"SUPERADMIN", "ADMIN", "CPD", "COBRANZA", "MAE", "COORDINADOR", "ENCARGADO_CURSO"}
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

    BUG-FIX (2026-07-30): removido import roto de STAFF_ROLES_HELPER que
    no existe en api.dependencies y rompía el endpoint con ImportError.
    La validación de staff roles ya se hace abajo con el set local.
    """
    if not isinstance(current_user, User):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta vista es solo para personal administrativo.",
        )
    # Verificar rol staff
    # F-2026-08-22-EC-CERTIFICADOS-READONLY (Kevin 2026-08-22): encargado_curso
    # tambien entra a este endpoint. El filtro de cursos_asignados de abajo
    # (via filtro_cursos_por_rol) se encarga de que SOLO vea los certificados
    # de SUS cursos asignados, igual que en pagos.
    from models.enums import UserRole
    staff_roles = {UserRole.ADMIN, UserRole.SUPERADMIN, UserRole.MAE,
                   UserRole.CPD, UserRole.COBRANZA, UserRole.COORDINADOR,
                   UserRole.ENCARGADO_CURSO}
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
    "/arancel-no-deudor",
    summary="Arancel vigente del Certificado de No Deudor",
    description=(
        "Devuelve cuánto cuesta hoy el Certificado de No Deudor "
        "(F-CERT-NO-DEUDOR-COBRO). Existe para que la pantalla del estudiante "
        "pueda mostrar el precio ANTES de que solicite, sin hardcodearlo: el "
        "monto vive en la config del servidor y es provisorio."
    ),
)
async def arancel_no_deudor(
    current_user: Union[Student, User] = Depends(get_current_user),
) -> dict:
    # OJO: esta ruta tiene que declararse ANTES de `/{cert_id}`, que es de un
    # solo segmento y si no se la comería como si "arancel-no-deudor" fuera
    # un id de certificado.
    return {
        "monto": settings.MONTO_CERTIFICADO_NO_DEUDOR,
        "moneda": "Bs",
    }


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

    # F-CERT-NO-DEUDOR-COBRO (2026-08-17): el estudiante no puede bajar el
    # Certificado de No Deudor hasta que se confirme la firma física. El
    # staff sí, porque es quien tiene que imprimirlo para hacerlo firmar.
    if isinstance(current_user, Student):
        motivo = await cert_request_service.motivo_bloqueo_descarga(cert)
        if motivo:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=motivo)

    # Descargar PDF desde Cloudinary (con fallback a re-render si falla)
    try:
        pdf_bytes = await certificate_service.descargar_pdf_bytes(cert)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"No se pudo recuperar el PDF ni re-renderizarlo: {str(e)}",
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


# ========================================================================
# F-CERT-APROBACION (2026-07-30): flujo de solicitud + aprobación
# ========================================================================
# Endpoints para que el estudiante SOLICITE un certificado y el encargado
# del programa (o admin/superadmin) lo APRUEBE. Al aprobar se emite el
# Certificate real (folio + PDF) y el estudiante puede descargarlo desde
# /certificates/{id}/pdf.
#
# Diseño:
#   POST   /certificates/requests/             -> estudiante crea solicitud
#   GET    /certificates/requests/my           -> estudiante ve las suyas
#   GET    /certificates/requests/             -> staff ve la cola
#   PATCH  /certificates/requests/{id}/in-review -> staff toma la solicitud
#   PATCH  /certificates/requests/{id}/approve -> staff aprueba (emite cert)
#   PATCH  /certificates/requests/{id}/reject  -> staff rechaza
#   PATCH  /certificates/requests/{id}/cancel  -> estudiante cancela
#   GET    /certificates/requests/stats        -> KPIs para panel staff
# ========================================================================


@router.post(
    "/requests/",
    response_model=CertificateRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Estudiante] Crear solicitud de certificado",
    description=(
        "El estudiante autenticado pide emisión de un certificado. La solicitud "
        "queda en estado 'pendiente' hasta que el encargado del programa la "
        "apruebe. Solo después de aprobada se emite el Certificate (folio + PDF) "
        "y el estudiante puede descargarlo."
    ),
)
async def crear_solicitud_certificado(
    data: CertificateRequestCreate,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo los estudiantes pueden crear solicitudes de certificado.",
        )
    req = await cert_request_service.crear_solicitud(data, current_user)
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.get(
    "/requests/my",
    response_model=List[CertificateRequestOut],
    summary="[Estudiante] Mis solicitudes de certificado",
)
async def listar_mis_solicitudes_cert(
    current_user: Union[Student, User] = Depends(get_current_user),
) -> List[CertificateRequestOut]:
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Este endpoint es solo para estudiantes.",
        )
    items = await cert_request_service.listar_mis_solicitudes(current_user)
    return [CertificateRequestOut(**cert_request_service._serializar_solicitud(r)) for r in items]


@router.get(
    "/requests/",
    response_model=CertificateRequestListResponse,
    summary="[Staff] Cola de solicitudes de certificado (filtrada por cursos_asignados)",
)
async def listar_cola_solicitudes_cert(
    estado: Optional[str] = Query(
        None,
        description="Filtrar por estado: pendiente | en_revision | aprobada | rechazada | cancelada",
    ),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestListResponse:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    items, total = await cert_request_service.listar_para_staff(
        current_user, estado=estado, page=page, per_page=per_page
    )
    return CertificateRequestListResponse(
        items=[CertificateRequestOut(**cert_request_service._serializar_solicitud(r)) for r in items],
        total=total,
    )


@router.get(
    "/requests/stats",
    summary="[Staff] Estadísticas de solicitudes (KPIs del panel)",
)
async def stats_solicitudes_cert(
    current_user: Union[Student, User] = Depends(get_current_user),
):
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    return await cert_request_service.obtener_estadisticas(current_user)


@router.patch(
    "/requests/{request_id}/in-review",
    response_model=CertificateRequestOut,
    summary="[Encargado] Marcar solicitud en revisión",
)
async def marcar_en_revision_solicitud_cert(
    request_id: str,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    req = await cert_request_service.marcar_en_revision(request_id, current_user)
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.patch(
    "/requests/{request_id}/approve",
    response_model=CertificateRequestOut,
    summary="[Encargado/Admin] Aprobar solicitud y emitir certificado",
    description=(
        "Al aprobar, se emite automáticamente el Certificate (con folio y PDF) "
        "y se enlaza a la solicitud. El estudiante puede descargarlo desde "
        "/certificates/{certificate_id}/pdf."
    ),
)
async def aprobar_solicitud_cert(
    request_id: str,
    data: Optional[CertificateRequestAprobar] = None,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    # El body es opcional para no romper a quien ya llamaba este endpoint sin
    # cuerpo (el flujo de certificado de Notas nunca lo necesitó).
    req = await cert_request_service.aprobar_solicitud(
        request_id, current_user, tratamiento=(data.tratamiento if data else None)
    )
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.patch(
    "/requests/{request_id}/confirmar-firma",
    response_model=CertificateRequestOut,
    summary="[Coordinador financiero/Superadmin] Confirmar la firma física y habilitar la descarga",
    description=(
        "Segundo paso de la aprobación del Certificado de No Deudor "
        "(F-CERT-NO-DEUDOR-COBRO, Kevin 2026-08-17). Aprobar ya emitió el PDF, "
        "pero el estudiante no puede descargarlo hasta que el coordinador haga "
        "firmar la copia física y lo habilite acá. Solo aplica a 'no_deudor': "
        "el certificado de Notas queda disponible apenas se aprueba."
    ),
)
async def confirmar_firma_fisica_cert(
    request_id: str,
    data: Optional[CertificateRequestConfirmarFirma] = None,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    req = await cert_request_service.confirmar_firma_fisica(
        request_id, current_user, observacion=(data.observacion if data else None)
    )
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.post(
    "/requests/{request_id}/comprobante",
    response_model=CertificateRequestOut,
    summary="[Estudiante] Adjuntar el comprobante de pago del arancel",
    description=(
        "El Certificado de No Deudor tiene arancel (F-CERT-NO-DEUDOR-COBRO). "
        "El estudiante sube acá el comprobante para que el coordinador lo vea "
        "junto a la solicitud. Se puede reemplazar mientras la solicitud siga "
        "pendiente o en revisión."
    ),
)
async def subir_comprobante_cert(
    request_id: str,
    archivo: UploadFile = File(..., description="Imagen o PDF del comprobante"),
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Solo el estudiante dueño de la solicitud puede subir el comprobante.",
        )
    try:
        url = await upload_document(file=archivo, folder="certificados-comprobantes")
    except Exception as e:
        raise HTTPException(
            status_code=502,
            detail=f"No se pudo subir el comprobante: {e}",
        )
    if not url:
        raise HTTPException(status_code=502, detail="No se pudo subir el comprobante.")

    req = await cert_request_service.adjuntar_comprobante(request_id, url, current_user)
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.patch(
    "/requests/{request_id}/reject",
    response_model=CertificateRequestOut,
    summary="[Encargado/Admin] Rechazar solicitud con motivo",
)
async def rechazar_solicitud_cert(
    request_id: str,
    data: CertificateRequestRechazar,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")
    req = await cert_request_service.rechazar_solicitud(request_id, data, current_user)
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))


@router.patch(
    "/requests/{request_id}/cancel",
    response_model=CertificateRequestOut,
    summary="[Estudiante] Cancelar mi solicitud (solo si está pendiente o en revisión)",
)
async def cancelar_solicitud_cert(
    request_id: str,
    data: CertificateRequestCancelar,
    current_user: Union[Student, User] = Depends(get_current_user),
) -> CertificateRequestOut:
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo el estudiante dueño puede cancelar.")
    req = await cert_request_service.cancelar_solicitud(request_id, data, current_user)
    return CertificateRequestOut(**cert_request_service._serializar_solicitud(req))
