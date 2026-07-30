"""
Servicio de Solicitudes de Trámite
===================================

F-TRAMITES-SOLICITUD (2026-07-29): lógica de negocio de las solicitudes que
el estudiante crea desde /app/requests (Convalidación, Tutoría, Readmisión,
Titulación).

El servicio NO maneja HTTP — eso es responsabilidad del router. Aquí vive:
  - Validación de transición de estado (solo estudiante puede cancelar,
    solo staff puede aprobar/rechazar, etc.).
  - Reglas de archivos adjuntos por tipo (definidas en el schema).
  - Queries segmentadas por rol (encargado de curso solo ve las de sus cursos).
"""

from datetime import datetime, timezone
from typing import List, Optional, Tuple

from beanie import PydanticObjectId
from fastapi import HTTPException, status

from models.enums import EstadoTramite, TipoTramite, UserRole
from models.student import Student
from models.tramite_solicitud import ArchivoAdjunto, TramiteSolicitud
from models.user import User
from schemas.tramite_solicitud import (
    ARCHIVOS_REQUERIDOS_POR_TIPO,
    TramiteEstadisticas,
    TramiteSolicitudCreate,
)
from core.timezone_utils import utcnow_naive


# Roles con permiso para revisar / aprobar / rechazar solicitudes.
# Excluimos 'student' y 'docente' del staff de revisión (los estudiantes
# no se revisan sus propias solicitudes, y los docentes no tienen
# competencia administrativa sobre estos trámites).
STAFF_ROLES_REVISION = {
    UserRole.CPD,
    UserRole.ADMIN,
    UserRole.SUPERADMIN,
    UserRole.MAE,
    UserRole.COORDINADOR,
    UserRole.COBRANZA,
    UserRole.ENCARGADO_CURSO,
}


def _es_staff_revision(user: User) -> bool:
    """True si el user puede listar/aprobar/rechazar solicitudes."""
    # KYC DataHub: el campo en el modelo User es 'rol' (no 'role')
    return getattr(user, "rol", None) in STAFF_ROLES_REVISION


def _puede_aprobar_esta_solicitud(user: User, sol: TramiteSolicitud) -> bool:
    """
    F-CERT-APROBACION (2026-07-30): valida que el user pueda aprobar/rechazar
    ESTA solicitud específica.

    Reglas (Kevin 2026-07-30):
    - ADMIN, SUPERADMIN: aprueban cualquier solicitud
    - ENCARGADO_CURSO: solo si el course_id de la solicitud está en sus
      cursos_asignados
    - Resto de staff (CPD, MAE, COORDINADOR, COBRANZA): NO aprueban; solo
      figuran en la lista para auditoría. Si la solicitud es antigua y no
      tiene course_id, se permite aprobar (compatibilidad).
    """
    if user.rol in (UserRole.ADMIN, UserRole.SUPERADMIN):
        return True
    if user.rol == UserRole.ENCARGADO_CURSO:
        if not sol.course_id:
            # Solicitud sin course_id (antigua): no podemos filtrar, mejor
            # bloquear para mantener la regla. Admin/superadmin pueden
            # aprobarla si quieren.
            return False
        return sol.course_id in (user.cursos_asignados or [])
    return False


def _to_archivo_adjunto(archivo_dict: dict) -> ArchivoAdjunto:
    """Construye un ArchivoAdjunto desde el dict del request."""
    return ArchivoAdjunto(
        nombre_campo=archivo_dict["nombre_campo"],
        url=archivo_dict["url"],
        nombre_archivo=archivo_dict.get("nombre_archivo"),
        mime_type=archivo_dict.get("mime_type"),
    )


async def crear_solicitud(
    data: TramiteSolicitudCreate,
    estudiante: Student,
) -> TramiteSolicitud:
    """
    Crea una solicitud de trámite para el estudiante autenticado.
    Valida que el tipo sea válido y que los archivos requeridos estén presentes.
    """
    archivos = [_to_archivo_adjunto(a.model_dump()) for a in data.archivos]

    enrollment_id = None
    course_id = None  # F-CERT-APROBACION (2026-07-30): se setea desde el enrollment
    if data.enrollment_id:
        try:
            enrollment_id = PydanticObjectId(data.enrollment_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="enrollment_id inválido",
            )
        # Cargar el enrollment para denormalizar course_id (filtro del encargado)
        from models.enrollment import Enrollment
        enrollment = await Enrollment.get(enrollment_id)
        if enrollment:
            course_id = enrollment.curso_id

    sol = TramiteSolicitud(
        tipo=data.tipo.value,
        estudiante_id=estudiante.id,
        enrollment_id=enrollment_id,
        course_id=course_id,
        nombre_completo=data.nombre_completo,
        ci=data.ci,
        email=data.email,
        telefono=data.telefono,
        motivo=data.motivo,
        programa_relacionado=data.programa_relacionado,
        modulos_relacionados=data.modulos_relacionados or [],
        monto_pago_bs=data.monto_pago_bs,
        archivos=archivos,
        estado=EstadoTramite.PENDIENTE.value,
    )
    await sol.insert()
    return sol


