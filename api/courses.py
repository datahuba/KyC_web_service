from typing import List, Any, Union, Optional, Dict, Literal
import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel, Field
from beanie.operators import In
from models.course import Course
from models.user import User
from models.student import Student
from models.enrollment import Enrollment
from models.estado_programa import EstadoPrograma
from models.enums import UserRole, EstadoInscripcion
from schemas.course import CourseCreate, CourseResponse, CourseUpdate, CourseEnrolledStudent
from schemas.enrollment import EnrollmentCreate
from services import course_service
from beanie import PydanticObjectId

# Nuevas dependencias de seguridad del ISSUE L
from api.dependencies import require_superadmin, require_cpd, require_staff, get_current_user, require_encargado_curso


# F-US-006-3TIPOS-3A (2026-08-04): dependencia que permite a CPD, admin,
# superadmin, encargado_curso o coordinador realizar operaciones de carga
# inicial. La verificacion de si el encargado tiene asignado el curso
# especifico se hace DENTRO del endpoint (no en la dep) porque depende del
# id del curso en el path.
def require_cpd_or_encargado_curso_or_coordinador(current_user: User = Depends(get_current_user)) -> User:
    """F-US-006-3TIPOS: permite a CPD/ADMIN/SUPERADMIN/ENCARGADO_CURSO/COORDINADOR."""
    if current_user.rol not in (
        UserRole.SUPERADMIN,
        UserRole.ADMIN,
        UserRole.CPD,
        UserRole.ENCARGADO_CURSO,
        UserRole.COORDINADOR,
    ):
        raise HTTPException(
            status_code=403,
            detail="Solo CPD, admin, superadmin, encargado de curso o coordinador pueden realizar esta accion.",
        )
    return current_user

router = APIRouter()


class ComunicadoRequest(BaseModel):
    """Comunicado por correo del Encargado de Programa/CPD a los estudiantes de un programa."""
    asunto: str = Field(..., min_length=1, max_length=200)
    mensaje: str = Field(..., min_length=1, max_length=5000)


@router.post("/{id}/comunicado", summary="Enviar comunicado por correo a los estudiantes del programa")
async def enviar_comunicado_programa(
    *,
    id: PydanticObjectId,
    payload: ComunicadoRequest,
    current_user: User = Depends(require_encargado_curso)  # ENCARGADO_CURSO/COORDINADOR/CPD/ADMIN/SUPERADMIN
) -> Any:
    """
    Envía un comunicado (asunto + mensaje) a TODOS los estudiantes inscritos en
    el programa: notificación in-app (siempre) + correo real si tienen email y
    SMTP está configurado. El Encargado de Curso solo puede enviarlo a sus
    programas asignados. Envíos concurrentes (semáforo) para no hacer timeout
    con muchos estudiantes.
    """
    course = await Course.get(id)
    if not course:
        raise HTTPException(status_code=404, detail="Programa no encontrado")

    if current_user.rol == UserRole.ENCARGADO_CURSO and id not in current_user.cursos_asignados:
        raise HTTPException(status_code=403, detail="No tienes asignado este programa")

    enrollments = await Enrollment.find(Enrollment.curso_id == id).to_list()
    student_ids = list({e.estudiante_id for e in enrollments})
    if not student_ids:
        return {"success": True, "total_estudiantes": 0, "correos_enviados": 0,
                "detail": "El programa no tiene estudiantes inscritos."}

    students = await Student.find(In(Student.id, student_ids)).to_list()

    from services.notification_service import create_notification
    from core.email_utils import send_email, build_comunicado_email
    from core.config import settings

    portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/dashboard"
    nombre_programa = course.nombre_programa
    asunto = payload.asunto.strip()
    mensaje = payload.mensaje.strip()

    sem = asyncio.Semaphore(8)
    correos_enviados = 0

    async def _procesar(st: Student):
        nonlocal correos_enviados
        async with sem:
            try:
                await create_notification(
                    destinatario_id=st.id,
                    tipo_destinatario="student",
                    titulo=asunto,
                    mensaje=mensaje,
                    tipo_alerta="info",
                    ruta="/app/dashboard"
                )
            except Exception as e:
                print(f"Error notificando comunicado a {st.id}: {str(e)}")
            if st.email:
                try:
                    html = build_comunicado_email(
                        nombre=st.nombre or st.registro,
                        asunto=asunto,
                        mensaje=mensaje,
                        programa=nombre_programa,
                        portal_link=portal_link
                    )
                    from services import email_service
                    _log = await email_service.enviar(
                        destinatario=st.email,
                        asunto=f"{asunto} · {nombre_programa}",
                        html=html,
                        tipo=email_service.TipoEmail.COMUNICADO,
                        destinatario_id=getattr(st, "id", None),
                        destinatario_nombre=getattr(st, "nombre", None),
                    )
                    ok = _log.estado == "enviado"
                    if ok:
                        correos_enviados += 1
                except Exception as e:
                    print(f"Error enviando comunicado por correo a {st.email}: {str(e)}")

    await asyncio.gather(*[_procesar(st) for st in students])

    return {
        "success": True,
        "total_estudiantes": len(students),
        "correos_enviados": correos_enviados,
        "detail": f"Comunicado enviado a {len(students)} estudiante(s)."
    }

from schemas.common import PaginatedResponse, PaginationMeta
from fastapi import Query
import math

from models.enums import TipoCurso, Modalidad
from typing import Optional

