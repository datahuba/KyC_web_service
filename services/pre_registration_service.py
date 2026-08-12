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
        # F-2026-08-11-CAMPOS-EC: campos educación continua (planilla de Lisa).
        # Se persisten en el data dict y se copian al Student al aprobar.
        "registro_universitario": (data.registro_universitario or "").strip() or None,
        "avance_academico_codigo": data.avance_academico_codigo,
        "formulario_descuento_numero": data.formulario_descuento_numero,
        "carrera_codigo": (data.carrera_codigo or "").strip() or None,
        "descuento_porcentaje": data.descuento_porcentaje,
        # F-2026-08-11-CAMPOS-EC-MODALIDAD (reunion UAGRM 2026-08-11, seccion 4):
        # procedencia (codigo departamento) + modalidad (presencial/virtual)
        # + carta_firmada_url (URL del PDF firmado por el director).
        "procedencia": (data.procedencia or "").strip().upper() or None,
        "modalidad": (data.modalidad or "").strip().lower() or None,
        "carta_firmada_url": (data.carta_firmada_url or "").strip() or None,
        # F-2026-08-11-CAMPOS-EC-RESOLUCION (Kevin 22:37): la resolucion del
        # programa es OPCIONAL pero se persiste aca para que el admin la vea
        # al aprobar y la copie a Course.resolucion_pdf_url.
        "resolucion_url": (data.resolucion_url or "").strip() or None,
        # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12): discriminacion
        # primera carrera vs profesional con titulo. es_primer_carrera default
        # True (mas seguro, cobra menos si no se sabe). titulo_profesional_url
        # es OBLIGATORIO si es_primer_carrera=False (validado en el schema).
        "es_primer_carrera": bool(data.es_primer_carrera) if data.es_primer_carrera is not None else True,
        "titulo_profesional_url": (data.titulo_profesional_url or "").strip() or None,
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
    con_descuento: bool = False,
) -> Tuple[List[PreRegistration], int]:
    """Lista submissions visibles para el usuario actual.

    F-2026-08-12-DESCUENTOS-TAB (Kevin 2026-08-12 post-reunion): si
    `con_descuento=True`, filtra a submissions que propusieron descuento
    de vicerrectorado (> 0). Usado por la pestana "Descuentos" del panel
    de pre-registros para que el EC tenga una vista unificada de todos
    los descuentos pendientes/aprobados/rechazados.
    """
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
    # F-2026-08-12-DESCUENTOS-TAB: filtro para que la pestana "Descuentos"
    # muestre solo submissions con descuento propuesto > 0.
    if con_descuento:
        sub_query["data.descuento_porcentaje"] = {"$gt": 0}

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
        # F-2026-08-11-CAMPOS-EC: campos específicos educación continua
        # (planilla de Lisa). Se persisten desde el data dict del form
        # si el estudiante los lleno al pre-registrarse.
        registro_universitario=(data.get("registro_universitario") or None),
        avance_academico_codigo=data.get("avance_academico_codigo") or None,
        formulario_descuento_numero=data.get("formulario_descuento_numero") or None,
        carrera_codigo=(data.get("carrera_codigo") or None),
        descuento_porcentaje=data.get("descuento_porcentaje") or None,
        # F-2026-08-11-CAMPOS-EC-MODALIDAD (reunion UAGRM 2026-08-11, seccion 4).
        procedencia=(data.get("procedencia") or None),
        modalidad=(data.get("modalidad") or None),
        carta_firmada_url=(data.get("carta_firmada_url") or None),
        # F-2026-08-11-CAMPOS-EC-RESOLUCION (Kevin 22:37).
        resolucion_url=(data.get("resolucion_url") or None),
        # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12): discriminacion
        # primera carrera vs profesional con titulo. se persiste tal cual
        # el data dict (que ya fue validado en el schema).
        es_primer_carrera=bool(data.get("es_primer_carrera", True)),
        titulo_profesional_url=(data.get("titulo_profesional_url") or None),
        titulo_profesional_estado="pendiente",  # el encargado EC lo valida despues
        # F-2026-08-12-DESCUENTO-BECA-VALIDACION (Kevin 2026-08-12, post-reunion):
        # Si el estudiante propuso un descuento (campo descuentoPorcentaje del
        # wizard, 0-100%), se persiste como descuento_vicerrectorado_monto
        # (convertido a 0-1) con estado "pendiente". El encargado EC debe
        # validarlo explicitamente despues (mismo patron que el titulo).
        # Si rechazo: el estudiante sigue matriculado pero se cobra el modulo
        # completo (sin descuento).
        # Si no propuso descuento: queda en "no_aplica".
        descuento_vicerrectorado_monto=(
            float(data.get("descuentoPorcentaje") or data.get("descuento_porcentaje") or 0) / 100.0
            if (data.get("descuentoPorcentaje") or data.get("descuento_porcentaje"))
            else None
        ),
        descuento_vicerrectorado_estado=(
            "pendiente"
            if (data.get("descuentoPorcentaje") or data.get("descuento_porcentaje"))
            else "no_aplica"
        ),
    )
    await student.insert()

    # Marcar la submission como aprobada
    sub.estado = "aprobado"
    sub.revisado_por = admin_username
    sub.fecha_revision = utcnow_naive()
    sub.migrated_to_student_id = student.id
    await sub.save()

    # F-2026-08-12-PRE-INSCRIPCION-AUTO-ENROLL (Kevin 2026-08-12 post-reunion):
    # al aprobar una pre-inscripcion, ademas de crear el Student, inscribirlo
    # automaticamente en el programa del formulario. Asi el estudiante
    # aparece inmediatamente en la lista de inscritos del programa y el
    # panel /app/inscripciones lo muestra sin tener que hacer
    # Inscripcion Individual manual.
    #
    # Solo se crea el Enrollment (sin pagos), porque Kevin decidio que los
    # pagos se confirman despues del pago real (no se asume que el
    # estudiante ya pago). El Enrollment queda en PENDIENTE_PAGO.
    #
    # Si el form no tiene programa_id o el curso esta cerrado, NO se
    # falla el approve (solo se loguea warning). El estudiante queda
    # creado, pero sin inscripcion. El EC puede inscribirlo manualmente
    # despues desde Inscripcion Individual.
    if sub.form_id:
        try:
            from models.pre_registration import PreRegistrationForm
            from schemas.enrollment import EnrollmentCreate
            from services import enrollment_service

            form = await PreRegistrationForm.get(sub.form_id)
            if form and form.programa_id:
                try:
                    # Reutilizamos el service de enrollment, que ya calcula
                    # matricula diferenciada (primer carrera vs profesional),
                    # descuentos, requisitos, modulos, etc.
                    enrollment_in = EnrollmentCreate(
                        estudiante_id=student.id,
                        curso_id=form.programa_id,
                        # NO pasamos descuento_id ni descuento_personalizado
                        # porque la pre-inscripcion usa el campo
                        # descuento_porcentaje del Student (que se valida
                        # por separado en el modal "Validar descuento").
                    )
                    await enrollment_service.create_enrollment(
                        enrollment_in=enrollment_in,
                        admin_username=admin_username,
                        student=student,
                    )
                except ValueError as ve:
                    # El curso esta cerrado/inactivo, o ya esta inscrito, etc.
                    # No fallamos el approve, solo logueamos.
                    print(
                        f"[pre-registration] No se pudo inscribir automáticamente "
                        f"al estudiante {student.nombre} en el programa {form.programa_id}: {ve}"
                    )
        except Exception as e:
            # Cualquier error inesperado en la inscripcion NO debe tumbar el
            # approve (el Student ya esta creado). Logueamos y seguimos.
            print(
                f"[pre-registration] Error inesperado inscribiendo automáticamente "
                f"al estudiante {student.id} en el programa del form {sub.form_id}: {e}"
            )

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
# F-2026-08-12-DESCUENTO-BECA-VALIDACION (Kevin 2026-08-12, post-reunion
# UAGRM): el descuento de vicerrectorado que el estudiante propuso en el
# wizard NO se aplica automaticamente al aprobar la pre-inscripcion. Queda
# en estado "pendiente" y el encargado EC debe aprobarlo o rechazarlo
# explicitamente desde el panel. Si se rechaza, el estudiante sigue
# matriculado pero se cobra el modulo completo (sin descuento).
# ============================================================================

