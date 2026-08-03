"""
Endpoints de Comunicados
========================

US-003 (2026-08-03): Módulo "Comunicados" en sidebar admin. El personal
(superadmin, encargado, cobranzas) crea anuncios oficiales para los
estudiantes. Los comunicados aparecen como pop-up al primer login del
estudiante (los ya vistos no se vuelven a mostrar).

Reglas de autorización:
- Crear/editar/eliminar: superadmin, encargado, cobranzas
  (encargado y cobranza SOLO sobre SUS cursos_asignados; superadmin sobre cualquiera)
- Listar admin: cualquier autorizado para crear
- Ver como estudiante: cualquier estudiante activo cuyas inscripciones
  coincidan con la audiencia del comunicado
- Marcar como visto: el propio estudiante

Endpoints:
- GET    /comunicados                  Listar (panel admin)
- POST   /comunicados                  Crear
- GET    /comunicados/{id}             Detalle
- PATCH  /comunicados/{id}             Editar
- DELETE /comunicados/{id}             Eliminar
- GET    /comunicados/pending          (estudiante) mis no vistos
- POST   /comunicados/{id}/mark-as-seen (estudiante) marcar como visto
"""

from datetime import datetime
from typing import Any, List, Optional, Union

from fastapi import APIRouter, Depends, HTTPException, Query, status
from beanie import PydanticObjectId
from beanie.operators import In, Or, And

from core.timezone_utils import utcnow_naive
from core.email_utils import build_comunicado_email, send_email
from core.config import settings

from models.comunicado import Comunicado, ComunicadoVisto
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment

from schemas.comunicado import (
    ComunicadoCreate,
    ComunicadoUpdate,
    ComunicadoResponse,
    ComunicadoListItem,
    ComunicadoEstudianteResponse,
    ComunicadosPendientesResponse,
    ComunicadoVistoResponse,
    ComunicadosListResponse,
)

from api.dependencies import get_current_user, get_current_active_user

router = APIRouter()

# Roles autorizados para crear/editar/eliminar comunicados.
# Kevin (2026-08-03): "superadmin, encargado, cobranzas".
COMUNICADO_AUTORES = [
    "superadmin", "encargado_curso", "cobranza",
]


def _es_autor_comunicados(user: User) -> bool:
    if not isinstance(user, User):
        return False
    return user.rol.value in COMUNICADO_AUTORES


async def _puede_crear_sobre_cursos(user: User, cursos_ids: List[PydanticObjectId]) -> bool:
    """
    Superadmin: puede crear para cualquier curso (o para todos).
    Encargado/Cobranza: SOLO si cursos_ids está contenido en sus cursos_asignados
    (o si cursos_ids está vacío = comunicado global: solo superadmin puede).
    """
    if user.rol.value == "superadmin":
        return True
    if user.rol.value in ("encargado_curso", "cobranza"):
        if not user.cursos_asignados:
            return False  # sin cursos asignados no puede crear nada
        if not cursos_ids:
            return False  # comunicado global solo superadmin
        return set(cursos_ids).issubset(set(user.cursos_asignados))
    return False


def _to_response(c: Comunicado) -> ComunicadoResponse:
    return ComunicadoResponse(
        id=str(c.id),
        titulo=c.titulo,
        contenido=c.contenido,
        autor_id=str(c.autor_id),
        autor_nombre=c.autor_nombre,
        autor_rol=c.autor_rol,
        cursos_ids=[str(x) for x in c.cursos_ids],
        importancia=c.importancia,
        adjuntos=c.adjuntos,
        expira_en=c.expira_en,
        enviar_email=c.enviar_email,
        email_enviado=c.email_enviado,
        email_enviado_en=c.email_enviado_en,
        email_destinatarios=c.email_destinatarios,
        total_vistos=c.total_vistos,
        created_at=c.created_at,
        updated_at=c.updated_at,
    )


def _to_estudiante_response(c: Comunicado, visto: bool) -> ComunicadoEstudianteResponse:
    return ComunicadoEstudianteResponse(
        id=str(c.id),
        titulo=c.titulo,
        contenido=c.contenido,
        autor_nombre=c.autor_nombre,
        autor_rol=c.autor_rol,
        importancia=c.importancia,
        adjuntos=c.adjuntos,
        expira_en=c.expira_en,
        created_at=c.created_at,
        visto=visto,
    )


