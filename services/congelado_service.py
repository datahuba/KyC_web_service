"""
Servicio de Congelamiento y Abandono (ISSUE-P-CONGELADO / ISSUE-R-NOTIFICACION-MORA)
=====================================================================================

Flujo de negocio (UAGRM):
- Congelamiento VOLUNTARIO: el estudiante/CPD solicita pausar los estudios pagando
  una tasa fija (TASA_CONGELAMIENTO_BS). Reutiliza EstadoInscripcion.SUSPENDIDO
  (igual que ISSUE-R-SOLICITUD-PASIVO) pero con motivo_suspension='congelado'.
- Notificación PREVENTIVA de mora (ISSUE-R-NOTIFICACION-MORA): a los
  DIAS_INACTIVIDAD_MORA sin pagos aprobados, se notifica al Encargado de Curso
  (o CPD si no hay ninguno asignado a ese curso) para que haga seguimiento
  humano ANTES de que el sistema actúe. Se marca mora_notificada=True para no
  spamear en cada corrida del job.
- Abandono AUTOMÁTICO: a los DIAS_INACTIVIDAD_ABANDONO sin pagos aprobados (y sin
  que nadie haya intervenido), el sistema marca la inscripción como SUSPENDIDO
  con motivo_suspension='abandono' y deja pendiente la multa de reincorporación
  (MULTA_REINCORPORACION_BS) para cuando el estudiante decida volver.

Ninguna de estas acciones toca pagos históricos ni altera saldos/deudas ya
calculados; solo cambian el estado académico y dejan trazabilidad.
"""

from datetime import datetime, timedelta
from core.timezone_utils import utcnow_naive
from typing import List, Optional
from beanie import PydanticObjectId
from beanie.operators import Or

from models.enrollment import Enrollment
from models.payment import Payment
from models.student import Student
from models.user import User
from models.enums import EstadoInscripcion, EstadoPago, UserRole
from models.notification_events import EventoNotificacion
from core.config import settings


async def _ultima_actividad_pago(enrollment: Enrollment) -> datetime:
    """
    Fecha del último pago APROBADO de la inscripción (fecha_verificacion).
    Si nunca pagó nada, usa fecha_inscripcion como punto de partida.
    """
    ultimo_pago = await Payment.find(
        Payment.inscripcion_id == enrollment.id,
        Payment.estado_pago == EstadoPago.APROBADO
    ).sort("-fecha_verificacion").limit(1).to_list()

    if ultimo_pago and ultimo_pago[0].fecha_verificacion:
        return ultimo_pago[0].fecha_verificacion
    return enrollment.fecha_inscripcion


