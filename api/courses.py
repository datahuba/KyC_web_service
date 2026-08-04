from typing import List, Any, Union, Optional, Dict
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
from models.enums import UserRole
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
                    ok = await send_email(st.email, f"{asunto} · {nombre_programa}", html)
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
    current_user: Union[User, Student] = Depends(get_current_user) # Abierto para todos
) -> Any:
    """Listar cursos con paginación y filtros"""
    courses, total_count = await course_service.get_courses(
        page=page,
        per_page=per_page,
        q=q,
        activo=activo,
        tipo_curso=tipo_curso,
        modalidad=modalidad,
        estado=estado,
    )

    total_pages = math.ceil(total_count / per_page) if total_count > 0 else 0

    return {
        "data": courses,
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


class InitialEnrollmentRequest(BaseModel):
    """Lista de estudiantes a inscribir como carga inicial del programa."""
    estudiantes: List[InitialEnrollmentItem] = Field(..., min_length=1, max_length=200)


class InitialEnrollmentResultado(BaseModel):
    """Resultado de inscribir a un estudiante en la carga inicial."""
    estudiante_id: str
    success: bool
    message: str
    enrollment_id: Optional[str] = None


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

    # 1. Verificar permisos del encargado_curso
    if (
        current_user.rol == UserRole.ENCARGADO_CURSO
        and id not in (current_user.cursos_asignados or [])
    ):
        raise HTTPException(
            status_code=403,
            detail="No tienes asignado este curso (encargado_curso).",
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

    for item in payload.estudiantes:
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
                ya_inscritos_count += 1
                resultados.append(InitialEnrollmentResultado(
                    estudiante_id=est_id_str,
                    success=False,
                    message="Ya esta inscrito en este curso",
                    enrollment_id=str(existing.id),
                ))
                continue

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
            # Si se especifico modulo inicial (en_ejecucion), marcar ese modulo
            # como "iniciado" para que el dashboard lo muestre en la fase correcta
            if (
                item.modulo_inicial_index is not None
                and enrollment.modulos
                and 0 <= item.modulo_inicial_index < len(enrollment.modulos)
            ):
                # El estudiante arranca a partir de este modulo; los anteriores
                # se marcan como pagados (asumimos que ya los curso)
                for idx in range(item.modulo_inicial_index):
                    enrollment.modulos[idx].monto_pagado = (
                        enrollment.modulos[idx].costo or 0.0
                    )
            # F-HISTORICO-AUTOSERVICIO-EXCEL (2026-08-04): aplicar pagos por
            # modulo del Excel del CPD. Dict {modulo_index_str: monto_pagado}.
            # Se actualiza monto_pagado y estado (Pagado si cubre el costo,
            # Parcial si no). NO sobreescribe pagos mayores ya registrados.
            if item.pagos_modulos and enrollment.modulos:
                for idx_str, monto in item.pagos_modulos.items():
                    try:
                        idx = int(idx_str)
                    except (ValueError, TypeError):
                        continue
                    if 0 <= idx < len(enrollment.modulos):
                        mod = enrollment.modulos[idx]
                        # Acumular (no sobreescribir): si Excel dice 294 pero
                        # ya habia 100, queda 394 (cap al costo)
                        nuevo_pagado = (mod.monto_pagado or 0.0) + float(monto or 0.0)
                        if mod.costo and nuevo_pagado > mod.costo + 0.01:
                            nuevo_pagado = mod.costo
                        mod.monto_pagado = nuevo_pagado
                        # Estado segun cobertura
                        if mod.costo and nuevo_pagado >= mod.costo - 0.01:
                            mod.estado = "Pagado"
                        elif nuevo_pagado > 0:
                            mod.estado = "Parcial"
            await enrollment.save()

            # Batch update de referencias cruzadas
            if course.id not in student.lista_cursos_ids:
                student.lista_cursos_ids.append(course.id)
                await student.save()
            if student.id not in course.inscritos:
                course.inscritos.append(student.id)
                await course.save()

            exitosos += 1
            resultados.append(InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=True,
                message="Inscripcion creada como carga inicial",
                enrollment_id=str(enrollment.id),
            ))
        except ValueError as e:
            fallidos += 1
            resultados.append(InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=False,
                message=str(e),
            ))
        except Exception as e:
            fallidos += 1
            resultados.append(InitialEnrollmentResultado(
                estudiante_id=est_id_str,
                success=False,
                message=f"Error inesperado: {str(e)}",
            ))

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
    current_user: User = Depends(require_cpd)
) -> Any:
    """
    Sube el PDF de la resolución que respalda el programa y guarda la URL.
    Acepta cualquier hosting (Cloudinary, S3, local). Aquí lo subimos a
    Cloudinary igual que los otros documentos del sistema.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF")

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
    current_user: User = Depends(require_cpd) # F-HISTORICO-AUTOSERVICIO (2026-08-04): Kevin decidio SOLO CPD y SUPERADMIN pueden crear. Inline check abajo porque require_cpd tambien permite ADMIN.
) -> Any:
    """Crear nuevo curso.

    F-HISTORICO-AUTOSERVICIO (2026-08-04): Kevin decidio que SOLO CPD y SUPERADMIN
    pueden crear programas. El dep `require_cpd` permite CPD, ADMIN y SUPERADMIN,
    asi que hacemos un check inline adicional para BLOQUEAR a ADMIN.
    Encargado_curso, coordinador, cobranza, docente, estudiante → 403.
    """
    # F-HISTORICO-AUTOSERVICIO: check inline para SOLO CPD y SUPERADMIN (no ADMIN)
    if current_user.rol not in (UserRole.CPD, UserRole.SUPERADMIN):
        raise HTTPException(
            status_code=403,
            detail="Solo CPD o superadmin pueden crear programas.",
        )
    try:
        course = await course_service.create_course(course_in=course_in)
        return course
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    current_user: User = Depends(require_cpd) # <-- CPD EDITA LOS PROGRAMAS
) -> Any:
    """Actualizar curso existente"""
    course = await course_service.get_course(id=id)
    if not course:
        raise HTTPException(status_code=404, detail="Curso no encontrado")
    try:
        course = await course_service.update_course(course=course, course_in=course_in)
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
