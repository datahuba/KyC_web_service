"""
Servicio de Solicitudes de Estado Pasivo (Passive Requests)
=============================================================

Flujo: solicitud (Encargado de Curso / CPD-Admin / Estudiante propio) ->
notificación al CPD -> aprobación (Enrollment pasa a SUSPENDIDO) o rechazo.
Reutiliza el mismo patrón que account_request_service.py.
"""

from typing import List, Optional, Union
from datetime import datetime
from beanie import PydanticObjectId

from models.passive_request import PassiveRequest
from models.enrollment import Enrollment
from models.student import Student
from models.user import User
from models.enums import EstadoInscripcion, UserRole
from schemas.passive_request import PassiveRequestCreate


def _validar_autorizacion_solicitante(enrollment: Enrollment, current_user: Union[User, Student]) -> None:
    """
    Valida si current_user puede solicitar el pasivo de esta inscripción.
    Lanza ValueError si no está autorizado (Requirement 2).
    """
    if isinstance(current_user, Student):
        if enrollment.estudiante_id != current_user.id:
            raise ValueError("No puedes solicitar el pasivo de una inscripción que no es tuya")
        return

    if isinstance(current_user, User):
        if current_user.rol in (UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN):
            return
        if current_user.rol == UserRole.ENCARGADO_CURSO:
            if enrollment.curso_id not in current_user.cursos_asignados:
                raise ValueError("No tienes asignado este curso")
            return
        raise ValueError("Tu rol no está autorizado para solicitar el pasivo de una inscripción")

    raise ValueError("Tipo de usuario no reconocido")


async def create_passive_request(
    data: PassiveRequestCreate,
    current_user: Union[User, Student]
) -> PassiveRequest:
    enrollment = await Enrollment.get(data.enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")

    if enrollment.estado not in (EstadoInscripcion.ACTIVO, EstadoInscripcion.PENDIENTE_PAGO):
        raise ValueError(
            f"No se puede solicitar el pasivo de una inscripción en estado '{enrollment.estado.value}'"
        )

    _validar_autorizacion_solicitante(enrollment, current_user)

    existente = await PassiveRequest.find_one(
        PassiveRequest.enrollment_id == data.enrollment_id,
        PassiveRequest.estado == "pendiente"
    )
    if existente:
        raise ValueError("Ya existe una solicitud de pasivo pendiente para esta inscripción")

    solicitante_tipo = "student" if isinstance(current_user, Student) else "user"

    solicitud = PassiveRequest(
        enrollment_id=data.enrollment_id,
        solicitante_id=current_user.id,
        solicitante_tipo=solicitante_tipo,
        motivo=data.motivo.strip(),
        respaldo_url=data.respaldo_url,
        estado="pendiente"
    )
    try:
        await solicitud.insert()
    except Exception as e:
        # AUDITORÍA (MEDIO #10): el check "existente" de arriba no es atómico
        # (find + insert por separado); dos requests casi simultáneas podían
        # pasar ambas ese check. El índice único parcial del modelo es la
        # protección real; aquí solo se traduce el DuplicateKeyError de Mongo
        # a un mensaje de negocio consistente con el check manual de arriba.
        if "duplicate key" in str(e).lower() or "E11000" in str(e):
            raise ValueError("Ya existe una solicitud de pasivo pendiente para esta inscripción")
        raise

    # Notificar a todo el personal CPD/Admin/Superadmin activo (mismo patrón que AccountRequest)
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

        nombre_solicitante = getattr(current_user, "nombre_funcional", None) or getattr(current_user, "username", None) or getattr(current_user, "nombre", "Usuario")

        for revisor in revisores:
            await create_notification(
                destinatario_id=revisor.id,
                tipo_destinatario="user",
                titulo="Nueva Solicitud de Estado Pasivo",
                mensaje=f"{nombre_solicitante} solicitó pausar la inscripción {enrollment.id}. Motivo: {solicitud.motivo}",
                tipo_alerta="info",
                ruta="/app/passive-requests",
                referencia_tipo="passive_request",
                referencia_id=solicitud.id
            )
    except Exception as e:
        print(f"Error notificando solicitud de pasivo al CPD: {str(e)}")

    return solicitud


async def get_passive_requests(
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20
) -> tuple[List[PassiveRequest], int]:
    query_dict = {}
    if estado and estado in ("pendiente", "aprobado", "rechazado"):
        query_dict["estado"] = estado

    total = await PassiveRequest.find(query_dict).count()
    skip = (page - 1) * per_page
    items = await PassiveRequest.find(query_dict).sort("-created_at").skip(skip).limit(per_page).to_list()
    return items, total


async def approve_passive_request(request_id: PydanticObjectId, admin_username: str) -> Enrollment:
    solicitud = await PassiveRequest.get(request_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise ValueError(f"La solicitud ya fue {solicitud.estado}.")

    enrollment = await Enrollment.get(solicitud.enrollment_id)
    if not enrollment:
        raise ValueError("La inscripción asociada ya no existe")

    enrollment.estado = EstadoInscripcion.SUSPENDIDO
    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()

    solicitud.estado = "aprobado"
    solicitud.revisado_por = admin_username
    solicitud.fecha_revision = datetime.utcnow()
    await solicitud.save()

    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Tu curso quedó en pausa",
            mensaje="Tu inscripción fue puesta en estado pasivo. Contacta al CPD si tienes dudas sobre cómo reincorporarte.",
            tipo_alerta="warning",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando aprobación de pasivo al estudiante: {str(e)}")

    return enrollment


async def reject_passive_request(
    request_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> PassiveRequest:
    solicitud = await PassiveRequest.get(request_id)
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
        destinatario_id = solicitud.solicitante_id
        tipo_destinatario = solicitud.solicitante_tipo
        await create_notification(
            destinatario_id=destinatario_id,
            tipo_destinatario=tipo_destinatario,
            titulo="Solicitud de Estado Pasivo Rechazada",
            mensaje=f"Tu solicitud fue rechazada. Motivo: {motivo}",
            tipo_alerta="error",
            ruta="/app/enrollments",
            referencia_tipo="passive_request",
            referencia_id=solicitud.id
        )
    except Exception as e:
        print(f"Error notificando rechazo de pasivo: {str(e)}")

    return solicitud


async def reactivate_enrollment(enrollment_id: PydanticObjectId, admin_username: str) -> Enrollment:
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")
    if enrollment.estado != EstadoInscripcion.SUSPENDIDO:
        raise ValueError("Solo se pueden reactivar inscripciones en estado pasivo (SUSPENDIDO)")

    enrollment.estado = (
        EstadoInscripcion.ACTIVO if enrollment.matricula_pagada else EstadoInscripcion.PENDIENTE_PAGO
    )
    enrollment.updated_at = datetime.utcnow()
    await enrollment.save()

    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Tu curso fue reactivado",
            mensaje="Tu inscripción volvió a estar activa. ¡Bienvenido/a de nuevo!",
            tipo_alerta="success",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando reactivación: {str(e)}")

    return enrollment
