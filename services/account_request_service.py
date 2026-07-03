"""
Servicio de Solicitudes de Cuenta (Account Requests)
====================================================

Flujo: solicitud pública -> notificación al CPD -> aprobación (crea Student) o rechazo.
"""

from typing import List, Optional
from datetime import datetime
from beanie import PydanticObjectId
from beanie.operators import Or

from models.account_request import AccountRequest
from models.student import Student
from models.enums import UserRole
from schemas.account_request import AccountRequestCreate


async def create_account_request(data: AccountRequestCreate) -> AccountRequest:
    """Registrar una solicitud pública y notificar al personal CPD."""
    email_norm = data.email.strip().lower()
    carnet_norm = data.carnet.strip()

    # 1. Evitar solicitudes duplicadas pendientes con el mismo email o carnet
    existing_request = await AccountRequest.find_one(
        AccountRequest.estado == "pendiente",
        Or(AccountRequest.email == email_norm, AccountRequest.carnet == carnet_norm)
    )
    if existing_request:
        raise ValueError(
            "Ya existe una solicitud pendiente con ese correo o carnet. "
            "Por favor espera la revisión del personal académico (CPD)."
        )

    # 2. Evitar solicitar si ya existe un estudiante con ese carnet o email
    existing_student = await Student.find_one(
        Or(Student.carnet == carnet_norm, Student.email == email_norm)
    )
    if existing_student:
        raise ValueError(
            "Ya existe una cuenta registrada con ese carnet o correo. "
            "Si olvidaste tu acceso, contacta al CPD."
        )

    solicitud = AccountRequest(
        nombre=data.nombre.strip(),
        email=email_norm,
        carnet=carnet_norm,
        celular=data.celular,
        registro=data.registro.strip() if data.registro else None,
        es_estudiante_interno=data.es_estudiante_interno,
        mensaje=data.mensaje.strip() if data.mensaje else None,
        estado="pendiente"
    )
    await solicitud.insert()

    # 3. Notificar a todo el personal CPD (y administración) para su revisión
    try:
        from models.user import User
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
                titulo="Nueva Solicitud de Cuenta",
                mensaje=f"{solicitud.nombre} (CI: {solicitud.carnet}) solicitó una cuenta de estudiante. Requiere tu revisión y aprobación.",
                tipo_alerta="info",
                ruta="/app/account-requests",
                referencia_tipo="account_request",
                referencia_id=solicitud.id
            )
    except Exception as e:
        print(f"Error notificando solicitud de cuenta al CPD: {str(e)}")

    return solicitud


async def get_account_requests(
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20
) -> tuple[List[AccountRequest], int]:
    """Listar solicitudes (para el CPD), con filtro opcional por estado."""
    query_dict = {}
    if estado and estado in ("pendiente", "aprobado", "rechazado"):
        query_dict["estado"] = estado

    total = await AccountRequest.find(query_dict).count()
    skip = (page - 1) * per_page
    items = await AccountRequest.find(query_dict).sort("-created_at").skip(skip).limit(per_page).to_list()
    return items, total


async def get_pending_count() -> int:
    return await AccountRequest.find(AccountRequest.estado == "pendiente").count()


async def approve_account_request(request_id: PydanticObjectId, admin_username: str) -> Student:
    """Aprobar la solicitud: crea el Student y marca la solicitud como aprobada."""
    from core.security import get_password_hash

    solicitud = await AccountRequest.get(request_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise ValueError(f"La solicitud ya fue {solicitud.estado}.")

    registro_final = solicitud.registro or solicitud.carnet

    # Validar unicidad antes de crear el estudiante
    existing = await Student.find_one(
        Or(
            Student.registro == registro_final,
            Student.carnet == solicitud.carnet,
            Student.email == solicitud.email
        )
    )
    if existing:
        raise ValueError(
            "No se puede aprobar: ya existe un estudiante con ese registro, carnet o correo."
        )

    student = Student(
        registro=registro_final,
        password=get_password_hash(solicitud.carnet),  # contraseña inicial = carnet
        nombre=solicitud.nombre,
        email=solicitud.email,
        carnet=solicitud.carnet,
        celular=solicitud.celular,
        es_estudiante_interno=solicitud.es_estudiante_interno,
        activo=True,
        lista_cursos_ids=[]
    )
    await student.insert()

    solicitud.estado = "aprobado"
    solicitud.revisado_por = admin_username
    solicitud.fecha_revision = datetime.utcnow()
    solicitud.estudiante_id = student.id
    await solicitud.save()

    # Nota: la verificación por correo al estudiante queda pendiente (ISSUE-A-VERIFICACION).
    return student


async def reject_account_request(
    request_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> AccountRequest:
    solicitud = await AccountRequest.get(request_id)
    if not solicitud:
        raise ValueError("Solicitud no encontrada")
    if solicitud.estado != "pendiente":
        raise ValueError(f"La solicitud ya fue {solicitud.estado}.")

    solicitud.estado = "rechazado"
    solicitud.motivo_rechazo = motivo
    solicitud.revisado_por = admin_username
    solicitud.fecha_revision = datetime.utcnow()
    await solicitud.save()
    return solicitud
