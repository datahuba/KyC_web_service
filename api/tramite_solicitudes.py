"""
Router de Solicitudes de Trámite (Tramites Solicitudes)
========================================================

F-TRAMITES-SOLICITUD (2026-07-29): endpoints para los 4 tipos de solicitudes
que el estudiante crea desde /app/requests:
  - convalidacion | tutoria | readmision | titulacion

Endpoints:
  - POST   /tramites/                       -> estudiante crea
  - GET    /tramites/my                      -> estudiante ve las suyas
  - GET    /tramites/                        -> staff ve todas (paginado + filtros)
  - GET    /tramites/{id}                    -> estudiante o staff ve detalle
  - PATCH  /tramites/{id}/aprobar            -> staff aprueba
  - PATCH  /tramites/{id}/rechazar           -> staff rechaza
  - PATCH  /tramites/{id}/en-revision        -> staff marca "en revisión"
  - PATCH  /tramites/{id}/cancelar           -> estudiante cancela
  - GET    /tramites/estadisticas            -> staff: dashboard de métricas
"""

import math
from typing import Any, Optional, Union
from fastapi import APIRouter, Depends, HTTPException, Query, status

from models.user import User
from models.student import Student
from models.enums import EstadoTramite, TipoTramite
from schemas.tramite_solicitud import (
    TramiteEstadisticas,
    TramiteSolicitudAprobar,
    TramiteSolicitudCancelar,
    TramiteSolicitudCreate,
    TramiteSolicitudListResponse,
    TramiteSolicitudRechazar,
    TramiteSolicitudResponse,
)
from schemas.common import PaginatedResponse, PaginationMeta
from services import tramite_solicitud_service
from api.dependencies import get_current_user, require_staff

router = APIRouter()


def _user_is_staff(user: Union[User, Student]) -> bool:
    """True si es un User (no Student). El User tiene .role, el Student no."""
    return isinstance(user, User)


@router.post(
    "/",
    response_model=TramiteSolicitudResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear solicitud de trámite (estudiante)",
)
async def crear_solicitud(
    data: TramiteSolicitudCreate,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    """
    El estudiante autenticado crea una solicitud de Convalidación, Tutoría,
    Readmisión o Titulación.

    El estudiante debe subir los archivos a Cloudinary ANTES de llamar a
    este endpoint y pasar las URLs en `archivos`. Los archivos requeridos
    dependen del tipo (ver ARCHIVOS_REQUERIDOS_POR_TIPO en el schema).
    """
    if _user_is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los estudiantes pueden crear solicitudes de trámite.",
        )
    try:
        return await tramite_solicitud_service.crear_solicitud(data, current_user)
    except ValueError as e:
        # Errores de validación de datos (no auth)
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/my",
    response_model=list[TramiteSolicitudResponse],
    summary="Listar mis solicitudes (estudiante)",
)
async def listar_mis_solicitudes(
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    if _user_is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Este endpoint es solo para estudiantes.",
        )
    return await tramite_solicitud_service.listar_mis_solicitudes(current_user)


@router.get(
    "/estadisticas",
    response_model=TramiteEstadisticas,
    summary="Estadísticas de solicitudes (staff)",
)
async def obtener_estadisticas(
    current_user: User = Depends(require_staff),
) -> Any:
    return await tramite_solicitud_service.estadisticas(current_user)


@router.get(
    "/",
    response_model=PaginatedResponse[TramiteSolicitudResponse],
    summary="Listar todas las solicitudes (staff)",
)
async def listar_todas(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    tipo: Optional[TipoTramite] = Query(None),
    estado: Optional[EstadoTramite] = Query(None),
    estudiante_id: Optional[str] = Query(None, description="Filtrar por ID de estudiante"),
    current_user: User = Depends(require_staff),
) -> Any:
    items, total = await tramite_solicitud_service.listar_todas(
        current_user,
        page=page,
        per_page=per_page,
        tipo=tipo,
        estado=estado,
        estudiante_id=estudiante_id,
    )
    total_pages = math.ceil(total / per_page) if total > 0 else 0
    return {
        "items": items,
        "data": items,  # alias retro-compat
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
    "/{solicitud_id}",
    response_model=TramiteSolicitudResponse,
    summary="Detalle de una solicitud",
)
async def obtener_detalle(
    solicitud_id: str,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    if _user_is_staff(current_user):
        return await tramite_solicitud_service.obtener_solicitud(solicitud_id, current_user=current_user)
    return await tramite_solicitud_service.obtener_solicitud(solicitud_id, estudiante=current_user)


@router.patch(
    "/{solicitud_id}/en-revision",
    response_model=TramiteSolicitudResponse,
    summary="Marcar en revisión (staff)",
)
async def marcar_en_revision(
    solicitud_id: str,
    current_user: User = Depends(require_staff),
) -> Any:
    return await tramite_solicitud_service.marcar_en_revision(solicitud_id, current_user)


@router.patch(
    "/{solicitud_id}/aprobar",
    response_model=TramiteSolicitudResponse,
    summary="Aprobar solicitud (staff)",
)
async def aprobar_solicitud(
    solicitud_id: str,
    data: TramiteSolicitudAprobar,
    current_user: User = Depends(require_staff),
) -> Any:
    return await tramite_solicitud_service.aprobar_solicitud(solicitud_id, current_user)


@router.patch(
    "/{solicitud_id}/rechazar",
    response_model=TramiteSolicitudResponse,
    summary="Rechazar solicitud (staff)",
)
async def rechazar_solicitud(
    solicitud_id: str,
    data: TramiteSolicitudRechazar,
    current_user: User = Depends(require_staff),
) -> Any:
    return await tramite_solicitud_service.rechazar_solicitud(
        solicitud_id, current_user, data.motivo
    )


@router.patch(
    "/{solicitud_id}/cancelar",
    response_model=TramiteSolicitudResponse,
    summary="Cancelar mi solicitud (estudiante)",
)
async def cancelar_solicitud(
    solicitud_id: str,
    data: TramiteSolicitudCancelar,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    if _user_is_staff(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="El staff no puede cancelar solicitudes de estudiantes. Use rechazar.",
        )
    return await tramite_solicitud_service.cancelar_solicitud(
        solicitud_id, current_user, data.motivo
    )