async def listar_mis_solicitudes(estudiante: Student) -> List[TramiteSolicitud]:
    """Lista las solicitudes del estudiante autenticado, ordenadas por fecha desc."""
    return (
        await TramiteSolicitud.find(TramiteSolicitud.estudiante_id == estudiante.id)
        .sort([("created_at", -1)])
        .to_list()
    )


async def listar_todas(
    current_user: User,
    *,
    page: int = 1,
    per_page: int = 20,
    tipo: Optional[TipoTramite] = None,
    estado: Optional[EstadoTramite] = None,
    solo_mias: bool = False,
    estudiante_id: Optional[str] = None,
) -> Tuple[List[TramiteSolicitud], int]:
    """
    Lista solicitudes con paginación y filtros.
    - current_user: usuario autenticado (debe ser staff).
    - Si current_user es 'encargado_curso' con cursos_asignados, filtra
      solicitudes cuyo enrollment pertenezca a esos cursos. Si no tiene
      cursos_asignados, ve TODO (compatibilidad con encargados sin asignar).
    - tipo: filtro por tipo (convalidacion, tutoria, etc.).
    - estado: filtro por estado.
    - solo_mias: si True, filtra por current_user (sirve para un coordinador
      que quiere ver las que él registró, no las del equipo). No se usa
      actualmente en la UI pero queda para futuro.
    - estudiante_id: filtro por estudiante específico.
    """
    if not _es_staff_revision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para listar solicitudes de otros estudiantes.",
        )

    query: dict = {}
    if tipo:
        query["tipo"] = tipo.value
    if estado:
        query["estado"] = estado.value
    if estudiante_id:
        try:
            query["estudiante_id"] = PydanticObjectId(estudiante_id)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="estudiante_id inválido",
            )

    # F-CERT-APROBACION (2026-07-30): segmentación por cursos_asignados del
    # encargado. Si es ENCARGADO_CURSO y tiene cursos_asignados, filtra las
    # solicitudes cuyo course_id esté en esa lista. Si no tiene cursos
    # asignados, ve TODO (compatibilidad con encargados sin asignar). Los
    # demás roles (admin, superadmin, CPD, MAE, coordinador, cobranza) ven
    # TODO sin filtro.
    if (
        current_user.rol == UserRole.ENCARGADO_CURSO
        and current_user.cursos_asignados
    ):
        cursos_permitidos = [str(c) for c in current_user.cursos_asignados]
        if "course_id" in query:
            # Si el user ya filtró por course_id, intersectar
            user_courses = query["course_id"].get("$in", []) if isinstance(query["course_id"], dict) else [query["course_id"]]
            query["course_id"] = {"$in": [c for c in user_courses if c in cursos_permitidos]}
        else:
            query["course_id"] = {"$in": cursos_permitidos}

    total = await TramiteSolicitud.find(query).count()

    skip = (page - 1) * per_page
    items = (
        await TramiteSolicitud.find(query)
        .sort([("created_at", -1)])
        .skip(skip)
        .limit(per_page)
        .to_list()
    )
    return items, total


async def obtener_solicitud(
    solicitud_id: str, current_user: Optional[User] = None, estudiante: Optional[Student] = None
) -> TramiteSolicitud:
    """
    Obtiene una solicitud por ID.
    - Si es staff: puede ver cualquiera.
    - Si es estudiante: solo puede ver las suyas.
    """
    try:
        sid = PydanticObjectId(solicitud_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ID de solicitud inválido",
        )
    sol = await TramiteSolicitud.get(sid)
    if not sol:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Solicitud no encontrada",
        )

    if estudiante and sol.estudiante_id != estudiante.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver esta solicitud.",
        )
    return sol