@router.get(
    "/",
    response_model=PaginatedResponse[CourseResponse],
    summary="Listar Cursos"
)
async def read_courses(
    page: int = Query(1, ge=1, description="Número de página"),
    per_page: int = Query(10, ge=1, le=100, description="Elementos por página"),
    q: Optional[str] = Query(None, description="Búsqueda por nombre o código"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    tipo_curso: Optional[TipoCurso] = Query(None, description="Filtrar por tipo de curso"),
    modalidad: Optional[Modalidad] = Query(None, description="Filtrar por modalidad"),
    estado: Optional[str] = Query(
        None,
        description="F-080: filtrar por estado calculado del programa (programado | en_ejecucion | cerrado)"
    ),
    # FIX-ISSUE-272 (2026-08-14): filtro por es_historico.
    es_historico: Optional[bool] = Query(
        None,
        description="FIX-ISSUE-272: filtrar por es_historico (true=historicos, false=activos)"
    ),
    current_user: Union[User, Student] = Depends(get_current_user) # Abierto para todos
) -> Any:
    """Listar cursos con paginación y filtros"""
    # F-2026-08-12-EC-CURSOS-FILTRO (Kevin 2026-08-12 post-reunion UAGRM):
    # el EC solo debe ver SUS cursos asignados. Esto filtra el dropdown
    # de cursos en el frontend (cursos del EC, no todos). Si no es User
    # (es Student) o no tiene cursos_asignados, ve todos (acceso normal).
    cursos_asignados_list = None
    if isinstance(current_user, User):
        from api.dependencies import filtro_cursos_por_rol
        cursos_filtro = filtro_cursos_por_rol(current_user)
        cursos_asignados_list = cursos_filtro.get("curso_id", {}).get("$in") if cursos_filtro else None

    courses, total_count = await course_service.get_courses(
        page=page,
        per_page=per_page,
        q=q,
        activo=activo,
        tipo_curso=tipo_curso,
        modalidad=modalidad,
        estado=estado,
        es_historico=es_historico,  # FIX-ISSUE-272
        cursos_asignados=cursos_asignados_list,
    )

    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): popular
    # `estado_calculado` para cada curso (no es un campo del modelo, es
    # un metodo). El frontend lo usa para mostrar el badge correcto.
    for c in courses:
        c.estado_calculado = c.get_estado_actual()

    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0

    # FIX-ISSUE-250 (2026-08-14): el frontend lee `items` (consistente con
    # /calendario y /disponibles). Antes retornaba solo `data` y el EC veia
    # panel vacio. Ahora retornamos `items` (campo principal) Y `data` (alias
    # para retro-compatibilidad) para no romper consumidores que ya leen data.
    return {
        "items": courses,
        "data": courses,  # alias retro-compat
        "meta": PaginationMeta(
            page=page,
            limit=per_page,
            totalItems=total_count,
            totalPages=total_pages,
            hasNextPage=(page < total_pages),
            hasPrevPage=(page > 1)
        )
    }


# ============================================================================
# F-080: CALENDARIO DE PROGRAMAS
# ============================================================================

@router.get(
    "/calendario",
    summary="F-080: Calendario de programas (Timeline o Lista Cronológica)"
)
async def get_calendario(
    year: Optional[int] = Query(None, description="Filtrar por año de fecha_inicio"),
    tipo_curso: Optional[TipoCurso] = Query(None, description="Filtrar por tipo"),
    estado: Optional[str] = Query(None, description="Filtrar por estado calculado (programado | en_ejecucion | cerrado)"),
    current_user: User = Depends(require_staff)
) -> Any:
    """
    Devuelve todos los cursos con su estado calculado en runtime (F-080).
    F-080-REGLA-K: el calendario es solo para personal administrativo
    (superadmin, admin, cpd, mae, cobranza, encargado_curso, coordinador,
    docente). Los estudiantes NO tienen acceso — Kevin: "el calendario es
    para administrativos, no para estudiantes".
    """
    items = await course_service.get_courses_para_calendario(
        year=year,
        tipo_curso=tipo_curso,
        estado=estado,
    )
    return {
        "success": True,
        "year": year,
        "total": len(items),
        "items": items,
    }


@router.get(
    "/disponibles",
    summary="F-080: Cursos disponibles para que un estudiante se inscriba"
)
async def get_disponibles(
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """
    F-080 + F-US-006-3TIPOS (2026-08-04): devuelve SOLO los cursos en
    estado PROGRAMADO (los únicos que aceptan nuevas inscripciones de
    estudiantes). Es el endpoint que consume el dashboard del estudiante
    para mostrar los cursos donde podría pedir inscripción.

    Antes retornaba PROGRAMADO + EN_EJECUCION. Tras el cambio de Kevin, un
    programa en ejecución ya cerró inscripciones — los rezagados los mete
    el admin/encargado manualmente. Los CERRADOS e HISTÓRICOS nunca
    aparecen aquí.
    """
    courses = await course_service.get_courses_disponibles_para_estudiante()
    return {
        "success": True,
        "total": len(courses),
        "items": [
            {
                "id": str(c.id),
                "codigo": c.codigo,
                "nombre_programa": c.nombre_programa,
                "tipo_curso": c.tipo_curso.value,
                "modalidad": c.modalidad.value,
                "fecha_inicio": c.fecha_inicio,
                "fecha_fin": c.fecha_fin,
                "estado_calculado": c.get_estado_actual(),
                "costo_total_interno": c.costo_total_interno,
                "matricula_interno": c.matricula_interno,
                "cantidad_modulos": len(c.modulos or []),
            }
            for c in courses
        ],
    }


# ============================================================================
# F-US-006-3TIPOS-3A (2026-08-04): CARGA INICIAL DE ESTUDIANTES
# ============================================================================
# Cuando se crea un programa en_ejecucion o historico, el admin/encargado
# debe poder cargar la lista de estudiantes que ya estaban/estan en el
# programa (sin pasar por el flujo de inscripcion normal, que ya cerro).
# Este endpoint reutiliza la logica del bulk enrollment pero:
#   - NO valida que el curso este activo (puede estar cerrado/historico)
#   - NO valida que el curso acepte inscripciones nuevas (es carga retroactiva)
#   - Marca cada inscripcion con el flag `es_carga_inicial` para auditoria
class InitialEnrollmentItem(BaseModel):
    """Un estudiante a inscribir en la carga inicial."""
    estudiante_id: str = Field(..., description="ID del estudiante (PydanticObjectId)")
    # Opcional para en_ejecucion: modulo desde el cual se inscribe
    modulo_inicial_index: Optional[int] = Field(
        None,
        ge=0,
        description="Indice del modulo desde el cual entra el estudiante (0-based). Solo para programas en_ejecucion."
    )
    # Opcional: si ya pago la matricula
    matricula_pagada: bool = Field(
        default=False,
        description="Si el estudiante ya pago la matricula (caso retroactivo/historico)."
    )
    # Opcional: pagos por modulo del Excel del CPD (carga retroactiva).
    # Llave = indice del modulo en el curso (0-based string), valor = monto pagado.
    # F-HISTORICO-AUTOSERVICIO-EXCEL (2026-08-04): al subir el Excel, el sistema
    # detecta "Pago Modulo1", "Pago Modulo2", etc. y los envia aqui para que
    # el estado del modulo se registre como Pagado/Parcial segun corresponda.
    pagos_modulos: Optional[Dict[str, float]] = Field(
        default=None,
        description="Dict {modulo_index_str: monto_pagado} del Excel del CPD. Ej: {'0': 294, '1': 294}."
    )
    # F-FIX-DESCUENTO-ITEM (2026-08-05, Kevin): el item puede traer el descuento
    # individual del estudiante. Esto permite re-aplicar el descuento del 50%
    # institucional a los 64 inscritos sin tener que borrar y re-cargar.
    # Si el item NO trae descuento, el backend usa el descuento del CURSO.
    descuento_id: Optional[str] = Field(
        None,
        description="ID del descuento individual del estudiante (PydanticObjectId). Si se pasa, se aplica al enrollment."
    )
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0, le=100,
        description="Porcentaje de descuento personalizado (0-100). Se usa si no hay descuento_id."
    )


