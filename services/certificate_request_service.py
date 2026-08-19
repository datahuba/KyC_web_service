"""
Service de Solicitudes de Certificado
====================================

F-CERT-APROBACION (2026-07-30): máquina de estados para solicitudes de
certificado de Notas / No Deudor. El estudiante crea la solicitud, el
encargado del programa (o admin/superadmin) la aprueba, y al aprobar
se emite el Certificate real.

Estados:
  pendiente → en_revision → aprobada | rechazada | cancelada
  aprobada es terminal (tiene certificate_id != null)
  rechazada puede re-solicitarse (se permite crear nueva solicitud)
  cancelada es terminal
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple, Union

from beanie import PydanticObjectId
from bson import ObjectId
from fastapi import HTTPException, status

from core.config import settings
from models.certificate import Certificate
from models.certificate_request import CertificateRequest
from models.course import Course
from models.enrollment import Enrollment
from models.enums import EstadoTramite, TipoCertificado, UserRole
from models.student import Student
from models.user import User
from schemas.certificate_request import (
    CertificateRequestCancelar,
    CertificateRequestCreate,
    CertificateRequestRechazar,
)
import services.certificate_service as certificate_service

logger = logging.getLogger(__name__)


# ========================================================================
# RBAC
# ========================================================================

def es_coordinador_financiero(user: User) -> bool:
    """
    True si el usuario es COORDINADOR con subtipo 'financiero'.

    El subtipo puede venir como enum o como string plano segun de donde se
    haya cargado el documento, asi que se compara sobre el valor.
    """
    if not isinstance(user, User):
        return False
    if user.rol != UserRole.COORDINADOR:
        return False
    subtipo = getattr(user, "subtipo_coordinador", None)
    return str(getattr(subtipo, "value", subtipo) or "").lower() == "financiero"


def puede_aprobar_solicitud_cert(
    user: User,
    course_id: PydanticObjectId,
    tipo: Optional[str] = None,
) -> bool:
    """
    Devuelve True si el usuario puede APROBAR/RECHAZAR/REVISAR solicitudes
    de certificado del programa course_id.

    Certificado de NOTAS (regla original, Kevin 2026-07-30):
    - ADMIN, SUPERADMIN: pueden aprobar CUALQUIER solicitud (backup)
    - ENCARGADO_CURSO: solo si course_id está en sus cursos_asignados
    - CPD, COORDINADOR, MAE, COBRANZA: NO pueden aprobar

    Certificado de NO DEUDOR (F-CERT-NO-DEUDOR-COBRO, Kevin 2026-08-17):
    - SUPERADMIN y COORDINADOR FINANCIERO, y nadie más.

    El cambio es a proposito mas restrictivo que el flujo de notas: este
    certificado ahora acredita que no hay deuda Y cobra un arancel, o sea
    que es una decision economica. Kevin fue explicito con quienes la toman
    ("Coordinador financiero + superadmin"), asi que el encargado de curso y
    el admin quedan afuera aunque puedan aprobar certificados de notas.

    `tipo` es opcional para no romper a los llamadores viejos: sin tipo se
    asume el flujo de notas, que es el que existia antes.
    """
    if not isinstance(user, User):
        return False

    if tipo == "no_deudor":
        if user.rol == UserRole.SUPERADMIN:
            return True
        return es_coordinador_financiero(user)

    if user.rol in (UserRole.ADMIN, UserRole.SUPERADMIN):
        return True
    if user.rol == UserRole.ENCARGADO_CURSO:
        return course_id in (user.cursos_asignados or [])
    return False


def puede_ver_cola_solicitudes_cert(user: User) -> bool:
    """
    Devuelve True si el usuario puede VER la cola de solicitudes de certificados
    (panel del encargado). Aunque no pueda aprobar (p.ej. CPD), puede ver
    para fines de auditoría.
    """
    if not isinstance(user, User):
        return False
    return user.rol in (
        UserRole.ADMIN,
        UserRole.SUPERADMIN,
        UserRole.ENCARGADO_CURSO,
        UserRole.CPD,
        UserRole.COORDINADOR,
        UserRole.MAE,
    )


def _filtro_cursos_cola_cert(user: User) -> Optional[dict]:
    """
    Filtro Mongo para limitar la cola de solicitudes al alcance del usuario.
    None = ve TODAS las solicitudes (admin/superadmin/CPD/coordinador/MAE).
    dict = filtra por course_id in cursos_asignados (encargado_curso).
    """
    if user.rol == UserRole.ENCARGADO_CURSO:
        if not user.cursos_asignados:
            # Encargado sin cursos asignados: ve solo las del curso
            # None, lo cual no devolverá nada. Mejor devolver un filtro
            # que explícitamente NO matchea nada.
            return {"course_id": {"$in": []}}
        return {"course_id": {"$in": [str(c) for c in user.cursos_asignados]}}
    return None  # admin/superadmin/etc: ve todo


# ========================================================================
# HELPERS
# ========================================================================

def es_descargable(req: CertificateRequest) -> bool:
    """
    Si el estudiante ya puede bajarse el PDF.

    Notas: alcanza con que este aprobada y tenga certificado emitido.
    No deudor: ademas hace falta la confirmacion de la firma fisica
    (F-CERT-NO-DEUDOR-COBRO). Kevin: "el coordinador hace firmar la copia
    fisica y debe habilitar o aprobar al estudiante para que lo tenga".
    """
    if req.estado != EstadoTramite.APROBADA or not req.certificate_id:
        return False
    if req.tipo == TipoCertificado.NO_DEUDOR:
        return bool(req.firma_fisica_confirmada)
    return True


async def motivo_bloqueo_descarga(cert: Certificate) -> Optional[str]:
    """
    Devuelve el motivo por el que un ESTUDIANTE todavía no puede descargar
    este certificado, o None si puede.

    F-CERT-NO-DEUDOR-COBRO (2026-08-17): el Certificado de No Deudor se emite
    al aprobar, pero el estudiante no lo ve hasta que el coordinador confirma
    que la copia física está firmada. Sin este chequeo el segundo paso sería
    decorativo: el PDF ya existe y el estudiante podría bajárselo igual.

    Los certificados emitidos a mano por el staff (`POST /certificates/emit`)
    no tienen solicitud asociada y no se bloquean: ahí el staff ya decidió.
    """
    if cert.tipo != TipoCertificado.NO_DEUDOR:
        return None

    req = await CertificateRequest.find_one({"certificate_id": cert.id})
    if not req:
        return None
    if req.firma_fisica_confirmada:
        return None
    return (
        "Tu certificado ya fue aprobado, pero todavía no está habilitado para "
        "descarga: el coordinador tiene que hacer firmar la copia física primero. "
        "Te avisamos apenas esté lista."
    )


def _serializar_solicitud(req: CertificateRequest) -> dict:
    """Convierte un CertificateRequest (Beanie doc) a dict para CertificateRequestOut."""
    return {
        "monto": req.monto,
        "comprobante_url": req.comprobante_url,
        "tratamiento": req.tratamiento,
        "firma_fisica_confirmada": bool(req.firma_fisica_confirmada),
        "fecha_firma_fisica": req.fecha_firma_fisica,
        "confirmada_por": req.confirmada_por,
        "observacion_firma": req.observacion_firma,
        "descargable": es_descargable(req),
        "id": str(req.id),
        "tipo": req.tipo,
        "estado": req.estado,
        "estudiante_id": str(req.estudiante_id),
        "enrollment_id": str(req.enrollment_id),
        "course_id": str(req.course_id),
        "hasta_modulo_n": req.hasta_modulo_n,
        "nombre_completo": req.nombre_completo,
        "programa_nombre": req.programa_nombre,
        "programa_codigo": req.programa_codigo,
        "motivo": req.motivo,
        "fecha_revision": req.fecha_revision,
        "revisado_por": req.revisado_por,
        "motivo_rechazo": req.motivo_rechazo,
        "motivo_cancelacion": req.motivo_cancelacion,
        "fecha_cancelacion": req.fecha_cancelacion,
        "certificate_id": str(req.certificate_id) if req.certificate_id else None,
        "created_at": req.created_at,
        "updated_at": req.updated_at,
    }


# ========================================================================
# ESTUDIANTE: crear / listar / cancelar
# ========================================================================

async def crear_solicitud(
    data: CertificateRequestCreate,
    current_user: Student,
) -> CertificateRequest:
    """
    El estudiante autenticado crea una solicitud de certificado.

    Validaciones:
    - current_user debe ser un Student
    - El enrollment debe existir y pertenecer al estudiante
    - El course del enrollment debe existir
    - No debe haber una solicitud ACTIVA (pendiente o en_revision) para el
      mismo (enrollment, tipo, hasta_modulo_n)
    """
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los estudiantes pueden crear solicitudes de certificado.",
        )

    # 1. Cargar enrollment
    try:
        eid = PydanticObjectId(data.enrollment_id)
    except Exception:
        raise HTTPException(status_code=400, detail="enrollment_id inválido.")

    enrollment = await Enrollment.get(eid)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripción no encontrada.")

    if enrollment.estudiante_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="Esta inscripción no te pertenece.",
        )

    # 2. Cargar curso (para snapshot de nombre/código y para validar derechos)
    course = await Course.get(enrollment.curso_id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso del enrollment no encontrado.")

    # 3. Si es no_deudor, validar hasta_modulo_n
    if data.tipo == TipoCertificado.NO_DEUDOR and data.hasta_modulo_n is None:
        raise HTTPException(
            status_code=422,
            detail="Para 'no_deudor' debes indicar 'hasta_modulo_n' (1..N).",
        )
    if data.tipo == TipoCertificado.NOTAS and data.hasta_modulo_n is not None:
        raise HTTPException(
            status_code=422,
            detail="Para 'notas' NO se debe enviar 'hasta_modulo_n'.",
        )

    # 4. Verificar que no haya solicitud ACTIVA para el mismo (enrollment, tipo, hasta_modulo_n)
    query = {
        "enrollment_id": eid,
        "tipo": data.tipo,
        "estado": {"$in": [EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION]},
    }
    if data.hasta_modulo_n is not None:
        query["hasta_modulo_n"] = data.hasta_modulo_n

    existing = await CertificateRequest.find_one(query)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Ya tienes una solicitud de certificado '{data.tipo}' en estado "
                f"'{existing.estado}' para esta inscripción. "
                f"Espera a que sea revisada o cancélala antes de crear una nueva."
            ),
        )

    # 5. Crear la solicitud
    #
    # F-CERT-NO-DEUDOR-COBRO (2026-08-17): el arancel se guarda como SNAPSHOT
    # en la solicitud, no se lee de config al momento de cobrar. Si Kevin
    # cambia el monto (hoy Bs 150, provisorio), las solicitudes ya creadas
    # conservan el que se le informó al estudiante cuando la hizo.
    monto = settings.MONTO_CERTIFICADO_NO_DEUDOR if data.tipo == TipoCertificado.NO_DEUDOR else None

    # F-CERT-COMPROBANTE-OBLIGATORIO (2026-08-18, Kevin): sin comprobante no
    # se envia la solicitud. Textual: "hay que solicitar obviamente el
    # comprobante al estudiante. Una vez sube el comprobante, recien se pueda
    # dejar enviar la solicitud".
    #
    # Se bloquea el ENVIO y no la aprobacion a proposito. Bloquear la
    # aprobacion dejaba sin camino al cobro en ventanilla: el estudiante paga
    # en caja, no tiene comprobante digital, y el coordinador no podia aprobar
    # aunque le constara el pago. Exigirlo al enviar no tiene ese problema:
    # el alumno le saca una foto a su recibo de caja igual.
    #
    # Solo aplica a 'no_deudor', el unico tipo con arancel.
    if data.tipo == TipoCertificado.NO_DEUDOR and not (data.comprobante_url or "").strip():
        raise HTTPException(
            status_code=422,
            detail=(
                f"Para solicitar el Certificado de No Deudor tenes que adjuntar "
                f"el comprobante del pago del arancel (Bs {monto:g}). Si pagaste "
                f"en caja, sirve una foto del recibo."
            ),
        )

    req = CertificateRequest(
        tipo=data.tipo,
        estudiante_id=current_user.id,
        enrollment_id=eid,
        course_id=enrollment.curso_id,
        hasta_modulo_n=data.hasta_modulo_n,
        nombre_completo=current_user.nombre or "",
        programa_nombre=course.nombre_programa or "",
        programa_codigo=course.codigo or "",
        motivo=data.motivo,
        estado=EstadoTramite.PENDIENTE,
        monto=monto,
        comprobante_url=(data.comprobante_url or "").strip() or None,
    )
    await req.save()
    logger.info(
        f"[CERT-REQ] Solicitud creada: id={req.id} tipo={req.tipo} "
        f"estudiante={current_user.id} enrollment={eid}"
    )
    return req


async def listar_mis_solicitudes(current_user: Student) -> List[CertificateRequest]:
    """Lista las solicitudes del estudiante autenticado, más recientes primero."""
    if not isinstance(current_user, Student):
        raise HTTPException(
            status_code=403,
            detail="Este endpoint es solo para estudiantes.",
        )
    return (
        await CertificateRequest.find(CertificateRequest.estudiante_id == current_user.id)
        .sort("-created_at")
        .to_list()
    )


async def cancelar_solicitud(
    request_id: str,
    data: CertificateRequestCancelar,
    current_user: Student,
) -> CertificateRequest:
    """El estudiante dueño cancela su solicitud (solo si está pendiente o en_revision)."""
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo el estudiante dueño puede cancelar.")

    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if req.estudiante_id != current_user.id:
        raise HTTPException(status_code=403, detail="Esta solicitud no es tuya.")

    if req.estado not in (EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION):
        raise HTTPException(
            status_code=409,
            detail=f"Solo se pueden cancelar solicitudes en estado 'pendiente' o 'en_revision'. "
                   f"Esta solicitud está '{req.estado}'.",
        )

    req.estado = EstadoTramite.CANCELADA
    req.motivo_cancelacion = data.motivo_cancelacion
    req.fecha_cancelacion = datetime.utcnow()
    await req.save()
    return req


# ========================================================================
# STAFF: cola, aprobar, rechazar, en revisión
# ========================================================================

async def listar_para_staff(
    current_user: User,
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Tuple[List[CertificateRequest], int]:
    """
    Lista solicitudes de certificado para la cola del staff.

    - ADMIN/SUPERADMIN/CPD/COORDINADOR/MAE: ven TODAS (filtradas opcionalmente por estado)
    - ENCARGADO_CURSO: solo las de sus cursos_asignados
    """
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado puede ver la cola.")

    if not puede_ver_cola_solicitudes_cert(current_user):
        raise HTTPException(status_code=403, detail="No tienes permiso para ver solicitudes.")

    query = {}
    if estado:
        query["estado"] = estado

    # Filtro por cursos_asignados del encargado
    filtro_cursos = _filtro_cursos_cola_cert(current_user)
    if filtro_cursos:
        # Si el user ya puso un filtro de course_id, hacer AND
        if "course_id" in query:
            # Intersección: el user pidió un curso específico Y solo puede ver los suyos
            user_courses = filtro_cursos["course_id"]["$in"]
            query["course_id"] = {"$in": [c for c in [query["course_id"]] if c in user_courses]}
        else:
            query.update(filtro_cursos)

    total = await CertificateRequest.find(query).count()
    skip = (page - 1) * per_page
    items = (
        await CertificateRequest.find(query)
        .sort("-created_at")
        .skip(skip)
        .limit(per_page)
        .to_list()
    )
    return items, total


async def marcar_en_revision(
    request_id: str,
    current_user: User,
) -> CertificateRequest:
    """Encargado/admin marca la solicitud como 'en_revision' (tomó la solicitud para revisarla)."""
    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if not puede_aprobar_solicitud_cert(current_user, req.course_id, req.tipo):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para revisar solicitudes de este programa.",
        )

    if req.estado not in (EstadoTramite.PENDIENTE,):
        raise HTTPException(
            status_code=409,
            detail=f"Solo se pueden marcar en revisión solicitudes en estado 'pendiente'. "
                   f"Esta solicitud está '{req.estado}'.",
        )

    req.estado = EstadoTramite.EN_REVISION
    req.revisado_por = current_user.username
    await req.save()
    return req


async def aprobar_solicitud(
    request_id: str,
    current_user: User,
    tratamiento: Optional[str] = None,
) -> CertificateRequest:
    """
    Aprueba la solicitud y emite el Certificate real con su folio y PDF.

    Certificado de NOTAS: lo aprueba el encargado del programa, admin o
    superadmin, y con eso el estudiante ya puede descargarlo.

    Certificado de NO DEUDOR (F-CERT-NO-DEUDOR-COBRO, 2026-08-17): lo aprueba
    el coordinador financiero o el superadmin, y aprobar NO alcanza para que
    el estudiante lo descargue — falta que se confirme la firma física
    (`confirmar_firma_fisica`). El `tratamiento` que se pase acá es el que se
    imprime antes del nombre en el PDF.
    """
    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if not puede_aprobar_solicitud_cert(current_user, req.course_id, req.tipo):
        if req.tipo == TipoCertificado.NO_DEUDOR:
            raise HTTPException(
                status_code=403,
                detail="El Certificado de No Deudor solo lo aprueban el coordinador "
                       "financiero o el superadmin.",
            )
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para aprobar solicitudes de este programa. "
                   "Solo el encargado del programa, admin o superadmin pueden aprobar.",
        )

    if tratamiento is not None:
        req.tratamiento = tratamiento

    if req.estado not in (EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION):
        raise HTTPException(
            status_code=409,
            detail=f"Solo se pueden aprobar solicitudes en estado 'pendiente' o 'en_revision'. "
                   f"Esta solicitud está '{req.estado}'.",
        )

    # Pre-check: si ya hay un Certificate emitido para este (enrollment, tipo, hasta_modulo_n),
    # no duplicamos. Devolvemos 409 con la información del cert existente.
    existing_cert = await certificate_service._buscar_cert_duplicado(
        enrollment_id=str(req.enrollment_id),
        tipo=req.tipo,
        hasta_modulo_n=req.hasta_modulo_n,
    )
    if existing_cert:
        # Enlazar el cert existente a la solicitud y aprobarla de todas formas
        req.certificate_id = existing_cert.id
        req.estado = EstadoTramite.APROBADA
        req.fecha_revision = datetime.utcnow()
        req.revisado_por = current_user.username
        await req.save()
        return req

    # Emitir el Certificate (reutiliza el flujo actual de certificate_service)
    try:
        if req.tipo == TipoCertificado.NOTAS:
            cert = await certificate_service.emitir_certificado_notas(
                enrollment_id=str(req.enrollment_id),
                current_user=current_user,
            )
        else:  # no_deudor
            cert = await certificate_service.emitir_certificado_no_deudor(
                enrollment_id=str(req.enrollment_id),
                hasta_modulo_n=req.hasta_modulo_n,
                current_user=current_user,
                tratamiento=req.tratamiento,
            )
    except ValueError as e:
        # Error de validación de requisitos (no cumple para emitir)
        # Devolvemos 422 con el motivo para que el encargado sepa
        logger.warning(
            f"[CERT-REQ] Aprobación fallida por requisitos no cumplidos: "
            f"request={req.id} error={e}"
        )
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception(f"[CERT-REQ] Error al emitir cert al aprobar solicitud {req.id}")
        raise HTTPException(
            status_code=500,
            detail=f"Error al emitir el certificado: {str(e)}",
        )

    req.certificate_id = cert.id
    req.estado = EstadoTramite.APROBADA
    req.fecha_revision = datetime.utcnow()
    req.revisado_por = current_user.username
    await req.save()
    logger.info(
        f"[CERT-REQ] Solicitud aprobada: request={req.id} cert={cert.id} "
        f"por={current_user.username}"
    )
    return req


async def adjuntar_comprobante(
    request_id: str,
    comprobante_url: str,
    current_user: Student,
) -> CertificateRequest:
    """
    El estudiante adjunta el comprobante de pago del arancel a su solicitud.

    F-CERT-NO-DEUDOR-COBRO (2026-08-17). Se permite reemplazarlo mientras la
    solicitud siga abierta: si subió el archivo equivocado tiene que poder
    corregirlo sin cancelar y volver a empezar.
    """
    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if not isinstance(current_user, Student) or req.estudiante_id != current_user.id:
        raise HTTPException(status_code=403, detail="Esta solicitud no te pertenece.")

    if req.estado not in (EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION):
        raise HTTPException(
            status_code=409,
            detail=f"Solo se puede adjuntar el comprobante mientras la solicitud está "
                   f"pendiente o en revisión. Esta está '{req.estado}'.",
        )

    req.comprobante_url = comprobante_url
    await req.save()
    logger.info(f"[CERT-REQ] Comprobante adjuntado: request={req.id}")
    return req


async def confirmar_firma_fisica(
    request_id: str,
    current_user: User,
    observacion: Optional[str] = None,
) -> CertificateRequest:
    """
    Segundo paso de la aprobación del Certificado de No Deudor.

    F-CERT-NO-DEUDOR-COBRO (2026-08-17). Kevin: "cuando llega al coordinador,
    el coordinador hace firmar la copia física y debe habilitar o aprobar al
    estudiante para que lo tenga".

    Aprobar ya emitió el PDF, pero el estudiante no lo ve hasta acá. La
    razón es que el documento que vale es el firmado en papel: si el
    estudiante pudiera bajarse el digital antes, tendría en la mano un
    certificado que todavía nadie firmó.
    """
    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if req.tipo != TipoCertificado.NO_DEUDOR:
        raise HTTPException(
            status_code=409,
            detail="La confirmación de firma física solo aplica al Certificado de No Deudor. "
                   "El de Notas queda disponible apenas se aprueba.",
        )

    if not puede_aprobar_solicitud_cert(current_user, req.course_id, req.tipo):
        raise HTTPException(
            status_code=403,
            detail="Solo el coordinador financiero o el superadmin pueden confirmar "
                   "la firma física.",
        )

    if req.estado != EstadoTramite.APROBADA:
        raise HTTPException(
            status_code=409,
            detail=f"Primero hay que aprobar la solicitud. Esta está '{req.estado}'.",
        )

    if req.firma_fisica_confirmada:
        raise HTTPException(
            status_code=409,
            detail="La firma física de esta solicitud ya estaba confirmada.",
        )

    req.firma_fisica_confirmada = True
    req.fecha_firma_fisica = datetime.now(timezone.utc)
    req.confirmada_por = current_user.username
    if observacion and observacion.strip():
        req.observacion_firma = observacion.strip()
    await req.save()
    logger.info(
        f"[CERT-REQ] Firma física confirmada: request={req.id} "
        f"por={current_user.username}"
    )
    return req


async def rechazar_solicitud(
    request_id: str,
    data: CertificateRequestRechazar,
    current_user: User,
) -> CertificateRequest:
    """Encargado/admin rechaza la solicitud con un motivo obligatorio."""
    try:
        rid = PydanticObjectId(request_id)
    except Exception:
        raise HTTPException(status_code=400, detail="request_id inválido.")

    req = await CertificateRequest.get(rid)
    if not req:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada.")

    if not puede_aprobar_solicitud_cert(current_user, req.course_id, req.tipo):
        raise HTTPException(
            status_code=403,
            detail="No tienes permiso para rechazar solicitudes de este programa.",
        )

    if req.estado not in (EstadoTramite.PENDIENTE, EstadoTramite.EN_REVISION):
        raise HTTPException(
            status_code=409,
            detail=f"Solo se pueden rechazar solicitudes en estado 'pendiente' o 'en_revision'. "
                   f"Esta solicitud está '{req.estado}'.",
        )

    req.estado = EstadoTramite.RECHAZADA
    req.motivo_rechazo = data.motivo_rechazo
    req.fecha_revision = datetime.utcnow()
    req.revisado_por = current_user.username
    await req.save()
    return req


# ========================================================================
# ESTADÍSTICAS (panel del encargado)
# ========================================================================

async def obtener_estadisticas(current_user: User) -> dict:
    """KPIs simples para el panel del encargado."""
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo personal autorizado.")

    filtro_cursos = _filtro_cursos_cola_cert(current_user)

    base_query = filtro_cursos or {}

    pendientes = await CertificateRequest.find(
        {**base_query, "estado": EstadoTramite.PENDIENTE}
    ).count()
    en_revision = await CertificateRequest.find(
        {**base_query, "estado": EstadoTramite.EN_REVISION}
    ).count()

    # Aprobadas y rechazadas HOY
    from datetime import timedelta
    inicio_hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    fin_hoy = inicio_hoy + timedelta(days=1)
    aprobadas_hoy = await CertificateRequest.find(
        {
            **base_query,
            "estado": EstadoTramite.APROBADA,
            "fecha_revision": {"$gte": inicio_hoy, "$lt": fin_hoy},
        }
    ).count()
    rechazadas_hoy = await CertificateRequest.find(
        {
            **base_query,
            "estado": EstadoTramite.RECHAZADA,
            "fecha_revision": {"$gte": inicio_hoy, "$lt": fin_hoy},
        }
    ).count()

    return {
        "pendientes": pendientes,
        "en_revision": en_revision,
        "aprobadas_hoy": aprobadas_hoy,
        "rechazadas_hoy": rechazadas_hoy,
        "total_pendientes": pendientes + en_revision,
    }
