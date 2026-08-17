"""
Router de Reportes de Bugs
==========================

F-REPORTE-BUGS (2026-08-17, Kevin): el personal administrativo reporta
errores desde la propia aplicación, con detalle y evidencia adjunta.

  POST   /bug-reports/                  -> crear reporte (con adjuntos)
  GET    /bug-reports/                  -> listar (paginado + filtros)
  GET    /bug-reports/stats             -> conteo por estado, para badges
  GET    /bug-reports/{id}              -> detalle
  PATCH  /bug-reports/{id}/estado       -> cambiar estado (con respuesta)
  DELETE /bug-reports/{id}              -> borrar (solo superadmin)

RBAC: `require_staff` cubre los 7 perfiles administrativos y bloquea
docentes y estudiantes, que es exactamente lo que pidió Kevin.

Quién ve qué: cualquiera del staff puede reportar y ver SUS propios
reportes. Ver los de todos y cambiarles el estado queda para
admin/superadmin — si no, cualquiera podría cerrar el reporte de otro.
"""

import math
from datetime import datetime, timezone
from typing import Any, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from api.dependencies import require_staff
from core.cloudinary_utils import upload_document
from models.bug_report import BugReport
from models.enums import UserRole
from models.user import User
from schemas.common import PaginatedResponse, PaginationMeta

router = APIRouter()

SEVERIDADES = {"critica", "alta", "media", "baja"}
ESTADOS = {"abierto", "en_revision", "resuelto", "descartado"}
ESTADOS_QUE_EXIGEN_RESPUESTA = {"resuelto", "descartado"}

# Un reporte con 20 capturas no ayuda a nadie y llena Cloudinary.
MAX_ADJUNTOS = 5


class BugReportOut(BaseModel):
    id: str
    titulo: str
    descripcion: str
    pagina: Optional[str] = None
    adjuntos: List[str] = []
    severidad: str
    modulo: Optional[str] = None
    reportado_por_nombre: str
    reportado_por_rol: str
    estado: str
    respuesta: Optional[str] = None
    atendido_por: Optional[str] = None
    fecha_atencion: Optional[datetime] = None
    created_at: datetime
    # Nombres de los adjuntos que no se pudieron subir. Se informa acá y no
    # con un status de error: el reporte SÍ se guardó, y devolver un error
    # haría que el frontend lo trate como si se hubiera perdido todo.
    adjuntos_fallidos: List[str] = []


class CambioEstado(BaseModel):
    estado: str = Field(..., description="abierto | en_revision | resuelto | descartado")
    respuesta: Optional[str] = Field(
        None,
        max_length=2000,
        description="Obligatorio al resolver o descartar",
    )


def _to_out(r: BugReport, adjuntos_fallidos: Optional[List[str]] = None) -> BugReportOut:
    return BugReportOut(
        adjuntos_fallidos=adjuntos_fallidos or [],
        id=str(r.id),
        titulo=r.titulo,
        descripcion=r.descripcion,
        pagina=r.pagina,
        adjuntos=r.adjuntos or [],
        severidad=r.severidad,
        modulo=r.modulo,
        reportado_por_nombre=r.reportado_por_nombre,
        reportado_por_rol=r.reportado_por_rol,
        estado=r.estado,
        respuesta=r.respuesta,
        atendido_por=r.atendido_por,
        fecha_atencion=r.fecha_atencion,
        created_at=r.created_at,
    )


def _puede_gestionar(user: User) -> bool:
    """Ver los reportes de todos y cambiarles el estado."""
    return user.rol in (UserRole.ADMIN, UserRole.SUPERADMIN)


@router.post(
    "/",
    response_model=BugReportOut,
    status_code=status.HTTP_201_CREATED,
    summary="[Staff] Reportar un bug o error",
)
async def crear_reporte(
    titulo: str = Form(..., min_length=5, max_length=150),
    descripcion: str = Form(..., min_length=10, max_length=4000),
    severidad: str = Form("media"),
    pagina: Optional[str] = Form(None),
    modulo: Optional[str] = Form(None),
    archivos: List[UploadFile] = File(default=[]),
    current_user: User = Depends(require_staff),
) -> Any:
    """
    Crea el reporte y sube los adjuntos (capturas o PDF).

    Se usa multipart porque vienen archivos. Si la subida de un adjunto
    falla, el reporte se guarda igual: perder el texto de alguien que se
    tomó el trabajo de describir el problema sería peor que perder una
    captura.
    """
    if severidad not in SEVERIDADES:
        raise HTTPException(
            status_code=400,
            detail=f"Severidad inválida. Debe ser una de: {', '.join(sorted(SEVERIDADES))}",
        )

    reales = [a for a in (archivos or []) if a and a.filename]
    if len(reales) > MAX_ADJUNTOS:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_ADJUNTOS} adjuntos por reporte.",
        )

    urls: List[str] = []
    fallidos: List[str] = []
    for archivo in reales:
        try:
            url = await upload_document(file=archivo, folder="bug-reports")
            if url:
                urls.append(url)
        except Exception:
            fallidos.append(archivo.filename)

    reporte = BugReport(
        titulo=titulo.strip(),
        descripcion=descripcion.strip(),
        pagina=(pagina or "").strip() or None,
        modulo=(modulo or "").strip() or None,
        severidad=severidad,
        adjuntos=urls,
        reportado_por_id=current_user.id,
        reportado_por_nombre=current_user.nombre_visible,
        reportado_por_rol=str(getattr(current_user.rol, "value", current_user.rol)),
    )
    await reporte.create()

    # Si algún adjunto falló, el reporte igual se guarda y el frontend avisa.
    # Perder el texto de alguien que se tomó el trabajo de describir el
    # problema sería peor que perder una captura.
    return _to_out(reporte, adjuntos_fallidos=fallidos)