class InitialEnrollmentRequest(BaseModel):
    """Lista de estudiantes a inscribir como carga inicial del programa."""
    estudiantes: List[InitialEnrollmentItem] = Field(..., min_length=1, max_length=200)


class InitialEnrollmentResultado(BaseModel):
    """Resultado de inscribir a un estudiante en la carga inicial."""
    estudiante_id: str
    success: bool
    message: str
    enrollment_id: Optional[str] = None
    # F-CARGA-CONTEO-ESTRUCTURADO (2026-08-18): antes los totales de la
    # respuesta se calculaban buscando substrings dentro de `message`
    # ("actualizaron pagos", "ya esta inscrito"). Cualquier cambio de
    # redaccion rompia el conteo en silencio, sin fallar ningun test.
    # Ahora la accion se declara de forma explicita y `message` queda
    # como texto libre para mostrarle al usuario.
    accion: Literal["creado", "actualizado", "ya_inscrito", "error"] = "error"


class InitialEnrollmentResponse(BaseModel):
    total_solicitados: int
    exitosos: int
    ya_inscritos: int
    fallidos: int
    resultados: List[InitialEnrollmentResultado]


@router.post(
    "/{id}/initial-enrollments",
    response_model=InitialEnrollmentResponse,
    status_code=200,
    summary="F-US-006-3TIPOS: Carga inicial de estudiantes para programas en_ejecucion o historicos",
)
async def post_initial_enrollments(
    id: PydanticObjectId,
    payload: InitialEnrollmentRequest,
    current_user: User = Depends(require_cpd_or_encargado_curso_or_coordinador),
) -> Any:
    """
    F-US-006-3TIPOS-3A (2026-08-04): carga la lista inicial de estudiantes
    para un programa en_ejecucion (los que ya estan inscritos) o historico
    (los que cursaron en el pasado). NO valida acepta_inscripciones() ni
    que el curso este activo: es una operacion administrativa de carga
    retroactiva.

    Permisos:
    - superadmin / admin / cpd: cualquier curso.
    - encargado_curso: solo cursos en cursos_asignados.
    - coordinador: cualquier curso.

    Para programas en_ejecucion, se puede especificar el modulo_inicial_index
    desde el cual se inscribe el estudiante (los modulos anteriores ya los
    curso/pago, este es desde donde arranca en el sistema). Para historicos,
    no se usa este campo.
    """
    from services import enrollment_service

    # 1. Verificar permisos por curso asignado.
    # F-CARGA-COORD-SEGMENTA (2026-08-18, Kevin): el COORDINADOR tambien queda
    # restringido a sus cursos_asignados. Antes solo se restringia al
    # ENCARGADO_CURSO, asi que un coordinador podia hacer carga inicial en
    # CUALQUIER curso aunque en los listados solo viera los suyos
    # (filtro_cursos_por_rol en dependencies.py ya lo segmentaba para LECTURA
    # sin excepcion). Esa asimetria lectura/escritura no era intencional.
    if (
        current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR)
        and id not in (current_user.cursos_asignados or [])
    ):
        raise HTTPException(
            status_code=403,
            detail="No tienes asignado este curso.",
        )

    # 2. Cargar el curso
    course = await Course.get(id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    # 3. Validar tipo de programa
    es_historico = getattr(course, "es_historico", False)
    estado_actual = course.get_estado_actual()
    if estado_actual == EstadoPrograma.PROGRAMADO.value:
        raise HTTPException(
            status_code=400,
            detail=(
                "Este endpoint es SOLO para programas en_ejecucion o historicos. "
                "Para programas en estado programado usa el flujo normal de "
                "inscripcion (el estudiante se inscribe por su cuenta desde "
                "su dashboard)."
            ),
        )

    # 4. Pre-cargar estudiantes
    estudiante_ids_unicos = list({item.estudiante_id for item in payload.estudiantes})
    try:
        estudiante_obj_ids = [PydanticObjectId(sid) for sid in estudiante_ids_unicos]
    except Exception:
        raise HTTPException(status_code=400, detail="estudiante_id invalido (debe ser PydanticObjectId)")

    students = await Student.find({"_id": {"$in": estudiante_obj_ids}}).to_list()
    student_map: dict = {str(s.id): s for s in students}

    exitosos = 0
    ya_inscritos_count = 0
    fallidos = 0
    resultados: List[InitialEnrollmentResultado] = []

    # F-CARGA-RACE-INSCRITOS (2026-08-18): acumuladores de referencias cruzadas.
    # Las tareas concurrentes NO escriben sobre `course` ni sobre cada
    # `student`; solo anotan aca bajo lock, y al final se persiste todo en
    # dos escrituras (un course.save() y un update_many de estudiantes).
    links_lock = asyncio.Lock()
    inscritos_a_agregar: set = set()
    estudiantes_a_vincular: set = set()

    # F-HISTORICO-EXCEL-PARALLEL (2026-08-04): procesar items en paralelo
    # con asyncio.gather y un semaforo para no saturar la BD. El loop
    # serial anterior tomaba ~2s por item, total 62 items = 2 min = timeout.
    # Con gather (sem=5), el total se reduce a ~25s para 62 items.
    async def procesar_item(item: InitialEnrollmentItem) -> InitialEnrollmentResultado:
        est_id_str = item.estudiante_id
        try:
            student = student_map.get(est_id_str)
            if not student:
                raise ValueError(f"Estudiante {est_id_str} no encontrado")

            # Verificar si ya esta inscrito en este curso
            existing = await Enrollment.find_one(
                Enrollment.estudiante_id == student.id,
                Enrollment.curso_id == course.id,
            )
            if existing:
                # F-HISTORICO-AUTOSERVICIO-EXCEL-PAGOS2 (2026-08-04): si el item
                # trae pagos_modulos o matricula_pagada, actualizar el enrollment
                # existente en vez de saltar. Esto cubre el caso donde el CPD
                # volvio a subir el Excel despues de un intento parcial.
                # F-HISTORICO-EXCEL-TOTAL-PAGADO-FIX2 (2026-08-04): el flag
                # 'actualizado' debe dispararse SIEMPRE que el item traiga
                # pagos_modulos, no solo si el monto del modulo cambia.
                # Razon: los modulos pueden ya estar Pagado (de intentos
                # anteriores que no actualizaron total_pagado), pero igual
                # necesitamos recalcular el total del enrollment.
                # F-FIX-DESCUENTO-ITEM (2026-08-05, Kevin): ademas actualizar
                # el descuento individual del estudiante si el item lo trae.
                actualizado = False
                if item.matricula_pagada and not existing.matricula_pagada:
                    existing.matricula_pagada = True
                    actualizado = True
                # F-FIX-MATRICULA-TOTAL-PAGADO (2026-08-05, Kevin): si la matricula
                # vale > 0 y el item dice que ya esta pagada, sumar el costo
                # de la matricula al total_pagado. Antes solo se seteaba el flag
                # sin actualizar el saldo, dejando el estado en PENDIENTE_PAGO.
                if (
                    item.matricula_pagada
                    and (existing.costo_matricula or 0) > 0
                    and (existing.matricula_pagada or False)
                ):
                    # Sumar la matricula al total_pagado si no estaba ya sumado
                    if (existing.total_pagado or 0) < (existing.costo_matricula or 0):
                        existing.actualizar_saldo(existing.costo_matricula)
                        actualizado = True
                # F-FIX-DESCUENTO-ITEM: actualizar descuento individual si viene
                if item.descuento_id is not None or item.descuento_personalizado is not None:
                    if item.descuento_id:
                        try:
                            disc = await Discount.get(PydanticObjectId(item.descuento_id))
                            if disc and disc.activo:
                                existing.descuento_estudiante_id = disc.id
                                existing.descuento_personalizado = float(disc.porcentaje)
                                actualizado = True
                        except Exception:
                            pass
                    elif item.descuento_personalizado is not None:
                        existing.descuento_estudiante_id = None
                        existing.descuento_personalizado = float(item.descuento_personalizado)
                        actualizado = True
                    # Recalcular el total_a_pagar con la nueva logica MAX
                    from services.enrollment_service import _recalcular_total_enrollment
                    try:
                        _recalcular_total_enrollment(existing, course)
                        actualizado = True
                    except Exception as e:
                        # Si falla, no romper
                        pass
                total_pagos_a_aplicar = 0.0
                if item.pagos_modulos and existing.modulos:
                    for idx_str, monto in item.pagos_modulos.items():
                        try:
                            idx = int(idx_str)
                        except (ValueError, TypeError):
                            continue
                        if 0 <= idx < len(existing.modulos):
                            mod = existing.modulos[idx]
                            monto_aplicar = float(monto or 0.0)
                            nuevo_pagado = (mod.monto_pagado or 0.0) + monto_aplicar
                            if mod.costo and nuevo_pagado > mod.costo + 0.01:
                                monto_aplicar = max(0.0, mod.costo - (mod.monto_pagado or 0.0))
                                nuevo_pagado = mod.costo
                            if nuevo_pagado != (mod.monto_pagado or 0.0):
                                mod.monto_pagado = nuevo_pagado
                                if mod.costo and nuevo_pagado >= mod.costo - 0.01:
                                    mod.estado = "Pagado"
                                elif nuevo_pagado > 0:
                                    mod.estado = "Parcial"
                            # Marcar actualizado siempre que el item TRAIGA pagos_modulos,
                            # asi recalculamos total_pagado aunque los modulos no cambien
                            actualizado = True
                            total_pagos_a_aplicar += monto_aplicar
                # F-HISTORICO-EXCEL-TOTAL-PAGADO (2026-08-04): recalcular
                # total_pagado y saldo_pendiente a partir de los modulos,
                # porque el endpoint /courses/{id}/students los lee de ahi.
                if actualizado:
                    total_pagado_de_modulos = sum(
                        (m.monto_pagado or 0.0) for m in (existing.modulos or [])
                    )
                    if total_pagado_de_modulos > existing.total_pagado:
                        diferencia = total_pagado_de_modulos - existing.total_pagado
                        existing.actualizar_saldo(diferencia)
                    elif total_pagos_a_aplicar > 0:
                        existing.actualizar_saldo(total_pagos_a_aplicar)
                    # F-FIX-MATRICULA: si matricula_pagada=True y no hay modulos
                    # (programa historico SIN modulos), pasar a ACTIVO
                    if (
                        existing.matricula_pagada
                        and (existing.costo_matricula or 0) > 0
                        and (existing.costo_matricula or 0) >= (existing.total_pagado or 0)
                    ):
                        # La matricula cubre el total
                        if existing.estado == EstadoInscripcion.PENDIENTE_PAGO.value:
                            existing.estado = EstadoInscripcion.ACTIVO.value
                    # F-HISTORICO-EXCEL-ESTADO (2026-08-04): si ya pago todo,
                    # pasar de PENDIENTE_PAGO a ACTIVO.
                    if (
                        existing.estado == EstadoInscripcion.PENDIENTE_PAGO.value
                        and existing.esta_completamente_pagado()
                    ):
                        existing.estado = EstadoInscripcion.ACTIVO.value
                    await existing.save()
                return InitialEnrollmentResultado(
                    estudiante_id=est_id_str,
                    success=True,
                    message="Ya estaba inscrito; se actualizaron pagos" if actualizado else "Ya esta inscrito en este curso",
                    enrollment_id=str(existing.id),
                    accion="actualizado" if actualizado else "ya_inscrito",
                )

            # Crear la inscripcion (carga inicial, bypasea validaciones de
            # acepta_inscripciones porque es una operacion administrativa)
            enrollment_in = EnrollmentCreate(
                estudiante_id=student.id,
                curso_id=course.id,
            )
            enrollment = await enrollment_service.create_enrollment(
                enrollment_in=enrollment_in,
                admin_username=current_user.nombre_visible,
                student=student,
                course=course,
                skip_link_updates=True,
            )

            # Marcar la carga inicial (auditoria)
            enrollment.es_carga_inicial = True
            # Si es historico o si el item lo pide, marcar matricula como pagada
            if es_historico or item.matricula_pagada:
                enrollment.matricula_pagada = True
            # F-FIX-DESCUENTO-ITEM (2026-08-05, Kevin): aplicar descuento
            # individual del item al enrollment nuevo. Si el item NO trae
            # descuento, el create_enrollment ya leyo el descuento del CURSO.
            if item.descuento_id is not None or item.descuento_personalizado is not None:
                if item.descuento_id:
                    try:
                        disc = await Discount.get(PydanticObjectId(item.descuento_id))
                        if disc and disc.activo:
                            enrollment.descuento_estudiante_id = disc.id
                            enrollment.descuento_personalizado = float(disc.porcentaje)
                    except Exception:
                        pass
                elif item.descuento_personalizado is not None:
                    enrollment.descuento_estudiante_id = None
                    enrollment.descuento_personalizado = float(item.descuento_personalizado)
                # Recalcular total_a_pagar con la logica MAX
                from services.enrollment_service import _recalcular_total_enrollment
                try:
                    _recalcular_total_enrollment(enrollment, course)
                except Exception:
                    pass
            # Si se especifico modulo inicial (en_ejecucion), marcar ese modulo
            # como "iniciado" para que el dashboard lo muestre en la fase correcta
            if (
                item.modulo_inicial_index is not None
                and enrollment.modulos
                and 0 <= item.modulo_inicial_index < len(enrollment.modulos)
            ):
                # El estudiante arranca a partir de este modulo; los anteriores
                # se marcan como pagados (asumimos que ya los curso).
                # F-FIX-MODULO-INICIAL-ESTADO (2026-08-09, Kevin): tambien
                # actualizar el estado del modulo a "Pagado" (antes solo se
                # seteaba monto_pagado=costo pero el estado quedaba
                # "Pendiente", mostrando inconsistencia en la UI).
                for idx in range(item.modulo_inicial_index):
                    mod = enrollment.modulos[idx]
                    mod.monto_pagado = mod.costo or 0.0
                    if (mod.costo or 0) > 0 and mod.monto_pagado >= (mod.costo or 0) - 0.01:
                        mod.estado = "Pagado"
            # F-HISTORICO-AUTOSERVICIO-EXCEL (2026-08-04): aplicar pagos por
            # modulo del Excel del CPD. Dict {modulo_index_str: monto_pagado}.
            total_pagos_a_aplicar = 0.0
            if item.pagos_modulos and enrollment.modulos:
                for idx_str, monto in item.pagos_modulos.items():
                    try:
                        idx = int(idx_str)
                    except (ValueError, TypeError):
                        continue
                    if 0 <= idx < len(enrollment.modulos):
                        mod = enrollment.modulos[idx]
                        monto_aplicar = float(monto or 0.0)
                        nuevo_pagado = (mod.monto_pagado or 0.0) + monto_aplicar
                        if mod.costo and nuevo_pagado > mod.costo + 0.01:
                            monto_aplicar = max(0.0, mod.costo - (mod.monto_pagado or 0.0))
                            nuevo_pagado = mod.costo
                        mod.monto_pagado = nuevo_pagado
                        if mod.costo and nuevo_pagado >= mod.costo - 0.01:
                            mod.estado = "Pagado"
                        elif nuevo_pagado > 0:
                            mod.estado = "Parcial"
                        total_pagos_a_aplicar += monto_aplicar
            # F-HISTORICO-EXCEL-TOTAL-PAGADO (2026-08-04): recalcular total.
            # F-FIX-MODULO-INICIAL-TOTAL-PAGADO (2026-08-09, Kevin): tambien
            # recalcular cuando se uso modulo_inicial_index (sin pagos_modulos
            # explicitos pero los modulos anteriores quedaron como pagados).
            total_pagado_de_modulos = sum(
                (m.monto_pagado or 0.0) for m in (enrollment.modulos or [])
            )
            if total_pagado_de_modulos > enrollment.total_pagado:
                diferencia = total_pagado_de_modulos - enrollment.total_pagado
                enrollment.actualizar_saldo(diferencia)
            elif total_pagos_a_aplicar > 0 or item.modulo_inicial_index is not None:
                if total_pagado_de_modulos > (enrollment.total_pagado or 0):
                    enrollment.actualizar_saldo(
                        total_pagado_de_modulos - (enrollment.total_pagado or 0)
                    )
            # F-FIX-MATRICULA-NUEVO-ESTADO (2026-08-06, Kevin): si el item
            # marco matricula_pagada=True, tambien hay que sacar al
            # enrollment del estado PENDIENTE_PAGO si ya no hay deuda.
            # Antes SOLO se hacia para existing (linea 510-516) y para
            # pago total (linea 622-626). Esto dejaba a los estudiantes
            # con matricula_pagada=True pero estado=PENDIENTE_PAGO, lo
            # que hacia que la UI mostrara "matricula pendiente" aunque
            # el usuario habia marcado el checkbox.
            if (
                enrollment.matricula_pagada
                and enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO.value
            ):
                # Caso 1: la matricula cubre el total (programa solo con matricula,
                # sin modulos, o matricula = total_a_pagar).
                costo_mat = enrollment.costo_matricula or 0
                total_pag = enrollment.total_pagado or 0
                if costo_mat > 0 and total_pag >= costo_mat - 0.01:
                    enrollment.estado = EstadoInscripcion.ACTIVO.value
                # Caso 2: ya pago todo el programa (incluyendo modulos).
                elif enrollment.esta_completamente_pagado():
                    enrollment.estado = EstadoInscripcion.ACTIVO.value
                # Caso 3: matricula_pagada=True + no hay modulos (programa
                # historico con un solo item "matricula" ya marcado como pagado)
                elif not enrollment.modulos and costo_mat > 0:
                    enrollment.estado = EstadoInscripcion.ACTIVO.value
            # F-HISTORICO-EXCEL-ESTADO (2026-08-04): si ya pago todo, sacar
            # del estado PENDIENTE_PAGO. La UI muestra el badge de la
            # matricula con enrollment.estado, no con matricula_pagada.
            if (
                enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO.value
                and enrollment.esta_completamente_pagado()
            ):
                enrollment.estado = EstadoInscripcion.ACTIVO.value
            await enrollment.save()

            # F-CARGA-RACE-INSCRITOS (2026-08-18): NO tocar course/student aca.
            # Este bloque corre bajo asyncio.gather, y `course` es UN SOLO
            # objeto compartido por todas las tareas. Hacer
            # `course.inscritos.append(...)` + `await course.save()` en
            # paralelo produce perdida de escrituras: dos tareas guardan
            # snapshots distintos del mismo documento y la ultima pisa a la
            # anterior, dejando `course.inscritos` con MENOS estudiantes que
            # los Enrollment realmente creados. Ni Course ni Student declaran
            # `use_revision`, asi que Beanie no detecta el conflicto.
            # El docstring de enrollment_service.create_enrollment ya advertia
            # de esto para `skip_link_updates=True`, y student_service lo
            # resuelve batcheando. Aca se hace igual: se acumula bajo lock y
            # se persiste una sola vez despues del gather.
            async with links_lock:
                inscritos_a_agregar.add(student.id)
                if course.id not in (student.lista_cursos_ids or []):
                    estudiantes_a_vincular.add(student.id)

            return InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=True,
                message="Inscripcion creada como carga inicial",
                enrollment_id=str(enrollment.id),
                accion="creado",
            )
        except ValueError as e:
            return InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=False,
                message=str(e),
                accion="error",
            )
        except Exception as e:
            return InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=False,
                message=f"Error inesperado: {str(e)}",
                accion="error",
            )

    # Procesar items con semaforo para no saturar la BD
    SEM = 5
    sem = asyncio.Semaphore(SEM)

    async def procesar_con_semaforo(item: InitialEnrollmentItem) -> InitialEnrollmentResultado:
        async with sem:
            return await procesar_item(item)

    # asyncio.gather con return_exceptions=True para que un fallo no aborte los demas
    tasks = [procesar_con_semaforo(item) for item in payload.estudiantes]
    results_raw = await asyncio.gather(*tasks, return_exceptions=True)

    # F-CARGA-RACE-INSCRITOS (2026-08-18): persistir las referencias cruzadas
    # acumuladas, ya fuera del contexto concurrente. Dos escrituras en total
    # en vez de dos por estudiante, y sin riesgo de pisarse entre si.
    if inscritos_a_agregar:
        # Releer el curso para no guardar un snapshot viejo: entre que se
        # cargo `course` y ahora, create_enrollment y otros procesos pudieron
        # haberlo modificado. Se re-lee, se agrega lo que falte y se guarda.
        course_fresco = await Course.get(course.id)
        if course_fresco is not None:
            existentes = set(course_fresco.inscritos or [])
            faltantes = inscritos_a_agregar - existentes
            if faltantes:
                course_fresco.inscritos = list(existentes | faltantes)
                await course_fresco.save()

    if estudiantes_a_vincular:
        # AddToSet agrega sin duplicar y sin reescribir el resto de la lista,
        # asi no se pisan otros cursos que el estudiante ya tuviera.
        from beanie.operators import AddToSet
        await Student.find(In(Student.id, list(estudiantes_a_vincular))).update(
            AddToSet({"lista_cursos_ids": course.id})
        )

    for r in results_raw:
        if isinstance(r, Exception):
            fallidos += 1
            resultados.append(InitialEnrollmentResultado(
                estudiante_id="?",
                success=False,
                message=f"Error inesperado: {str(r)}",
                accion="error",
            ))
            continue
        resultados.append(r)
        # F-CARGA-CONTEO-ESTRUCTURADO (2026-08-18): contar por el campo
        # `accion`, no por substrings del mensaje. "actualizado" sigue
        # contando como exitoso (hubo escritura real), igual que antes.
        if r.accion in ("creado", "actualizado"):
            exitosos += 1
        elif r.accion == "ya_inscrito":
            ya_inscritos_count += 1
        else:
            fallidos += 1

    return InitialEnrollmentResponse(
        total_solicitados=len(payload.estudiantes),
        exitosos=exitosos,
        ya_inscritos=ya_inscritos_count,
        fallidos=fallidos,
        resultados=resultados,
    )