# =====================================================================
# PANEL ADMIN
# =====================================================================

@router.get(
    "",
    response_model=ComunicadosListResponse,
    summary="Listar comunicados (panel admin)",
)
async def listar_comunicados(
    current_user: User = Depends(get_current_user),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    solo_mios: bool = Query(False, description="Si true, solo los comunicados creados por mí"),
) -> Any:
    """Lista los comunicados visibles para el personal autorizado."""
    if not _es_autor_comunicados(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para gestionar comunicados.",
        )

    # Filtro base: vigentes (no expirados)
    now = utcnow_naive()
    query: dict = {
        "$or": [
            {"expira_en": None},
            {"expira_en": {"$gt": now}},
        ]
    }

    # Si el usuario no es superadmin, limitar a comunicados globales o de sus cursos
    if current_user.rol.value != "superadmin":
        query["$and"] = [
            {
                "$or": [
                    {"cursos_ids": {"$size": 0}},  # global
                    {"cursos_ids": {"$in": current_user.cursos_asignados}},  # sus cursos
                ]
            }
        ]

    if solo_mios:
        query["autor_id"] = current_user.id

    total = await Comunicado.find(query).count()
    items_db = (
        await Comunicado.find(query)
        .sort("-created_at")
        .skip(skip)
        .limit(limit)
        .to_list()
    )

    items = [
        ComunicadoListItem(
            id=str(c.id),
            titulo=c.titulo,
            autor_nombre=c.autor_nombre,
            autor_rol=c.autor_rol,
            importancia=c.importancia,
            cursos_count=len(c.cursos_ids),
            total_vistos=c.total_vistos,
            email_enviado=c.email_enviado,
            created_at=c.created_at,
        )
        for c in items_db
    ]
    return ComunicadosListResponse(items=items, total=total)


@router.post(
    "",
    response_model=ComunicadoResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Crear comunicado",
)
async def crear_comunicado(
    data: ComunicadoCreate,
    current_user: User = Depends(get_current_user),
) -> Any:
    if not _es_autor_comunicados(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para crear comunicados.",
        )

    if not await _puede_crear_sobre_cursos(current_user, data.cursos_ids):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puede crear comunicados para sus cursos asignados. Para un comunicado global, contacte al superadmin.",
        )

    # Validar que los cursos existen (si se especificaron)
    if data.cursos_ids:
        cursos_existentes = await Course.find(In(Course.id, data.cursos_ids)).count()
        if cursos_existentes != len(data.cursos_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uno o más cursos especificados no existen.",
            )

    nombre_autor = getattr(current_user, "nombre_visible", current_user.username)

    com = Comunicado(
        titulo=data.titulo,
        contenido=data.contenido,
        autor_id=current_user.id,
        autor_nombre=nombre_autor,
        autor_rol=current_user.rol.value,
        cursos_ids=data.cursos_ids,
        importancia=data.importancia,
        adjuntos=data.adjuntos,
        expira_en=data.expira_en,
        enviar_email=data.enviar_email,
    )
    await com.insert()

    # Envío de email (asíncrono, no bloquea la respuesta)
    if data.enviar_email:
        await _enviar_email_comunicado(com)

    return _to_response(com)


@router.get(
    "/{comunicado_id}",
    response_model=ComunicadoResponse,
    summary="Detalle de un comunicado",
)
async def obtener_comunicado(
    comunicado_id: str,
    current_user: Union[User, Student] = Depends(get_current_user),
) -> Any:
    com = await Comunicado.get(PydanticObjectId(comunicado_id))
    if not com:
        raise HTTPException(status_code=404, detail="Comunicado no encontrado.")

    # Si es User autorizado para crear, puede ver detalle
    if isinstance(current_user, User) and _es_autor_comunicados(current_user):
        return _to_response(com)

    # Si es Student, debe estar en la audiencia del comunicado
    if isinstance(current_user, Student):
        if not com.cursos_ids:
            # Comunicado global, todos lo pueden ver
            return _to_response(com)
        if any(curso_id in [c.id for c in current_user.lista_cursos_ids or []] for curso_id in com.cursos_ids):
            return _to_response(com)
        raise HTTPException(status_code=403, detail="No tiene acceso a este comunicado.")

    raise HTTPException(status_code=403, detail="Acceso denegado.")


