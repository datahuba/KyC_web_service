"""
Router del Registro de Correos
==============================

F-CORREOS-REGISTRO (Kevin 2026-08-17): "ver cuales son las que llegan a los
usuarios". Hasta ahora no habia forma de saberlo — `send_email()` devolvia un
bool y los errores iban a `print()`.

  GET   /email-logs/          -> listar (paginado + filtros)
  GET   /email-logs/stats     -> cupo del dia y estado de la cola
  POST  /email-logs/procesar  -> reintentar encolados y fallidos
  GET   /email-logs/{id}      -> detalle, con el HTML que se envio

RBAC: admin y superadmin. El registro incluye el cuerpo de los correos, que
puede traer datos personales (y en el caso de las credenciales de
preinscripcion, la contraseña inicial del alumno), asi que no se abre al
resto del staff.
"""

import math
from typing import Any, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from api.dependencies import require_staff
from models.email_log import EmailLog, EstadoEmail, PrioridadEmail
from models.enums import UserRole
from models.user import User
from schemas.common import PaginatedResponse, PaginationMeta
from services import email_service

router = APIRouter()


class EmailLogOut(BaseModel):
    id: str
    destinatario: str
    destinatario_nombre: Optional[str] = None
    asunto: str
    tipo: str
    prioridad: str
    estado: str
    intentos: int
    error: Optional[str] = None
    fecha_envio: Optional[Any] = None
    created_at: Any
    # El HTML solo viaja en el detalle: en el listado seria mandar cientos de
    # kilobytes que nadie mira.
    cuerpo_html: Optional[str] = None


def _puede_ver(user: User) -> bool:
    return user.rol in (UserRole.ADMIN, UserRole.SUPERADMIN)


def _exigir_permiso(user: User) -> None:
    if not _puede_ver(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El registro de correos es solo para admin o superadmin: "
                   "incluye el contenido de los mensajes.",
        )


def _to_out(l: EmailLog, incluir_cuerpo: bool = False) -> EmailLogOut:
    return EmailLogOut(
        id=str(l.id),
        destinatario=l.destinatario,
        destinatario_nombre=l.destinatario_nombre,
        asunto=l.asunto,
        tipo=l.tipo,
        prioridad=l.prioridad,
        estado=l.estado,
        intentos=l.intentos,
        error=l.error,
        fecha_envio=l.fecha_envio,
        created_at=l.created_at,
        cuerpo_html=(l.cuerpo_html if incluir_cuerpo else None),
    )


@router.get(
    "/stats",
    summary="[Admin] Cupo del día y estado de la cola de correo",
    description=(
        "Cuántos correos se enviaron hoy, cuánto queda del tope diario, y "
        "cuántos están encolados o fallidos. El cupo reservado es el colchón "
        "que los correos NO críticos no pueden tocar, para que un envío "
        "masivo no deje sin credenciales a un alumno que se preinscribe."
    ),
)
async def stats(current_user: User = Depends(require_staff)) -> Any:
    _exigir_permiso(current_user)
    return await email_service.estadisticas()


@router.post(
    "/procesar",
    summary="[Admin] Reintentar los correos encolados y fallidos",
    description=(
        "Procesa la cola respetando la prioridad: primero los críticos y, "
        "dentro de cada prioridad, los más viejos. Así un lote de comunicados "
        "nunca posterga una credencial de acceso."
    ),
)
async def procesar(
    limite: int = Query(100, ge=1, le=500),
    current_user: User = Depends(require_staff),
) -> Any:
    _exigir_permiso(current_user)
    return await email_service.procesar_pendientes(limite=limite)


@router.get(
    "/",
    response_model=PaginatedResponse[EmailLogOut],
    summary="[Admin] Listar correos enviados y pendientes",
)
async def listar(
    page: int = Query(1, ge=1),
    per_page: int = Query(25, ge=1, le=100),
    estado: Optional[str] = Query(None, description="enviado | fallido | encolado | descartado"),
    tipo: Optional[str] = Query(None),
    prioridad: Optional[str] = Query(None),
    destinatario: Optional[str] = Query(None, description="Búsqueda parcial por email"),
    current_user: User = Depends(require_staff),
) -> Any:
    _exigir_permiso(current_user)

    query: dict = {}
    if estado:
        if estado not in EstadoEmail.TODOS:
            raise HTTPException(
                status_code=400,
                detail=f"Estado inválido. Debe ser uno de: {', '.join(EstadoEmail.TODOS)}",
            )
        query["estado"] = estado
    if tipo:
        query["tipo"] = tipo
    if prioridad:
        if prioridad not in PrioridadEmail.TODAS:
            raise HTTPException(
                status_code=400,
                detail=f"Prioridad inválida. Debe ser una de: {', '.join(PrioridadEmail.TODAS)}",
            )
        query["prioridad"] = prioridad
    if destinatario:
        # Escapado para que un punto del email no funcione como comodín.
        import re as _re
        query["destinatario"] = {"$regex": _re.escape(destinatario), "$options": "i"}

    total = await EmailLog.find(query).count()
    items = (
        await EmailLog.find(query)
        .sort("-created_at")
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list()
    )
    salida = [_to_out(l) for l in items]
    total_pages = math.ceil(total / per_page) if total else 0
    return {
        "items": salida,
        "data": salida,
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1),
        ),
    }


@router.get(
    "/{log_id}",
    response_model=EmailLogOut,
    summary="[Admin] Detalle de un correo, con el HTML que se envió",
)
async def detalle(
    log_id: PydanticObjectId,
    current_user: User = Depends(require_staff),
) -> Any:
    _exigir_permiso(current_user)
    l = await EmailLog.get(log_id)
    if not l:
        raise HTTPException(status_code=404, detail="Registro no encontrado")
    return _to_out(l, incluir_cuerpo=True)