class EstadoOverrideRequest(BaseModel):
    estado_override: Optional[str] = Field(
        None,
        description="Override manual del estado. None = volver al cálculo automático. Valores: programado, en_ejecucion, cerrado."
    )


@router.patch(
    "/{id}/estado",
    response_model=CourseResponse,
    summary="F-080: Cambiar override manual del estado (CPD)"
)
async def patch_estado_override(
    id: PydanticObjectId,
    payload: EstadoOverrideRequest,
    current_user: User = Depends(require_cpd)
) -> Any:
    """
    CPD define (o limpia) el override manual del estado de un programa.
    Útil para suspensiones, extensiones o correcciones manuales.
    """
    try:
        course = await course_service.set_estado_override(
            course_id=id,
            estado_override=payload.estado_override,
        )
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put(
    "/{id}/resolucion",
    response_model=CourseResponse,
    summary="F-080: Subir PDF de la resolución de respaldo del programa (CPD)"
)
async def put_resolucion(
    id: PydanticObjectId,
    file: UploadFile = File(..., description="PDF de la resolución"),
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    """
    Sube el PDF de la resolución que respalda el programa y guarda la URL.
    Acepta cualquier hosting (Cloudinary, S3, local). Aquí lo subimos a
    Cloudinary igual que los otros documentos del sistema.

    F-EC-RESOLUCION-REEMPLAZAR (2026-08-18, Kevin en capacitacion): antes
    este endpoint exigia `require_cpd`, lo que dejaba al encargado sin poder
    REEMPLAZAR la resolucion de su propio programa, aunque SI puede subirla
    al crearlo (`POST /courses/upload-resolucion-temp` ya usa
    `require_encargado_curso`) y aunque puede editar el resto del programa
    (`update_course`, FIX-ISSUE-258). Era el mismo documento y la misma
    persona, con dos criterios distintos segun el momento. Se unifica con el
    criterio de update_course: EC/COORD solo sobre sus cursos_asignados.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

    # Mismo control que update_course: el EC/COORD solo toca lo suyo.
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        if id not in (current_user.cursos_asignados or []):
            raise HTTPException(
                status_code=403,
                detail=(
                    "No tienes asignado este programa. Solo puedes subir la "
                    "resolucion de programas en tu lista de cursos asignados."
                ),
            )

    # Subir a Cloudinary (mismo patrón que el resto del sistema)
    try:
        from core.cloudinary_utils import upload_pdf
        url = await upload_pdf(
            file=file,
            folder=f"resoluciones/cursos/{id}",
            public_id=f"curso_{id}",
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error subiendo el PDF a Cloudinary: {str(e)}",
        )

    try:
        course = await course_service.set_resolucion_pdf_url(course_id=id, pdf_url=url)
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post(
    "/",
    response_model=CourseResponse,
    status_code=201,
    summary="Crear Curso"
)
async def create_course(
    *,
    course_in: CourseCreate,
    current_user: User = Depends(require_encargado_curso) # F-2026-08-11-EC-AUTOSERVICIO: cualquier EC/COORD/CPD/ADMIN/SUPERADMIN pueden intentar. Validaciones inline abajo.
) -> Any:
    """Crear nuevo curso.

    F-2026-08-12-EC-RESOLUCION-OBLIGATORIA (Kevin 2026-08-12 post-reunion):
    el EC/COORD/CPD/ADMIN/SUPERADMIN pueden crear los 3 tipos de programas
    (historico, programado/proximo, en ejecucion). La diferencia es la
    resolucion PDF:

    - Historico (es_historico=True): resolucion OPCIONAL. Sirve solo
      como registro/documento de respaldo.
    - Programado/proximo (estado 'proximo'): resolucion OPCIONAL.
    - En ejecucion (estado 'en_ejecucion'): resolucion OBLIGATORIA.
      Sin resolucion NO se puede crear el programa.

    Para subir la resolucion antes de crear el curso, hay un endpoint
    auxiliar `POST /courses/upload-resolucion-temp` que sube el PDF a
    cloudinary y devuelve la URL temporal. El frontend usa esa URL
    en el payload de create_course.
    """
    from core.timezone_utils import utcnow_naive
    from datetime import datetime as _dt

    # F-2026-08-12-EC-RESOLUCION-OBLIGATORIA: validar la resolucion segun
    # el tipo de programa. Si es en_ejecucion, la resolucion_pdf_url
    # debe estar presente (ya sea porque se subio via temp o viene en
    # el payload). Si no, 400 con mensaje claro.
    es_historico_flag = bool(getattr(course_in, "es_historico", False))
    estado_override = getattr(course_in, "estado_override", None)
    resolucion_pdf_url = getattr(course_in, "resolucion_pdf_url", None)

    # Determinar si el programa sera en ejecucion. Miramos estado_override
    # (lo que el usuario eligio en el form) o estado persistido.
    sera_en_ejecucion = (estado_override == "en_ejecucion") and not es_historico_flag

    if sera_en_ejecucion and not resolucion_pdf_url:
        raise HTTPException(
            status_code=400,
            detail=(
                "Para crear un programa EN EJECUCION es obligatorio subir la "
                "resolucion PDF. Usa el endpoint POST /courses/upload-resolucion-temp "
                "para subir el PDF primero, luego pasa la URL devuelta en "
                "resolucion_pdf_url al crear el curso."
            ),
        )

    # F-2026-08-12-EC-HISTORICO-CREAR (Kevin 2026-08-12 post-reunion):
    # cualquier EC puede crear cualquier tipo, pero:
    # - Si es historico (es_historico=True), NO exigimos fecha_fin
    #   (programas del pasado lejano pueden no tener fecha exacta).
    # - Si NO es historico y trae fecha_fin, validamos que sea pasada
    #   (es coherente con que es un programa "historico/cerrado").
    #
    # FIX-ISSUE-251 (2026-08-14): el mensaje era confuso. Ahora claro.
    if not es_historico_flag:
        fecha_fin = getattr(course_in, "fecha_fin", None)
        if fecha_fin is not None:
            if isinstance(fecha_fin, _dt):
                fin_dt = fecha_fin
            else:
                fin_dt = _dt.combine(fecha_fin, _dt.min.time())
            now_naive = utcnow_naive()
            if fin_dt >= now_naive:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        "La fecha_fin debe ser ANTERIOR a hoy cuando el programa "
                        "NO es historico. Tienes 2 opciones: (1) marca es_historico=true "
                        "si es un programa del pasado, o (2) deja fecha_fin null "
                        "o usa una fecha futura si es un programa programado o en ejecucion."
                    ),
                )
    try:
        course = await course_service.create_course(course_in=course_in)
        # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): popular
        # estado_calculado para que el frontend muestre el badge correcto
        # inmediatamente despues de crear.
        course.estado_calculado = course.get_estado_actual()

        # FIX-F-2026-08-12-EC-CREADO-POR (Kevin 2026-08-12): guardar quien
        # creo el programa. Esto se persistia implicitamente en User.cursos_asignados
        # via el auto-asign, pero NO en el Course. Sin este campo no se puede
        # hacer migraciones retroactivas ("asignar a este EC los programas que
        # el creo") ni trazabilidad. Ademas, por seguridad forzamos `activo=True`
        # aunque el frontend mande False: la decision de visibilidad se hace
        # via el flag `es_historico`, no via `activo` (FIX-F-2026-08-12-EC-ACTIVO-HISTORICO).
        # Si en el futuro queremos un flag "inactivo" para archivar manualmente,
        # usamos otro campo dedicado (ej: `archivado`).
        course.creado_por_id = current_user.id
        course.activo = True
        await course.save()

        # F-2026-08-12-EC-AUTOASIGNAR-CURSO (Kevin 2026-08-12 post-reunion):
        # cuando un EC/COORDINADOR crea un programa historico, debe
        # autoasignarse a su lista de cursos_asignados. Asi el programa
        # aparece en sus listados (filtrados por cursos_asignados) y
        # puede cargar estudiantes. Sin esto, el EC crea el programa
        # pero no lo ve nunca.
        if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
            if course.id not in (current_user.cursos_asignados or []):
                current_user.cursos_asignados = (current_user.cursos_asignados or []) + [course.id]
                await current_user.save()

        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# F-2026-08-12-EC-RESOLUCION-OBLIGATORIA (Kevin 2026-08-12 post-reunion):
# el EC decidio que la resolucion PDF es:
# - Historico: OPCIONAL
# - Programado (proximo): OPCIONAL
# - En ejecucion: OBLIGATORIA
# Si no cumple, el programa NO se crea.
# Para resolver esto, agregamos un endpoint de upload TEMPORAL que
# sube el PDF a cloudinary SIN asociarlo a ningun curso. El frontend
# sube el PDF primero, obtiene la URL, y la pasa en el payload de
# create_course. Asi el backend puede validar que para en_ejecucion
# la URL este presente.

@router.post(
    "/upload-resolucion-temp",
    summary="F-2026-08-12-EC-RESOLUCION-OBLIGATORIA: subir PDF de resolucion temporal (sin asociar a curso)",
)
async def upload_resolucion_temp(
    file: UploadFile = File(..., description="PDF de la resolucion"),
    current_user: User = Depends(require_encargado_curso),
) -> Any:
    """
    Sube un PDF de resolucion a cloudinary y devuelve la URL temporal
    (sin asociarla a ningun curso). El frontend usa esta URL al crear
    el curso via POST /courses con resolucion_pdf_url=...

    Para programas en ejecucion la resolucion es OBLIGATORIA (se
    valida en create_course). Para historicos y programados es
    opcional.
    """
    if file.content_type != "application/pdf":
        raise HTTPException(400, "Solo se aceptan archivos PDF")
    try:
        from core.cloudinary_utils import upload_pdf
        # Subir a una carpeta "temp" - no se asocia a ningun curso
        url = await upload_pdf(
            file=file,
            folder="resoluciones/cursos/temp",
            public_id=f"temp_{current_user.id}_{int(datetime.now().timestamp())}",
        )
        return {"url": url}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Error subiendo PDF: {str(e)}")

@router.get(
    "/{id}",
    response_model=CourseResponse,
    summary="Ver Curso"
)
async def read_course(
    *,
    id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user)
) -> Any:
    """Ver detalles de un curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): popular
    # estado_calculado para que el frontend muestre el badge correcto.
    course.estado_calculado = course.get_estado_actual()
    return course

