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
    # F-XXX (2026-07-29): estado de resolución
    resolved: bool = False
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    resolution_note: Optional[str] = None
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
    unresolved_only: bool = Query(True, description="Si True (default), solo errores NO resueltos"),
    current_user: User = Depends(require_admin_or_superadmin),
):
    """
    Lista los errores 500 capturados en producción en las últimas N horas.

    F-044: por defecto muestra errores de las últimas 24h, ordenado DESC
    por timestamp. El TTL de la colección es 7 días así que más allá de
    eso no hay datos.

    F-XXX (2026-07-29): por defecto filtra errores NO resueltos
    (`resolved=false`) para enfocarse en los que aún requieren atención.
    Pasar `unresolved_only=false` para ver también los resueltos.
    """
    since = datetime.utcnow() - timedelta(hours=hours)

    query = {"timestamp": {"$gte": since}}
    if status_code is not None:
        query["status_code"] = status_code
    if path_contains:
        query["path"] = {"$regex": path_contains, "$options": "i"}
    if unresolved_only:
        # F-XXX (2026-07-29): matchear también docs sin el campo `resolved`
        # (los creados antes de este feature). {$ne: True} cubre tanto
        # `resolved=false` como `resolved` ausente.
        query["resolved"] = {"$ne": True}

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
                # F-XXX (2026-07-29): estado de resolución
                resolved=bool(getattr(e, "resolved", False)),
                resolved_by=getattr(e, "resolved_by", None),
                resolved_at=getattr(e, "resolved_at", None),
                resolution_note=getattr(e, "resolution_note", None),
            )
            for e in errors
        ],
        stats={
            "by_type": by_type,
            "by_status": by_status,
            "top_paths": [{"path": p, "count": c} for p, c in top_paths],
            # F-XXX (2026-07-29): contadores adicionales de resolución
            "resolved_count": sum(1 for e in errors if getattr(e, "resolved", False)),
        },
    )


# F-XXX (2026-07-29): endpoint para marcar un error como resuelto
class ResolveErrorRequest(BaseModel):
    note: Optional[str] = Field(None, max_length=500, description="Nota opcional (ej: 'Fixed in commit abc123')")


@router.post(
    "/errors/{error_id}/resolve",
    summary="F-ERROR-VIEWER-FIX: Resolver y eliminar un error (HARD DELETE)",
)
async def resolve_error(
    *,
    error_id: str,
    payload: Optional[ResolveErrorRequest] = None,
    current_user: User = Depends(require_admin_or_superadmin),
):
    """
    F-ERROR-VIEWER-FIX (2026-07-31): antes este endpoint marcaba el error
    como `resolved=true` (soft delete). Pero Kevin: "cuando se solucionan
    eliminarse de la pagina". Ahora HACEMOS HARD DELETE -- el error
    desaparece del visor inmediatamente.

    Si quieren dejar registro, pueden archivar manualmente (TODO futuro).

    Nota: el `note` del payload se acepta pero ya no se persiste (no hay
    donde). Se loguea en el output del backend para auditoría.
    """
    from beanie import PydanticObjectId as _POI
    try:
        err_oid = _POI(error_id)
    except Exception:
        raise HTTPException(status_code=400, detail="error_id inválido")

    error = await ErrorLog.get(err_oid)
    if not error:
        raise HTTPException(status_code=404, detail="Error log no encontrado")

    # Auditoria: dejamos constancia en logs (no en BD).
    import logging
    logger = logging.getLogger("kyc.admin")
    logger.info(
        "ErrorLog resuelto+eliminado: id=%s path=%s method=%s status=%s by=%s note=%s",
        str(error.id), error.path, error.method, error.status_code,
        current_user.username, (payload.note if payload else None),
    )

    await error.delete()

    return {
        "id": str(error_id),
        "deleted": True,
        "resolved_by": current_user.username,
    }