async def congelar_inscripcion(
    enrollment_id: PydanticObjectId,
    registrado_por: str,
    tasa_pagada: bool = True
) -> Enrollment:
    """
    Congelamiento VOLUNTARIO de estudios. Requiere estado ACTIVO o
    PENDIENTE_PAGO. Registra la tasa (por defecto asumida pagada al
    momento de congelar; si se factura por separado, marcar False y
    actualizar luego).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")

    if enrollment.estado not in (EstadoInscripcion.ACTIVO, EstadoInscripcion.PENDIENTE_PAGO):
        raise ValueError(f"No se puede congelar una inscripción en estado '{enrollment.estado.value}'")

    enrollment.estado = EstadoInscripcion.SUSPENDIDO
    enrollment.motivo_suspension = "congelado"
    enrollment.fecha_congelamiento = utcnow_naive()
    enrollment.tasa_congelamiento_pagada = tasa_pagada
    enrollment.updated_at = utcnow_naive()
    await enrollment.save()

    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Tus estudios fueron congelados",
            mensaje=f"Tu inscripción fue congelada correctamente. Tasa de congelamiento: Bs. {settings.TASA_CONGELAMIENTO_BS}.",
            tipo_alerta="warning",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando congelamiento: {str(e)}")

    return enrollment


async def reactivar_desde_congelado_o_abandono(enrollment_id: PydanticObjectId, admin_username: str) -> Enrollment:
    """
    Reactiva una inscripción SUSPENDIDA por congelamiento o abandono.
    Si el motivo fue 'abandono', deja constancia de que la multa de
    reincorporación (MULTA_REINCORPORACION_BS) queda pendiente de cobro
    (no se genera un Payment automático; Cobranza la registra manualmente
    igual que cualquier otro cobro, para no inventar dinero fantasma en caja).
    """
    enrollment = await Enrollment.get(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")

    if enrollment.estado != EstadoInscripcion.SUSPENDIDO:
        raise ValueError("Solo se pueden reactivar inscripciones en estado SUSPENDIDO")

    if enrollment.motivo_suspension == "abandono":
        enrollment.multa_reincorporacion_pendiente = True

    enrollment.estado = (
        EstadoInscripcion.ACTIVO if enrollment.matricula_pagada else EstadoInscripcion.PENDIENTE_PAGO
    )
    enrollment.motivo_suspension = None
    enrollment.mora_notificada = False
    enrollment.updated_at = utcnow_naive()
    await enrollment.save()

    try:
        from services.notification_service import create_notification
        mensaje = "Tu inscripción volvió a estar activa. ¡Bienvenido/a de nuevo!"
        if enrollment.multa_reincorporacion_pendiente:
            mensaje += f" Recuerda que corresponde la multa de reincorporación de Bs. {settings.MULTA_REINCORPORACION_BS}."
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Tu curso fue reactivado",
            mensaje=mensaje,
            tipo_alerta="success",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando reactivación: {str(e)}")

    return enrollment


async def _notificar_mora_preventiva(enrollment: Enrollment) -> None:
    """
    ISSUE-R-NOTIFICACION-MORA: notifica al Encargado de Curso asignado a este
    curso (o a todo el personal CPD/Admin/Superadmin si no hay ninguno
    específico) para seguimiento humano ANTES de marcar abandono automático.
    """
    from services.notification_service import create_notification

    encargados = await User.find(
        User.activo == True,
        User.rol == UserRole.ENCARGADO_CURSO,
        User.cursos_asignados == enrollment.curso_id
    ).to_list()

    destinatarios = encargados
    if not destinatarios:
        destinatarios = await User.find(
            User.activo == True,
            Or(User.rol == UserRole.CPD, User.rol == UserRole.ADMIN, User.rol == UserRole.SUPERADMIN)
        ).to_list()

    student = await Student.get(enrollment.estudiante_id)
    nombre_estudiante = student.nombre if student else "un estudiante"

    for dest in destinatarios:
        try:
            await create_notification(
                destinatario_id=dest.id,
                tipo_destinatario="user",
                titulo="Alerta preventiva de mora",
                mensaje=(
                    f"{nombre_estudiante} lleva {settings.DIAS_INACTIVIDAD_MORA}+ días sin registrar pagos "
                    f"en su inscripción. Verifica si sigue asistiendo antes de que el sistema marque abandono "
                    f"automático a los {settings.DIAS_INACTIVIDAD_ABANDONO} días."
                ),
                tipo_alerta="warning",
                ruta="/app/enrollments",
                referencia_tipo="enrollment",
                referencia_id=enrollment.id,
                evento=EventoNotificacion.ALERTA_MORA,
            )
        except Exception as e:
            print(f"Error notificando mora preventiva: {str(e)}")

    # F-NOTIF-ESTUDIANTE (Kevin 2026-08-17): el estudiante TAMBIEN se entera.
    #
    # Antes esta alerta iba solo al encargado. El resultado era que el unico
    # que no sabia que estaba por caer en abandono automatico era justamente
    # el que podia evitarlo pagando. Es la brecha mas clara que aparecio al
    # revisar los 33 puntos donde se notifica.
    if student:
        try:
            await create_notification(
                destinatario_id=student.id,
                tipo_destinatario="student",
                titulo="Tu inscripción necesita atención",
                mensaje=(
                    f"Pasaron más de {settings.DIAS_INACTIVIDAD_MORA} días sin que registres "
                    f"un pago en tu inscripción. Si ya pagaste, subí tu comprobante; si "
                    f"tenés una dificultad, acercate a la Unidad de Postgrado antes de que "
                    f"pasen {settings.DIAS_INACTIVIDAD_ABANDONO} días."
                ),
                tipo_alerta="warning",
                ruta="/app/payments",
                referencia_tipo="enrollment",
                referencia_id=enrollment.id,
                evento=EventoNotificacion.ALERTA_MORA,
            )
        except Exception as e:
            print(f"Error notificando mora preventiva al estudiante: {str(e)}")

    enrollment.mora_notificada = True
    enrollment.updated_at = utcnow_naive()
    await enrollment.save()


async def _marcar_abandono_automatico(enrollment: Enrollment) -> None:
    """Abandono automático: último recurso tras DIAS_INACTIVIDAD_ABANDONO sin pagos."""
    from services.notification_service import create_notification

    enrollment.estado = EstadoInscripcion.SUSPENDIDO
    enrollment.motivo_suspension = "abandono"
    enrollment.fecha_abandono = utcnow_naive()
    enrollment.updated_at = utcnow_naive()
    await enrollment.save()

    try:
        await create_notification(
            destinatario_id=enrollment.estudiante_id,
            tipo_destinatario="student",
            titulo="Inscripción marcada como abandono",
            mensaje=(
                f"Detectamos {settings.DIAS_INACTIVIDAD_ABANDONO}+ días sin pagos registrados en tu inscripción "
                f"y fue marcada como abandono. Para reincorporarte, contacta al CPD "
                f"(aplica multa de reincorporación de Bs. {settings.MULTA_REINCORPORACION_BS})."
            ),
            tipo_alerta="error",
            ruta="/app/enrollments",
            referencia_tipo="enrollment",
            referencia_id=enrollment.id
        )
    except Exception as e:
        print(f"Error notificando abandono automático: {str(e)}")


async def verificar_inactividad_pagos(enrollment_ids: Optional[List[PydanticObjectId]] = None) -> dict:
    """
    Job periódico (ISSUE-P-CONGELADO + ISSUE-R-NOTIFICACION-MORA). Recorre
    inscripciones ACTIVO/PENDIENTE_PAGO con saldo pendiente y aplica:
    - >= DIAS_INACTIVIDAD_MORA sin pago y aún no notificado -> notifica y marca mora_notificada.
    - >= DIAS_INACTIVIDAD_ABANDONO sin pago -> abandono automático (último recurso).

    Args:
        enrollment_ids: si se provee, acota la revisión SOLO a esos IDs (en vez
            de recorrer toda la base). Pensado para pruebas aisladas y para que
            CPD pueda re-verificar una inscripción puntual sin correr el job
            completo sobre todos los estudiantes reales.

    Retorna un resumen para logging/endpoint manual de disparo.
    """
    ahora = utcnow_naive()
    filtros = [
        Or(Enrollment.estado == EstadoInscripcion.ACTIVO, Enrollment.estado == EstadoInscripcion.PENDIENTE_PAGO),
        Enrollment.saldo_pendiente > 0
    ]
    if enrollment_ids:
        filtros.append({"_id": {"$in": enrollment_ids}})

    candidatas = await Enrollment.find(*filtros).to_list()

    notificadas = 0
    abandonadas = 0

    for enrollment in candidatas:
        ultima_actividad = await _ultima_actividad_pago(enrollment)
        dias_inactivo = (ahora - ultima_actividad).days

        if dias_inactivo >= settings.DIAS_INACTIVIDAD_ABANDONO:
            await _marcar_abandono_automatico(enrollment)
            abandonadas += 1
        elif dias_inactivo >= settings.DIAS_INACTIVIDAD_MORA and not enrollment.mora_notificada:
            await _notificar_mora_preventiva(enrollment)
            notificadas += 1

    return {
        "revisadas": len(candidatas),
        "notificadas_mora": notificadas,
        "marcadas_abandono": abandonadas,
        "ejecutado_en": ahora.isoformat()
    }
