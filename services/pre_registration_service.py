"""
Servicio de Pre-registro de Estudiantes
=======================================

Flujo:
  1. Super admin crea PreRegistrationForm (slug + programa + vigencia)
  2. Visitante envía POST público al form por slug → crea PreRegistration
  3. CPD (form general) o Encargado de Curso / Coordinador (form por programa)
     revisa la PreRegistration desde el panel
  4. Al aprobar: se crea un Student + User con la convención 'Uagrm.<CI>'
     y se le envía un email de bienvenida con su contraseña inicial
"""

import math
import re
from datetime import datetime
from typing import List, Optional, Tuple
from beanie import PydanticObjectId
from beanie.operators import Or, In

from core.timezone_utils import utcnow_naive
from core.security import get_password_hash
from models.pre_registration import PreRegistrationForm, PreRegistration
from models.student import Student
from models.user import User
from models.course import Course
from models.enums import UserRole
from schemas.pre_registration import (
    PreRegistrationFormCreate,
    PreRegistrationFormUpdate,
    PreRegistrationSubmit,
)


# ============================================================================
# FORM TEMPLATE (admin)
# ============================================================================

async def create_form(data: PreRegistrationFormCreate, admin_username: str) -> PreRegistrationForm:
    """Crear un nuevo formulario. Solo super admin."""
    # Validar que el slug no exista
    existing = await PreRegistrationForm.find_one(PreRegistrationForm.slug == data.slug)
    if existing:
        raise ValueError(f"Ya existe un formulario con el slug '{data.slug}'. Elegí otro.")

    # Validar que el programa exista (si fue dado)
    programa_oid = None
    if data.programa_id:
        try:
            programa_oid = PydanticObjectId(data.programa_id)
        except Exception:
            raise ValueError("El ID del programa no es un ObjectId válido.")
        programa = await Course.get(programa_oid)
        if not programa:
            raise ValueError(f"No existe un curso con id {data.programa_id}.")

    form = PreRegistrationForm(
        nombre=data.nombre.strip(),
        slug=data.slug,
        descripcion=data.descripcion.strip() if data.descripcion else None,
        programa_id=programa_oid,
        fecha_inicio=data.fecha_inicio,
        fecha_fin=data.fecha_fin,
        estado="activo",
        created_by=admin_username,
    )
    await form.insert()
    return form


async def update_form(form_id: PydanticObjectId, data: PreRegistrationFormUpdate) -> PreRegistrationForm:
    """Actualizar un formulario existente. Solo super admin."""
    form = await PreRegistrationForm.get(form_id)
    if not form:
        raise ValueError("Formulario no encontrado.")

    payload = data.model_dump(exclude_unset=True)
    if "programa_id" in payload:
        if payload["programa_id"] is None:
            form.programa_id = None
        else:
            try:
                programa_oid = PydanticObjectId(payload["programa_id"])
            except Exception:
                raise ValueError("El ID del programa no es un ObjectId válido.")
            programa = await Course.get(programa_oid)
            if not programa:
                raise ValueError(f"No existe un curso con id {payload['programa_id']}.")
            form.programa_id = programa_oid

    for field in ("nombre", "descripcion", "fecha_inicio", "fecha_fin", "estado"):
        if field in payload:
            value = payload[field]
            if isinstance(value, str) and field in ("nombre", "descripcion"):
                value = value.strip() or None
            setattr(form, field, value)

    # Coherencia de fechas si se actualizaron ambas
    if form.fecha_fin <= form.fecha_inicio:
        raise ValueError("La fecha de fin debe ser posterior a la fecha de inicio.")

    await form.save()
    return form