async def aprobar_solicitud(solicitud_id: str, current_user: User) -> TramiteSolicitud:
    """Aprueba una solicitud pendiente o en revisión."""
    if not _es_staff_revision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para aprobar solicitudes.",
        )

    sol = await obtener_solicitud(solicitud_id)
    # F-CERT-APROBACION (2026-07-30): validar permiso granular (encargado del
    # programa o admin/superadmin). El resto de staff (CPD/MAE/coordinador/
    # cobranza) NO aprueba, solo ve.
    if not _puede_aprobar_esta_solicitud(current_user, sol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "No tienes permiso para aprobar esta solicitud. "
                "Solo el encargado del programa, admin o superadmin pueden aprobarla."
            ),
        )
    if sol.estado in {EstadoTramite.APROBADA.value, EstadoTramite.RECHAZADA.value, EstadoTramite.CANCELADA.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede aprobar una solicitud en estado '{sol.estado}'.",
        )

    sol.estado = EstadoTramite.APROBADA.value
    sol.fecha_revision = utcnow_naive()
    sol.revisado_por = current_user.username
    sol.motivo_rechazo = None
    await sol.save()
    return sol


async def rechazar_solicitud(
    solicitud_id: str, current_user: User, motivo: str
) -> TramiteSolicitud:
    """Rechaza una solicitud pendiente o en revisión."""
    if not _es_staff_revision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para rechazar solicitudes.",
        )

    sol = await obtener_solicitud(solicitud_id)
    # F-CERT-APROBACION (2026-07-30): mismo permiso granular que aprobar.
    if not _puede_aprobar_esta_solicitud(current_user, sol):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "No tienes permiso para rechazar esta solicitud. "
                "Solo el encargado del programa, admin o superadmin pueden rechazarla."
            ),
        )
    if sol.estado in {EstadoTramite.APROBADA.value, EstadoTramite.RECHAZADA.value, EstadoTramite.CANCELADA.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No se puede rechazar una solicitud en estado '{sol.estado}'.",
        )

    sol.estado = EstadoTramite.RECHAZADA.value
    sol.fecha_revision = utcnow_naive()
    sol.revisado_por = current_user.username
    sol.motivo_rechazo = motivo
    await sol.save()
    return sol


async def marcar_en_revision(solicitud_id: str, current_user: User) -> TramiteSolicitud:
    """Marca una solicitud como 'en_revision' (staff la está revisando)."""
    if not _es_staff_revision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para revisar solicitudes.",
        )

    sol = await obtener_solicitud(solicitud_id)
    if sol.estado != EstadoTramite.PENDIENTE.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Solo se pueden marcar en revisión las solicitudes pendientes. Estado actual: '{sol.estado}'.",
        )
    sol.estado = EstadoTramite.EN_REVISION.value
    await sol.save()
    return sol


async def cancelar_solicitud(
    solicitud_id: str, estudiante: Student, motivo: Optional[str] = None
) -> TramiteSolicitud:
    """El estudiante cancela su propia solicitud (solo si está pendiente o en revisión)."""
    sol = await obtener_solicitud(solicitud_id, estudiante=estudiante)
    if sol.estado in {EstadoTramite.APROBADA.value, EstadoTramite.RECHAZADA.value, EstadoTramite.CANCELADA.value}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"No puedes cancelar una solicitud en estado '{sol.estado}'.",
        )
    sol.estado = EstadoTramite.CANCELADA.value
    sol.fecha_cancelacion = utcnow_naive()
    sol.motivo_cancelacion = motivo
    await sol.save()
    return sol


async def estadisticas(current_user: User) -> TramiteEstadisticas:
    """
    Calcula estadísticas para el panel staff: cuántas solicitudes hay por
    tipo, cuántas por estado, cuántas están pendientes y se crearon hoy.
    """
    if not _es_staff_revision(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para ver estadísticas de solicitudes.",
        )

    # Un solo aggregation
    pipeline = [
        {
            "$group": {
                "_id": {"tipo": "$tipo", "estado": "$estado"},
                "count": {"$sum": 1},
            }
        }
    ]
    rows = await TramiteSolicitud.aggregate(pipeline).to_list()

    por_tipo: dict = {}
    por_estado: dict = {}
    total = 0
    for row in rows:
        tipo = row["_id"]["tipo"]
        est = row["_id"]["estado"]
        count = row["count"]
        por_tipo.setdefault(tipo, {})[est] = count
        por_estado[est] = por_estado.get(est, 0) + count
        total += count

    # Pendientes hoy (UTC)
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    pendientes_hoy = await TramiteSolicitud.find(
        {
            "estado": EstadoTramite.PENDIENTE.value,
            "created_at": {"$gte": hoy_inicio},
        }
    ).count()

    return TramiteEstadisticas(
        por_tipo=por_tipo,
        por_estado=por_estado,
        total=total,
        pendientes_hoy=pendientes_hoy,
    )