@router.put(
    "/{id}",
    response_model=CourseResponse,
    summary="Actualizar Curso"
)
async def update_course(
    *,
    id: PydanticObjectId,
    course_in: CourseUpdate,
    # FIX-ISSUE-258 (2026-08-14): EC/COORD pueden editar cursos en sus
    # cursos_asignados. CPD/ADMIN/SUPERADMIN editan cualquiera. Validacion
    # inline mas abajo.
    current_user: User = Depends(require_encargado_curso)
) -> Any:
    """Actualizar curso existente.

    FIX-ISSUE-258: EC/COORD pueden editar si curso esta en cursos_asignados.
    """
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")

    # FIX-ISSUE-258: EC solo puede editar cursos en sus cursos_asignados.
    if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        if id not in (current_user.cursos_asignados or []):
            raise HTTPException(
                status_code=403,
                detail=(
                    "No tienes asignado este programa. Solo puedes editar "
                    "programas en tu lista de cursos asignados."
                ),
            )

    try:
        course = await course_service.update_course(course=course, course_in=course_in)
        # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): popular
        # estado_calculado para que el frontend muestre el badge correcto.
        course.estado_calculado = course.get_estado_actual()
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.delete(
    "/{id}",
    response_model=CourseResponse,
    summary="Eliminar Curso"
)
async def delete_course(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_superadmin) # <-- SOLO SUPERADMIN BORRA
) -> Any:
    """Eliminar curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    course = await course_service.delete_course(id=id)
    return course

@router.get(
    "/{id}/students",
    response_model=List[CourseEnrolledStudent],
    summary="Ver Inscritos del Curso"
)
async def get_course_students(
    *,
    id: PydanticObjectId,
    current_user: User = Depends(require_staff) # <-- TODOS LOS ADMINISTRATIVOS VEN EL REPORTE
) -> Any:
    """Reporte detallado de estudiantes inscritos en un curso"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
        
    report = await course_service.get_course_students(course_id=id)
    return report