@router.patch(
    "/{comunicado_id}",
    response_model=ComunicadoResponse,
    summary="Editar comunicado",
)
async def editar_comunicado(
    comunicado_id: str,
    data: ComunicadoUpdate,
    current_user: User = Depends(get_current_user),
) -> Any:
    if not _es_autor_comunicados(current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para editar comunicados.")

    com = await Comunicado.get(PydanticObjectId(comunicado_id))
    if not com:
        raise HTTPException(status_code=404, detail="Comunicado no encontrado.")

    # Solo el autor o superadmin puede editar
    if str(com.autor_id) != str(current_user.id) and current_user.rol.value != "superadmin":
        raise HTTPException(status_code=403, detail="Solo el autor o un superadmin puede editar este comunicado.")

    # Si cambian los cursos, validar permiso
    if data.cursos_ids is not None:
        if not await _puede_crear_sobre_cursos(current_user, data.cursos_ids):
            raise HTTPException(status_code=403, detail="No puede reasignar el comunicado a cursos fuera de su alcance.")

    update_data = data.model_dump(exclude_unset=True)
    for k, v in update_data.items():
        setattr(com, k, v)
    await com.save()
    return _to_response(com)


@router.delete(
    "/{comunicado_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar comunicado",
)
async def eliminar_comunicado(
    comunicado_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    if not _es_autor_comunicados(current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso para eliminar comunicados.")

    com = await Comunicado.get(PydanticObjectId(comunicado_id))
    if not com:
        raise HTTPException(status_code=404, detail="Comunicado no encontrado.")

    if str(com.autor_id) != str(current_user.id) and current_user.rol.value != "superadmin":
        raise HTTPException(status_code=403, detail="Solo el autor o un superadmin puede eliminar este comunicado.")

    # Eliminar también los registros de visto asociados
    await ComunicadoVisto.find(ComunicadoVisto.comunicado_id == com.id).delete()
    await com.delete()


# =====================================================================
# ESTUDIANTE
# =====================================================================

@router.get(
    "/pending/me",
    response_model=ComunicadosPendientesResponse,
    summary="Comunicados pendientes del estudiante autenticado",
)
async def comunicados_pendientes(
    current_user: Student = Depends(get_current_user),
) -> Any:
    """
    Devuelve los comunicados que el estudiante autenticado AÚN NO HA VISTO.

    Reglas de audiencia:
    - Comunicado global (cursos_ids vacío): todos los estudiantes activos
    - Comunicado por curso: solo estudiantes inscritos en alguno de los cursos
    - Comunicado expirado: se omite
    """
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo los estudiantes pueden consultar sus comunicados pendientes.")

    now = utcnow_naive()
    cursos_estudiante = set(str(c) for c in current_user.lista_cursos_ids or [])

    # Traer todos los comunicados vigentes (no expirados)
    vigentes = await Comunicado.find(
        Or(
            Comunicado.expira_en == None,
            Comunicado.expira_en > now,
        )
    ).sort("-created_at").to_list()

    # Filtrar por audiencia
    visibles = []
    for c in vigentes:
        if not c.cursos_ids:
            visibles.append(c)  # global
        else:
            cursos_com = set(str(x) for x in c.cursos_ids)
            if cursos_com & cursos_estudiante:
                visibles.append(c)

    # Traer los ya vistos por este estudiante (una sola query)
    if visibles:
        ids_visibles = [c.id for c in visibles]
        ya_vistos_ids = set(
            str(v.comunicado_id) for v in await ComunicadoVisto.find(
                ComunicadoVisto.estudiante_id == current_user.id,
                In(ComunicadoVisto.comunicado_id, ids_visibles),
            ).to_list()
        )
    else:
        ya_vistos_ids = set()

    # Pendientes = visibles que aún no vio
    pendientes = [c for c in visibles if str(c.id) not in ya_vistos_ids]

    return ComunicadosPendientesResponse(
        cantidad=len(pendientes),
        comunicados=[_to_estudiante_response(c, visto=False) for c in pendientes],
    )


@router.post(
    "/{comunicado_id}/mark-as-seen",
    response_model=ComunicadoVistoResponse,
    summary="Marcar comunicado como visto",
)
async def marcar_como_visto(
    comunicado_id: str,
    current_user: Student = Depends(get_current_user),
) -> Any:
    if not isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Solo los estudiantes pueden marcar comunicados como vistos.")

    com = await Comunicado.get(PydanticObjectId(comunicado_id))
    if not com:
        raise HTTPException(status_code=404, detail="Comunicado no encontrado.")

    # Validar audiencia (mismo criterio que /pending/me)
    if com.cursos_ids:
        cursos_estudiante = set(str(c) for c in current_user.lista_cursos_ids or [])
        cursos_com = set(str(x) for x in com.cursos_ids)
        if not (cursos_com & cursos_estudiante):
            raise HTTPException(status_code=403, detail="No tienes acceso a este comunicado.")

    # Idempotente: si ya está marcado, devolver el timestamp existente
    existente = await ComunicadoVisto.find_one(
        ComunicadoVisto.comunicado_id == com.id,
        ComunicadoVisto.estudiante_id == current_user.id,
    )
    if existente:
        return ComunicadoVistoResponse(
            ok=True,
            comunicado_id=str(com.id),
            visto_en=existente.visto_en,
        )

    visto = ComunicadoVisto(
        comunicado_id=com.id,
        estudiante_id=current_user.id,
    )
    await visto.insert()

    # Denormalizar contador
    com.total_vistos = (com.total_vistos or 0) + 1
    await com.save()

    return ComunicadoVistoResponse(
        ok=True,
        comunicado_id=str(com.id),
        visto_en=visto.visto_en,
    )


# =====================================================================
# HELPERS
# =====================================================================

async def _enviar_email_comunicado(com: Comunicado) -> None:
    """
    Envía el comunicado por email a la audiencia correspondiente.
    Se ejecuta async (no bloquea la respuesta HTTP del POST).

    - Si cursos_ids está vacío: audiencia = todos los estudiantes activos
      con email.
    - Si cursos_ids tiene IDs: audiencia = estudiantes inscritos en
      alguno de esos cursos, con email.
    """
    try:
        # Construir query de audiencia
        if not com.cursos_ids:
            estudiantes = await Student.find(
                Student.activo == True,
                Student.email != None,
            ).to_list()
        else:
            # Estudiantes inscritos en alguno de los cursos
            enrollments = await Enrollment.find(
                In(Enrollment.curso_id, com.cursos_ids),
            ).to_list()
            ids_estudiantes = list({e.estudiante_id for e in enrollments})
            if not ids_estudiantes:
                com.email_enviado = True
                com.email_enviado_en = utcnow_naive()
                com.email_destinatarios = 0
                await com.save()
                return
            estudiantes = await Student.find(
                In(Student.id, ids_estudiantes),
                Student.activo == True,
                Student.email != None,
            ).to_list()

        portal_link = settings.FRONTEND_URL.rstrip("/") + "/app/dashboard"
        enviados = 0
        programa = "Unidad de Postgrado"
        if com.cursos_ids:
            # Intentar tomar el nombre del primer curso para el subject
            primer_curso = await Course.get(com.cursos_ids[0])
            if primer_curso:
                programa = primer_curso.nombre_programa or programa

        for est in estudiantes:
            html = build_comunicado_email(
                nombre=est.nombre or "Estudiante",
                asunto=com.titulo,
                mensaje=com.contenido,
                programa=programa,
                portal_link=portal_link,
            )
            ok = await send_email(est.email, com.titulo, html)
            if ok:
                enviados += 1

        com.email_enviado = True
        com.email_enviado_en = utcnow_naive()
        com.email_destinatarios = enviados
        await com.save()
    except Exception as e:
        # No fallamos el POST si el email falla. Solo logueamos.
        import traceback
        print(f"[comunicados] Error enviando email: {e}")
        traceback.print_exc()