# F-XXX (2026-07-29): endpoint bulk para resolver automáticamente errores
# esperados. Cuando un usuario tiene la sesión vencida y recarga la página,
# el frontend dispara muchos requests con token expirado → 401. Estos
# ensucian el visor con errores esperados. El admin puede resolverlos todos
# de una vez con este botón.
#
# Acepta un `pattern` opcional para matchear otros tipos de errores esperados
# (ej: "Credenciales incorrectas", "Demasiados intentos", "JSON inválido",
# "imagen demasiado grande", etc.).
@router.post(
    "/errors/auto-resolve-expired-tokens",
    summary="F-XXX: Marcar como resueltos errores esperados en la ventana",
)
async def auto_resolve_expired_tokens(
    *,
    hours: int = Query(168, ge=1, le=168, description="Ventana de tiempo en horas (default 7 días)"),
    pattern: str = Query(
        "Token.*inválido|expirado",
        description="Regex case-insensitive para matchear el mensaje del error. Default = 401 de token expirado.",
    ),
    status_code: Optional[int] = Query(
        401,
        description="Status code a matchear (default 401). Pasá 0 para no filtrar por status code.",
    ),
    note: str = Query(
        "Auto-resuelto: error esperado",
        description="Nota que se setea en resolution_note",
    ),
    current_user: User = Depends(require_admin_or_superadmin),
):
    """
    F-ERROR-VIEWER-FIX (2026-07-31): antes marcaba como `resolved=true`
    (soft delete). Ahora hace HARD DELETE de los errores que matcheen
    el patrón regex en su mensaje. Devuelve la cantidad eliminados.
    """
    since = datetime.utcnow() - timedelta(hours=hours)
    # Filtrar por timestamp y patrón; el campo `resolved` ya no se usa
    # pero lo dejamos por si hay docs viejos.
    query: dict = {
        "timestamp": {"$gte": since},
        "message": {"$regex": pattern, "$options": "i"},
    }
    if status_code and status_code > 0:
        query["status_code"] = status_code
    errors = await ErrorLog.find(query).to_list()
    deleted = 0
    for err in errors:
        try:
            await err.delete()
            deleted += 1
        except Exception as e:
            # Si falla un delete, seguimos con los demas
            import logging
            logging.getLogger("kyc.admin").warning("No se pudo eliminar ErrorLog %s: %s", str(err.id), e)
    return {
        "resolved_count": deleted,
        "window_hours": hours,
        "pattern": pattern,
    }


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
        # F-XXX (2026-07-29): estado de resolución en el detalle
        resolved=bool(getattr(error, "resolved", False)),
        resolved_by=getattr(error, "resolved_by", None),
        resolved_at=getattr(error, "resolved_at", None),
        resolution_note=getattr(error, "resolution_note", None),
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


# ============================================================================
# F-2026-08-12-EC-MIGRATE-HISTORICO (Kevin 2026-08-12)
# ============================================================================
# Migracion retroactiva: asigna TODOS los cursos historicos (es_historico=True)
# a TODOS los usuarios con rol ENCARGADO_CURSO o COORDINADOR que NO tengan
# cursos_asignados (o que tengan una lista pequena que indique que nunca se
# les asigno nada). Esto resuelve el problema de los EC que crearon
# programas historicos ANTES de que existiera el fix
# F-2026-08-12-EC-AUTOASIGNAR-CURSO (commit 5558e6d): sus cursos quedaron
# sin autoasignar y no aparecen en sus listados.
#
# Solo superadmin puede ejecutar (es una operacion masiva de BD).
# ============================================================================

@router.post(
    "/migrate/ec-historico-cursos",
    summary="F-2026-08-12-EC-MIGRATE: Asignar retroactivamente cursos historicos a ECs",
)
async def migrate_ec_historico_cursos(
    current_user: User = Depends(get_current_user),
):
    """
    Asigna todos los cursos con `es_historico=True` a todos los usuarios
    con rol ENCARGADO_CURSO o COORDINADOR. Es idempotente: si el EC ya
    tiene el curso asignado, no se duplica.

    Devuelve un resumen con cuantos cursos se asignaron, a cuantos ECs,
    y cuantos cursos no se tocaron (porque nadie los pidio o ya estaban
    asignados a todos los ECs objetivo).
    """
    if current_user.rol not in (UserRole.SUPERADMIN, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin/admin puede ejecutar migraciones de BD."
        )

    from models.course import Course
    from models.user import User as UserModel

    # 1. Obtener todos los cursos historicos
    cursos_historicos = await Course.find(Course.es_historico == True).to_list()
    if not cursos_historicos:
        return {
            "success": True,
            "cursos_historicos": 0,
            "ecs_actualizados": 0,
            "asignaciones_nuevas": 0,
            "message": "No hay cursos historicos en la BD. Nada que hacer.",
        }

    # 2. Obtener todos los ECs/COORDINADORES activos
    ecs = await UserModel.find(
        UserModel.rol.in_([UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR]),
        UserModel.activo == True,
    ).to_list()
    if not ecs:
        return {
            "success": True,
            "cursos_historicos": len(cursos_historicos),
            "ecs_actualizados": 0,
            "asignaciones_nuevas": 0,
            "message": "No hay ECs/COORDINADORES activos. Nada que hacer.",
        }

    # 3. Asignar cada curso a cada EC (idempotente)
    asignaciones_nuevas = 0
    ecs_actualizados = 0
    for ec in ecs:
        ec_actualizado = False
        cursos_ec = list(ec.cursos_asignados or [])
        for curso in cursos_historicos:
            if curso.id not in cursos_ec:
                cursos_ec.append(curso.id)
                asignaciones_nuevas += 1
                ec_actualizado = True
        if ec_actualizado:
            ec.cursos_asignados = cursos_ec
            await ec.save()
            ecs_actualizados += 1

    return {
        "success": True,
        "cursos_historicos": len(cursos_historicos),
        "ecs_encontrados": len(ecs),
        "ecs_actualizados": ecs_actualizados,
        "asignaciones_nuevas": asignaciones_nuevas,
        "message": (
            f"Migracion completada: {asignaciones_nuevas} asignaciones nuevas "
            f"a {ecs_actualizados} ECs/COORDINADORES. "
            f"Total cursos historicos: {len(cursos_historicos)}. "
            f"Total ECs revisados: {len(ecs)}."
        ),
    }