async def get_forms_for_admin(
    current_user: User,
    page: int = 1,
    per_page: int = 20
) -> Tuple[List[PreRegistrationForm], int]:
    """
    Lista formularios visibles para el usuario actual:
    - superadmin: ve TODOS
    - cpd: ve los generales (programa_id is None) y los que tienen como
      "responsable" CPD (no aplica por ahora, así que solo los generales)
    - encargado_curso / coordinador: ve los delegados a sus cursos_asignados
    - admin: ve todos (como superadmin pero sin permisos de crear/eliminar)
    """
    query: dict = {}
    if current_user.rol == UserRole.CPD:
        query = {"programa_id": None}
    elif current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos_permitidos = current_user.cursos_asignados or []
        if not cursos_permitidos:
            return [], 0
        query = {"programa_id": {"$in": cursos_permitidos}}
    elif current_user.rol not in (UserRole.SUPERADMIN, UserRole.ADMIN):
        return [], 0

    total = await PreRegistrationForm.find(query).count()
    skip = (page - 1) * per_page
    items = await PreRegistrationForm.find(query).sort("-created_at").skip(skip).limit(per_page).to_list()
    return items, total


async def get_form_by_id(form_id: PydanticObjectId) -> Optional[PreRegistrationForm]:
    return await PreRegistrationForm.get(form_id)


async def delete_form(form_id: PydanticObjectId) -> None:
    """Eliminar un formulario. Solo super admin.

    BUG-PRE-002: solo bloquea si hay submissions con estado='pendiente'
    (las únicas que aún esperan revisión). Las aprobadas y rechazadas son
    data histórica — al eliminar el form, se eliminan en cascada.

    Pendientes → BLOQUEAN (probablemente data importante, esperar revisión)
    Aprobadas   → NO bloquean, se eliminan en cascada
    Rechazadas  → NO bloquean, se eliminan en cascada
    """
    form = await PreRegistrationForm.get(form_id)
    if not form:
        raise ValueError("Formulario no encontrado.")

    # Contar pendientes (las únicas que bloquean)
    pending_count = await PreRegistration.find(
        PreRegistration.form_id == form_id,
        PreRegistration.estado == "pendiente",
    ).count()
    if pending_count > 0:
        raise ValueError(
            f"No se puede eliminar: el formulario tiene {pending_count} submission(s) pendiente(s) de revisar. "
            "Aprobá o rechazá esas submissions primero, o cerrá el formulario en vez de eliminarlo."
        )

    # Contar submissions históricas (aprobadas + rechazadas) — se eliminarán en cascada
    historical_count = await PreRegistration.find(
        PreRegistration.form_id == form_id,
        PreRegistration.estado != "pendiente",
    ).count()

    # Eliminar submissions históricas en cascada
    if historical_count > 0:
        await PreRegistration.find(
            PreRegistration.form_id == form_id,
        ).delete()

    await form.delete()


# ============================================================================
# SUBMISSION PÚBLICO (sin auth)
# ============================================================================

async def get_public_form_by_slug(slug: str) -> PreRegistrationForm:
    """Obtener un formulario por slug para la página pública. Valida que esté abierto."""
    form = await PreRegistrationForm.find_one(PreRegistrationForm.slug == slug)
    if not form:
        raise ValueError("Formulario no encontrado.")
    if form.estado != "activo":
        raise ValueError("Este formulario ya fue cerrado por el administrador.")
    now = utcnow_naive()
    if now < form.fecha_inicio:
        raise ValueError("Este formulario aún no está disponible. Vuelve más tarde.")
    if now > form.fecha_fin:
        raise ValueError("La fecha límite para llenar este formulario ya pasó.")
    return form