@router.get(
    "/",
    response_model=PaginatedResponse[BugReportOut],
    summary="[Staff] Listar reportes",
)
async def listar_reportes(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    estado: Optional[str] = Query(None),
    severidad: Optional[str] = Query(None),
    solo_mios: bool = Query(False, description="Ver únicamente los propios"),
    current_user: User = Depends(require_staff),
) -> Any:
    query: dict = {}
    # Quien no gestiona solo ve los suyos, aunque no pida solo_mios.
    if solo_mios or not _puede_gestionar(current_user):
        query["reportado_por_id"] = current_user.id
    if estado:
        query["estado"] = estado
    if severidad:
        query["severidad"] = severidad

    total = await BugReport.find(query).count()
    items = (
        await BugReport.find(query)
        .sort("-created_at")
        .skip((page - 1) * per_page)
        .limit(per_page)
        .to_list()
    )
    salida = [_to_out(r) for r in items]
    total_pages = math.ceil(total / per_page) if total else 0
    return {
        "items": salida,
        "data": salida,  # alias retro-compat
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1),
        ),
    }


@router.get("/stats", summary="[Staff] Conteo por estado")
async def stats(current_user: User = Depends(require_staff)) -> Any:
    base: dict = {} if _puede_gestionar(current_user) else {"reportado_por_id": current_user.id}
    salida = {}
    for e in sorted(ESTADOS):
        salida[e] = await BugReport.find({**base, "estado": e}).count()
    salida["total"] = sum(salida.values())
    return salida


@router.get("/{id}", response_model=BugReportOut, summary="[Staff] Detalle")
async def detalle(
    id: PydanticObjectId,
    current_user: User = Depends(require_staff),
) -> Any:
    r = await BugReport.get(id)
    if not r:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    if not _puede_gestionar(current_user) and r.reportado_por_id != current_user.id:
        raise HTTPException(status_code=403, detail="Solo podés ver tus propios reportes.")
    return _to_out(r)


@router.patch(
    "/{id}/estado",
    response_model=BugReportOut,
    summary="[Admin] Cambiar el estado de un reporte",
)
async def cambiar_estado(
    id: PydanticObjectId,
    body: CambioEstado,
    current_user: User = Depends(require_staff),
) -> Any:
    if not _puede_gestionar(current_user):
        raise HTTPException(
            status_code=403,
            detail="Solo admin o superadmin pueden cambiar el estado de un reporte.",
        )
    if body.estado not in ESTADOS:
        raise HTTPException(
            status_code=400,
            detail=f"Estado inválido. Debe ser uno de: {', '.join(sorted(ESTADOS))}",
        )
    # Cerrar un reporte sin decir por qué no le sirve a quien lo abrió.
    if body.estado in ESTADOS_QUE_EXIGEN_RESPUESTA and not (body.respuesta or "").strip():
        raise HTTPException(
            status_code=400,
            detail="Al resolver o descartar hay que explicar qué se hizo.",
        )

    r = await BugReport.get(id)
    if not r:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")

    r.estado = body.estado
    if body.respuesta:
        r.respuesta = body.respuesta.strip()
    r.atendido_por = current_user.nombre_visible
    r.fecha_atencion = datetime.now(timezone.utc)
    r.updated_at = datetime.now(timezone.utc)
    await r.save()
    return _to_out(r)


@router.delete("/{id}", summary="[Superadmin] Eliminar un reporte")
async def eliminar(
    id: PydanticObjectId,
    current_user: User = Depends(require_staff),
) -> Any:
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin puede eliminar reportes.",
        )
    r = await BugReport.get(id)
    if not r:
        raise HTTPException(status_code=404, detail="Reporte no encontrado")
    await r.delete()
    return {"message": "Reporte eliminado", "_id": str(id)}