async def aprobar_descuento_vicerrectorado(student_id: PydanticObjectId) -> Student:
    """
    Aprueba el descuento de vicerrectorado de un estudiante. El descuento
    ya debio haber sido propuesto al aprobar la submission (estado
    "pendiente"). Si no hay descuento propuesto, lanza ValueError.

    F-2026-08-12-DESCUENTO-RECALC (Kevin 2026-08-12 post-reunion B1):
    ademas de cambiar el estado a 'aprobado', recalcula el `total_a_pagar`
    del Enrollment activo del estudiante aplicando el descuento SOLO a:
    - Modulos no pagados (los ya pagados conservan su costo original)
    - Monto restante despues de la matricula (la matricula ya se cobro
      al aprobar la pre-inscripcion, no se toca)

    Asi, si el estudiante ya pago la matricula de 200 Bs y le aprueban
    un descuento del 50% sobre los 3000 Bs de colegiatura, su nuevo
    `total_a_pagar` = 200 + 1500 = 1700 Bs (en lugar de 200 + 3000 = 3200).
    """
    from models.enrollment import Enrollment
    from models.enums import EstadoInscripcion

    student = await Student.get(student_id)
    if not student:
        raise ValueError("Estudiante no encontrado.")
    if (
        student.descuento_vicerrectorado_monto is None
        or student.descuento_vicerrectorado_estado == "no_aplica"
    ):
        raise ValueError(
            "El estudiante no propuso un descuento de vicerrectorado. "
            "Solo se puede validar un descuento pendiente de aprobacion."
        )
    student.descuento_vicerrectorado_estado = "aprobado"
    student.descuento_vicerrectorado_motivo_rechazo = None
    await student.save()

    # F-2026-08-12-DESCUENTO-RECALC: recalcular total_a_pagar del Enrollment
    # activo (si existe) aplicando el descuento. Si no hay enrollment todavia
    # (caso raro donde se aprobo descuento antes de aprobar submission), no
    # hay nada que recalcular: cuando se apruebe la submission, el Enrollment
    # se creara con el descuento aplicado via el campo descuento_curso.
    descuento_pct = float(student.descuento_vicerrectorado_monto or 0.0)
    if descuento_pct <= 0:
        return student

    enrollment = await Enrollment.find_one(
        Enrollment.estudiante_id == student_id,
        Enrollment.estado != EstadoInscripcion.CANCELADO,
    )
    if not enrollment:
        return student

    # Aplicar el descuento SOLO a los modulos no pagados.
    # La matricula NO se modifica (ya fue cobrada al aprobar la submission).
    ahorro_total = 0.0
    for mod in (enrollment.modulos or []):
        if mod.estado == "Pagado":
            continue
        costo_original = float(mod.costo or 0.0)
        if costo_original <= 0:
            continue
        descuento_aplicado = round(costo_original * descuento_pct, 2)
        # El costo del modulo es lo que el estudiante DEBE pagar (no el original).
        # Actualizar `costo` baja el monto pendiente; mantener `costo_original`
        # para auditoria (campo nuevo si se quiere agregar en el futuro).
        mod.costo = round(costo_original - descuento_aplicado, 2)
        ahorro_total += descuento_aplicado

    # Recalcular total_a_pagar: matricula + modulos (con descuento aplicado)
    # NO tocar total_pagado (lo ya pagado se respeta).
    if ahorro_total > 0:
        total_modulos_nuevo = sum(float(m.costo or 0.0) for m in (enrollment.modulos or []))
        costo_matricula = float(getattr(enrollment, "costo_matricula", 0) or 0)
        enrollment.total_a_pagar = round(costo_matricula + total_modulos_nuevo, 2)
        # saldo_pendiente se mantiene derivado (Pydantic validator lo calcula)
        enrollment.saldo_pendiente = max(
            0.0, enrollment.total_a_pagar - float(enrollment.total_pagado or 0)
        )
        # Anotar el descuento aplicado en el snapshot del enrollment para
        # que sea visible en listados y reportes. Usamos descuento_personalizado
        # (que ya existe) para representar el % del vicerrectorado.
        from models.enrollment import Enrollment as _E
        enrollment.descuento_personalizado = descuento_pct * 100
        await enrollment.save()

    return student