async def submit_public_form(slug: str, data: PreRegistrationSubmit) -> PreRegistration:
    """Registrar una submission pública."""
    form = await get_public_form_by_slug(slug)  # ya valida abierto/en ventana

    carnet = data.carnet.strip()
    email = data.email.strip().lower()

    # Evitar duplicados: si ya existe un Student con ese carnet o email, no permitir
    existing_student = await Student.find_one(
        Or(Student.carnet == carnet, Student.email == email)
    )
    if existing_student:
        raise ValueError(
            "Ya existe una cuenta registrada con ese carnet o correo. "
            "Si olvidaste tu acceso, contacta al CPD."
        )

    # Si el visitante llena el mismo carnet/email dos veces para el mismo form, también bloqueamos
    existing_sub = await PreRegistration.find_one(
        PreRegistration.form_id == form.id,
        PreRegistration.data.carnet == carnet,
        PreRegistration.estado == "pendiente"
    )
    if existing_sub:
        raise ValueError(
            "Ya enviaste una solicitud con ese carnet para este formulario. "
            "Espera la revisión del equipo académico."
        )

    # Normalizar fecha de nacimiento: aceptar DD/MM/AAAA o YYYY-MM-DD
    fecha_nac_iso = None
    if data.fecha_nacimiento:
        raw = data.fecha_nacimiento.strip()
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", raw)
        if m:
            dd, mm, yyyy = m.groups()
            fecha_nac_iso = f"{yyyy}-{mm}-{dd}"
        else:
            fecha_nac_iso = raw  # ya viene en ISO o se rechaza por Pydantic

    payload = {
        "nombre": data.nombre.strip(),
        "email": email,
        "carnet": carnet,
        "extension": (data.extension or "").strip().upper() or None,
        "celular": data.celular.strip(),
        "fecha_nacimiento": fecha_nac_iso,
        "sexo": data.sexo,
        "domicilio": (data.domicilio or "").strip() or None,
        "mensaje": (data.mensaje or "").strip() or None,
    }

    sub = PreRegistration(
        form_id=form.id,
        data=payload,
        estado="pendiente",
    )
    await sub.insert()

    # Notificar al revisor: si es por programa, al Encargado/Coord; si es general, a CPD
    try:
        from services.notification_service import create_notification
        revisores: list[User] = []
        if form.programa_id is not None:
            # Encargados/Coordinadores del programa
            users = await User.find(
                User.activo == True,
                In(User.rol, [UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR, UserRole.ADMIN, UserRole.SUPERADMIN]),
                In(User.cursos_asignados, [form.programa_id])
            ).to_list()
            revisores = users
        else:
            # Generales: CPD + admin + superadmin
            users = await User.find(
                User.activo == True,
                In(User.rol, [UserRole.CPD, UserRole.ADMIN, UserRole.SUPERADMIN])
            ).to_list()
            revisores = users

        for r in revisores:
            await create_notification(
                destinatario_id=r.id,
                tipo_destinatario="user",
                titulo="Nueva Pre-inscripción",
                mensaje=f"{payload['nombre']} (CI: {payload['carnet']}) se pre-inscribió en '{form.nombre}'. Requiere tu revisión.",
                tipo_alerta="info",
                ruta="/app/pre-registros",
                referencia_tipo="pre_registration",
                referencia_id=sub.id,
            )
    except Exception as e:
        print(f"[pre-registration] Error notificando revisores: {e}")

    return sub


# ============================================================================
# SUBMISSIONS ADMIN (lista / aprobación / rechazo)
# ============================================================================

async def get_submissions_for_admin(
    current_user: User,
    form_id: Optional[str] = None,
    estado: Optional[str] = None,
    page: int = 1,
    per_page: int = 20,
) -> Tuple[List[PreRegistration], int]:
    """Lista submissions visibles para el usuario actual."""
    # Primero, set de form_ids visibles
    form_query: dict = {}
    if current_user.rol == UserRole.CPD:
        form_query = {"programa_id": None}
    elif current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        if not cursos:
            return [], 0
        form_query = {"programa_id": {"$in": cursos}}
    elif current_user.rol not in (UserRole.SUPERADMIN, UserRole.ADMIN):
        return [], 0

    # Si se filtró por form_id, validar que el form sea visible
    if form_id:
        try:
            form_oid = PydanticObjectId(form_id)
        except Exception:
            return [], 0
        form = await PreRegistrationForm.get(form_oid)
        if not form:
            return [], 0
        # Chequear visibilidad del form individual contra el rol
        if current_user.rol == UserRole.CPD and form.programa_id is not None:
            return [], 0
        if current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
            cursos = current_user.cursos_asignados or []
            if form.programa_id not in cursos:
                return [], 0
        form_query = {"_id": form_oid}

    form_ids = [f.id for f in await PreRegistrationForm.find(form_query).to_list()]
    form_ids_oid = form_ids
    if not form_ids_oid:
        return [], 0

    sub_query: dict = {"form_id": {"$in": form_ids_oid}}
    if estado and estado in ("pendiente", "aprobado", "rechazado"):
        sub_query["estado"] = estado

    total = await PreRegistration.find(sub_query).count()
    skip = (page - 1) * per_page
    items = await PreRegistration.find(sub_query).sort("-created_at").skip(skip).limit(per_page).to_list()
    return items, total


