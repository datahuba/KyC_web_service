"""
Servicio de Solicitudes de Inscripción (Enrollment Requests)
===============================================================

Flujo: el Estudiante solicita cursar un programa activo -> se notifica a
CPD/Admin/Superadmin -> CPD aprueba (crea la Enrollment real reutilizando
enrollment_service.create_enrollment, con toda su lógica financiera y de
validación intacta) o rechaza con motivo.

Reutiliza el mismo patrón que passive_request_service.py.
"""

from typing import List, Optional
from datetime import datetime
from beanie import PydanticObjectId

from models.enrollment_request import EnrollmentRequest
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.user import User
from models.enums import UserRole
from schemas.enrollment_request import EnrollmentRequestCreate
from schemas.enrollment import EnrollmentCreate
from services import enrollment_service


async def create_enrollment_request(
    data: EnrollmentRequestCreate,
    current_student: Student
) -> EnrollmentRequest:
    course = await Course.get(data.curso_id)
    if not course:
        raise ValueError("Curso no encontrado")
    if not course.activo:
        raise ValueError("Este curso no está activo actualmente y no acepta solicitudes")

    # No permitir duplicar solicitud pendiente para el mismo curso
    existente = await EnrollmentRequest.find_one(
        EnrollmentRequest.estudiante_id == current_student.id,
        EnrollmentRequest.curso_id == data.curso_id,
        EnrollmentRequest.estado == "pendiente"
    )
    if existente:
        raise ValueError("Ya tienes una solicitud pendiente para este curso")

    # No permitir solicitar si ya está inscrito (activo o cancelado, etc.)
    ya_inscrito = await Enrollment.find_one(
        Enrollment.estudiante_id == current_student.id,
        Enrollment.curso_id == data.curso_id
    )
    if ya_inscrito:
        raise ValueError("Ya tienes una inscripción registrada para este curso")

    solicitud = EnrollmentRequest(
        estudiante_id=current_student.id,
        curso_id=data.curso_id,
        mensaje=(data.mensaje.strip() if data.mensaje else None),
        estado="pendiente"
    )
    await solicitud.insert()

    try:
        from beanie.operators import Or
        from services.notification_service import create_notification

        revisores = await User.find(
            User.activo == True,
            Or(
                User.rol == UserRole.CPD,
                User.rol == UserRole.ADMIN,
                User.rol == UserRole.SUPERADMIN
            )
        ).to_list()

        for revisor in revisores:
            await create_notification(
                destinatario_id=revisor.id,
                tipo_destinatario="user",
                titulo="Nueva Solicitud de Inscripción",
                mensaje=f"{current_student.nombre or current_student.registro} solicitó inscribirse a '{course.nombre_programa}'",
                tipo_alerta="info",
                ruta="/app/enrollment-requests",
                referencia_tipo="enrollment_request",
                referencia_id=solicitud.id
            )
    except Exception as e:
        print(f"Error notificando solicitud de inscripción al CPD: {str(e)}")

    return solicitud


async def get_enrollment_requests(
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20
) -> tuple[List[EnrollmentRequest], int]:
    query_dict = {}
    if estado and estado in ("pendiente", "aprobado", "rechazado"):
        query_dict["estado"] = estado

    total = await EnrollmentRequest.find(query_dict).count()
    skip = (page - 1) * per_page
    items = await EnrollmentRequest.find(query_dict).sort("-created_at").skip(skip).limit(per_page).to_list()
    return items, total


async def get_my_enrollment_requests(estudiante_id: PydanticObjectId) -> List[EnrollmentRequest]:
    """Historial de solicitudes del propio estudiante (para su perfil)."""
    return await EnrollmentRequest.find(
        EnrollmentRequest.estudiante_id == estudiante_id
    ).sort("-created_at").to_list()


async def approve_enrollment_request(request_id: PydanticObjectId, admin_username: str) -> Enrollment:
    solicitud = await EnrollmentRequest.get(request_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise ValueError(f"La solicitud ya fue {solicitud.estado}.")

    # Reutiliza la lógica financiera/validación real de creación de inscripciones
    # (matrícula, descuentos, distribución de módulos) sin duplicarla.
    enrollment = await enrollment_service.create_enrollment(
        enrollment_in=EnrollmentCreate(
            estudiante_id=solicitud.estudiante_id,
            curso_id=solicitud.curso_id
        ),
        admin_username=admin_username
    )

    solicitud.estado = "aprobado"
    solicitud.enrollment_id = enrollment.id
    solicitud.revisado_por = admin_username
    solicitud.fecha_revision = datetime.utcnow()
    await solicitud.save()

    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=solicitud.estudiante_id,
            tipo_destinatario="student",
            titulo="Solicitud de Inscripción Aprobada",
            mensaje="Tu solicitud fue aprobada. Ya puedes ver tu nueva inscripción y proceder con el pago de matrícula.",
            tipo_alerta="success",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando aprobación de inscripción al estudiante: {str(e)}")

    return enrollment


async def reject_enrollment_request(
    request_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> EnrollmentRequest:
    solicitud = await EnrollmentRequest.get(request_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise ValueError(f"La solicitud ya fue {solicitud.estado}.")

    solicitud.estado = "rechazado"
    solicitud.motivo_rechazo = motivo
    solicitud.revisado_por = admin_username
    solicitud.fecha_revision = datetime.utcnow()
    await solicitud.save()

    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=solicitud.estudiante_id,
            tipo_destinatario="student",
            titulo="Solicitud de Inscripción Rechazada",
            mensaje=f"Tu solicitud fue rechazada. Motivo: {motivo}",
            tipo_alerta="error",
            ruta="/app/dashboard",
            referencia_tipo="enrollment_request",
            referencia_id=solicitud.id
        )
    except Exception as e:
        print(f"Error notificando rechazo de inscripción: {str(e)}")

    return solicitud