class EncargadosAssignRequest(BaseModel):
    encargados_ids: List[str] = Field(default_factory=list)

@router.put(
    "/{id}/encargados",
    summary="Asignar encargados a un curso"
)
async def assign_encargados(
    *,
    id: PydanticObjectId,
    payload: EncargadosAssignRequest,
    current_user: User = Depends(require_cpd) # <-- CPD ASIGNA ENCARGADOS
) -> Any:
    """Asignar encargados (Encargado de Curso/Coordinador) a un curso existente."""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
        
    from services.user_service import assign_course_to_users
    try:
        await assign_course_to_users(course_id=id, encargados_ids=payload.encargados_ids)
        return {"success": True, "detail": "Encargados asignados correctamente"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ========================================================================
# NUEVO ENDPOINT (ISSUE R): Obtener Módulos por Docente
# ========================================================================
@router.get(
    "/modules/by-teacher/{teacher_id}",
    summary="Obtener módulos asignados a un docente"
)
async def get_modules_by_teacher(
    *,
    teacher_id: PydanticObjectId,
    current_user: Union[User, Student] = Depends(get_current_user) # <-- PERMISO ABIERTO PARA DOCENTE Y STAFF
) -> Any:
    """
    Obtiene todos los módulos que un docente tiene asignados, iterando sobre los cursos activos.
    """
    # Verificación de seguridad: Evitar que estudiantes vean esto
    if isinstance(current_user, Student):
        raise HTTPException(status_code=403, detail="Acceso denegado para estudiantes.")
        
    # Validar que si es un docente, solo pueda solicitar ver sus PROPIOS módulos
    if current_user.rol.value not in ["superadmin", "admin", "cpd", "mae", "cobranza", "encargado_curso", "coordinador"]:
        if str(current_user.id) != str(teacher_id):
            raise HTTPException(status_code=403, detail="No tienes permisos para ver esta sección administrativa.")

    # Buscamos todos los cursos activos en la base de datos (filtrando para encargados/coordinadores)
    if current_user.rol.value in ["encargado_curso", "coordinador"]:
        if not current_user.cursos_asignados:
            return []
        courses = await Course.find({"_id": {"$in": current_user.cursos_asignados}, "activo": True}).to_list()
    else:
        courses = await Course.find(Course.activo == True).to_list()
    
    assigned_modules = []
    
    for course in courses:
        # Iteramos sobre el array de módulos de cada curso
        for index, module in enumerate(course.modulos):
            # Si el módulo tiene un docente asociado y coincide con el solicitado
            if module.docente_id and str(module.docente_id) == str(teacher_id):
                assigned_modules.append({
                    "curso_id": str(course.id),
                    "curso_nombre": course.nombre_programa,
                    "curso_codigo": course.codigo,
                    "modulo_nombre": module.nombre,
                    "modulo_costo": module.costo,
                    "modulo_index": index + 1
                })
                
    return assigned_modules