async def rechazar_descuento_vicerrectorado(
    student_id: PydanticObjectId,
    motivo: str,
) -> Student:
    """
    Rechaza el descuento de vicerrectorado. El estudiante sigue matriculado
    pero se cobra el modulo completo (sin descuento). El motivo se guarda
    para trazabilidad.
    """
    student = await Student.get(student_id)
    if not student:
        raise ValueError("Estudiante no encontrado.")
    if (
        student.descuento_vicerrectorado_monto is None
        or student.descuento_vicerrectorado_estado == "no_aplica"
    ):
        raise ValueError(
            "El estudiante no propuso un descuento de vicerrectorado. "
            "Solo se puede rechazar un descuento pendiente de aprobacion."
        )
    motivo_clean = (motivo or "").strip()
    if len(motivo_clean) < 3:
        raise ValueError(
            "Para rechazar el descuento debes indicar un motivo de al menos 3 caracteres."
        )
    student.descuento_vicerrectorado_estado = "rechazado"
    student.descuento_vicerrectorado_motivo_rechazo = motivo_clean
    await student.save()
    return student


# ============================================================================
# Métricas (para badges y dashboard)
# ============================================================================

async def get_forms_counters(current_user: User) -> dict:
    """Conteos globales (para badges en sidebar).

    F-2026-08-11-EC-FIX-COUNTERS-403: encargado_curso y coordinador ven
    solo counts de SUS cursos asignados. Antes este service no recibia
    el user y retornaba el total global (lo que hacia parecer a un EC
    que tenia 0 submissions cuando en realidad tenia 5 en su curso).

    F-2026-08-12-DESCUENTOS-TAB (Kevin 2026-08-12): nuevo campo
    `descuentos_pendientes` = submissions con descuento propuesto > 0
    que aun NO fueron migradas a Student o que fueron migradas pero el
    descuento sigue en estado 'pendiente'. Usado para el badge de la
    pestana "Descuentos".
    """
    # F-2026-08-11-EC-FIX-COUNTERS-403: set de form_ids visibles
    form_query: dict = {}
    if current_user.rol == UserRole.CPD:
        form_query = {"programa_id": None}
    elif current_user.rol in (UserRole.ENCARGADO_CURSO, UserRole.COORDINADOR):
        cursos = current_user.cursos_asignados or []
        if not cursos:
            return {
                "forms_total": 0,
                "forms_activos": 0,
                "submissions_pendientes": 0,
                "descuentos_pendientes": 0,
            }
        form_query = {"programa_id": {"$in": cursos}}
    elif current_user.rol not in (UserRole.SUPERADMIN, UserRole.ADMIN):
        return {
            "forms_total": 0,
            "forms_activos": 0,
            "submissions_pendientes": 0,
            "descuentos_pendientes": 0,
        }

    forms_total = await PreRegistrationForm.find(form_query).count()
    forms_activos = await PreRegistrationForm.find(
        form_query, PreRegistrationForm.estado == "activo"
    ).count()

    form_ids = [f.id for f in await PreRegistrationForm.find(form_query).to_list()]
    if not form_ids:
        return {
            "forms_total": forms_total,
            "forms_activos": forms_activos,
            "submissions_pendientes": 0,
            "descuentos_pendientes": 0,
        }

    # Submissions pendientes (estado=submission)
    subs_pendientes = await PreRegistration.find(
        PreRegistration.form_id.in_(form_ids),  # type: ignore
        PreRegistration.estado == "pendiente",
    ).count()

    # F-2026-08-12-DESCUENTOS-TAB: submissions con descuento propuesto > 0
    # que aun requieren accion del EC (estado 'pendiente' o 'aprobado').
    # Excluimos las rechazadas (ya fueron revisadas).
    descuentos_pendientes = await PreRegistration.find(
        PreRegistration.form_id.in_(form_ids),  # type: ignore
        PreRegistration.estado.in_(["pendiente", "aprobado"]),  # type: ignore
        {"data.descuento_porcentaje": {"$gt": 0}},
    ).count()

    return {
        "forms_total": forms_total,
        "forms_activos": forms_activos,
        "submissions_pendientes": subs_pendientes,
        "descuentos_pendientes": descuentos_pendientes,
    }
