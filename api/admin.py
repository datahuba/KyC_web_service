"""
F-044 (2026-07-22) · API de Administración - Visor de Errores 500
================================================================

Contexto: errores 500 solo se veían en logs del contenedor, no llegaban
al usuario ni al equipo técnico. Esto dejó pasar bugs críticos como
F-046 (NameError en `subir_nota_borrador`) durante días.

Solución:
1. `main.py`: global exception handler persiste cada error 500 en
   colección MongoDB `error_logs` con TTL 7 días.
2. Este router: expone `GET /api/v1/admin/errors/recent` para que
   admin/superadmin vean los errores en el frontend.
3. Frontend `/app/admin/errors`: tabla con timestamp, path, method,
   status, mensaje, user, link al detalle con stack.

Solo superadmin y admin pueden acceder.
"""

from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.user import User, UserRole
from models.error_log import ErrorLog
from models.student import Student
from api.dependencies import get_current_user

router = APIRouter()


def require_admin_or_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Solo superadmin o admin pueden ver el visor de errores."""
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo usuarios pueden acceder a /admin")
    if current_user.rol not in (UserRole.SUPERADMIN, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin/admin pueden ver el visor de errores 500",
        )
    return current_user


class ErrorLogResponse(BaseModel):
    """Schema de respuesta para un error log."""
    id: str = Field(..., description="ID del log")
    timestamp: datetime
    path: str
    method: str
    status_code: int
    error_type: str
    message: str
    user_email: Optional[str] = None
    user_type: Optional[str] = None
    environment: str

    class Config:
        from_attributes = True


class ErrorLogDetailResponse(ErrorLogResponse):
    """Schema detallado (incluye stack_trace, request_body, query_params)."""
    stack_trace: Optional[str] = None
    request_body: Optional[str] = None
    query_params: Optional[str] = None


class ErrorLogsListResponse(BaseModel):
    """Lista paginada de error logs."""
    total: int = Field(..., description="Total de errores en el rango")
    items: List[ErrorLogResponse] = Field(..., description="Errores (ordenados DESC por timestamp)")
    stats: dict = Field(..., description="Estadísticas agregadas")


@router.get(
    "/errors/recent",
    response_model=ErrorLogsListResponse,
    summary="F-044: Listar errores 500 recientes (solo superadmin/admin)",
)
async def list_recent_errors(
    *,
    limit: int = Query(100, ge=1, le=500, description="Máximo de errores a retornar"),
    hours: int = Query(24, ge=1, le=168, description="Ventana de tiempo en horas (default 24, max 7 días)"),
    status_code: Optional[int] = Query(None, description="Filtrar por status code (ej: 500)"),
    path_contains: Optional[str] = Query(None, description="Filtrar por substring del path"),
    current_user: User = Depends(require_admin_or_superadmin),
):
    """
    Lista los errores 500 capturados en producción en las últimas N horas.

    F-044: por defecto muestra errores de las últimas 24h, ordenado DESC
    por timestamp. El TTL de la colección es 7 días así que más allá de
    eso no hay datos.
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    query = {"timestamp": {"$gte": since}}
    if status_code is not None:
        query["status_code"] = status_code
    if path_contains:
        query["path"] = {"$regex": path_contains, "$options": "i"}

    # Total para el header
    total = await ErrorLog.find(query).count()

    # Lista (ordenada DESC, limitada)
    errors = await ErrorLog.find(query).sort("-timestamp").limit(limit).to_list()

    # Estadísticas agregadas
    by_type = {}
    by_path = {}
    by_status = {}
    for err in errors:
        by_type[err.error_type] = by_type.get(err.error_type, 0) + 1
        by_path[err.path] = by_path.get(err.path, 0) + 1
        by_status[err.status_code] = by_status.get(err.status_code, 0) + 1

    # Top 5 paths con más errores
    top_paths = sorted(by_path.items(), key=lambda x: x[1], reverse=True)[:5]

    return ErrorLogsListResponse(
        total=total,
        items=[
            ErrorLogResponse(
                id=str(e.id),
                timestamp=e.timestamp,
                path=e.path,
                method=e.method,
                status_code=e.status_code,
                error_type=e.error_type,
                message=e.message,
                user_email=e.user_email,
                user_type=e.user_type,
                environment=e.environment,
            )
            for e in errors
        ],
        stats={
            "by_type": by_type,
            "by_status": by_status,
            "top_paths": [{"path": p, "count": c} for p, c in top_paths],
        },
    )


@router.get(
    "/errors/{error_id}",
    response_model=ErrorLogDetailResponse,
    summary="F-044: Detalle de un error 500 (con stack_trace y body)",
)
async def get_error_detail(
    *,
    error_id: str,
    current_user: User = Depends(require_admin_or_superadmin),
):
    """Detalle completo de un error, incluyendo stack_trace y body."""
    error = await ErrorLog.get(error_id)
    if not error:
        raise HTTPException(status_code=404, detail="Error log no encontrado")

    return ErrorLogDetailResponse(
        id=str(error.id),
        timestamp=error.timestamp,
        path=error.path,
        method=error.method,
        status_code=error.status_code,
        error_type=error.error_type,
        message=error.message,
        user_email=error.user_email,
        user_type=error.user_type,
        environment=error.environment,
        stack_trace=error.stack_trace,
        request_body=error.request_body,
        query_params=error.query_params,
    )


@router.delete(
    "/errors/clear",
    summary="F-044: Limpiar errores antiguos (solo superadmin)",
)
async def clear_old_errors(
    *,
    hours: int = Query(168, ge=1, description="Borrar errores más viejos que N horas (default 7 días)"),
    current_user: User = Depends(require_admin_or_superadmin),
):
    """Borra errores más viejos que N horas. Solo superadmin."""
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin puede borrar logs de errores",
        )
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    result = await ErrorLog.find({"timestamp": {"$lt": cutoff}}).delete()
    return {"deleted": result.deleted_count if hasattr(result, "deleted_count") else 0, "cutoff": cutoff.isoformat()}