async def approve_submission(submission_id: PydanticObjectId, admin_username: str) -> Student:
    """
    Aprobar: crea Student + User con la convención 'Uagrm.<CI>' y envía
    email de bienvenida con la contraseña inicial.
    """
    sub = await PreRegistration.get(submission_id)
    if not sub:
        raise ValueError("Pre-inscripción no encontrada.")
    if sub.estado != "pendiente":
        raise ValueError(f"La pre-inscripción ya fue {sub.estado}.")

    data = sub.data
    carnet = (data.get("carnet") or "").strip()
    email = (data.get("email") or "").strip().lower()
    nombre = (data.get("nombre") or "").strip()

    if not carnet or not email or not nombre:
        raise ValueError("La pre-inscripción no tiene los datos mínimos (nombre, email, carnet).")

    # Doble check: no crear duplicados
    existing = await Student.find_one(
        Or(Student.carnet == carnet, Student.email == email)
    )
    if existing:
        raise ValueError(
            "No se puede aprobar: ya existe un estudiante con ese carnet o correo."
        )

    # Crear el Student
    initial_password_plain = f"Uagrm.{carnet}"
    student = Student(
        registro=carnet,  # usar CI como registro por defecto
        password=get_password_hash(initial_password_plain),
        nombre=nombre,
        email=email,
        carnet=carnet,
        extension=data.get("extension"),
        celular=data.get("celular"),
        domicilio=data.get("domicilio"),
        fecha_nacimiento=(
            datetime.fromisoformat(data["fecha_nacimiento"])
            if data.get("fecha_nacimiento") else None
        ),
        sexo=data.get("sexo"),
        activo=True,
        lista_cursos_ids=[],
    )
    await student.insert()

    # Marcar la submission como aprobada
    sub.estado = "aprobado"
    sub.revisado_por = admin_username
    sub.fecha_revision = utcnow_naive()
    sub.migrated_to_student_id = student.id
    await sub.save()

    # Email de bienvenida con contraseña inicial (best-effort, no bloqueante)
    try:
        from core.config import settings
        from core.email_utils import send_email, build_welcome_pre_registration_email

        html = build_welcome_pre_registration_email(
            nombre=nombre,
            carnet=carnet,
            initial_password=initial_password_plain,
            login_url=f"{settings.FRONTEND_URL.rstrip('/')}/auth/sign-in",
        )
        await send_email(
            email,
            "Bienvenido a Posgrado UAGRM - Tus credenciales de acceso",
            html,
        )
    except Exception as e:
        print(f"[pre-registration] Error enviando email de bienvenida: {e}")

    return student


async def reject_submission(
    submission_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> PreRegistration:
    sub = await PreRegistration.get(submission_id)
    if not sub:
        raise ValueError("Pre-inscripción no encontrada.")
    if sub.estado != "pendiente":
        raise ValueError(f"La pre-inscripción ya fue {sub.estado}.")

    sub.estado = "rechazado"
    sub.motivo_rechazo = motivo
    sub.revisado_por = admin_username
    sub.fecha_revision = utcnow_naive()
    await sub.save()
    return sub


# ============================================================================
# Métricas (para badges y dashboard)
# ============================================================================

async def get_forms_counters() -> dict:
    """Conteos globales (para badges en sidebar)."""
    forms_total = await PreRegistrationForm.find().count()
    forms_activos = await PreRegistrationForm.find(PreRegistrationForm.estado == "activo").count()
    subs_pendientes = await PreRegistration.find(PreRegistration.estado == "pendiente").count()
    return {
        "forms_total": forms_total,
        "forms_activos": forms_activos,
        "submissions_pendientes": subs_pendientes,
    }
