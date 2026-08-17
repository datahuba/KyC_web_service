"""
Servicio de correo con registro, prioridad y control de cupo
===========================================================

F-CORREOS-REGISTRO (Kevin 2026-08-17).

Por que existe: Brevo en el plan gratis admite 300 correos por dia y solo
los estudiantes ya son 305. Un comunicado masivo agota el dia entero, y
hasta ahora el correo numero 301 simplemente se perdia sin dejar rastro.

Kevin decidio quedarse en el plan gratis y **priorizar los correos con las
credenciales de los estudiantes** (los del formulario de preinscripcion).
La razon es concreta: ese correo lleva el usuario y la contraseña inicial,
asi que si no llega, el alumno no puede entrar al sistema. Un recordatorio
de pago que se atrasa un dia es una molestia; una credencial que no llega
es un alumno bloqueado.

Como se traduce eso en codigo:

  - Cada correo declara su PRIORIDAD.
  - Antes de enviar se cuenta cuantos salieron hoy.
  - Los CRITICOS tienen cupo reservado: se mandan aunque el dia este casi
    agotado.
  - Los no criticos, si no hay cupo, quedan ENCOLADOS para el dia siguiente
    en vez de perderse.
  - Todo queda registrado en `email_logs`, salga bien o mal.

El reintento de los encolados y fallidos lo hace `procesar_pendientes()`.
"""

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional

from beanie import PydanticObjectId

from core.config import settings
from core.email_utils import send_email as _send_email_smtp
from models.email_log import EmailLog, EstadoEmail, PrioridadEmail

logger = logging.getLogger(__name__)


# ========================================================================
# Tipos de flujo (que correo es)
# ========================================================================
# Se listan explicitamente para poder filtrar en el panel y para que quede
# claro cual es critico y cual no.

class TipoEmail:
    CREDENCIALES_PREINSCRIPCION = "credenciales_preinscripcion"
    RESET_PASSWORD = "reset_password"
    VERIFICACION_EMAIL = "verificacion_email"
    INSCRIPCION_APROBADA = "inscripcion_aprobada"
    PAGO_APROBADO = "pago_aprobado"
    NOTA_VALIDADA = "nota_validada"
    RECORDATORIO_PAGO = "recordatorio_pago"
    COMUNICADO = "comunicado"
    PRE_REGISTRO_RECIBIDO = "pre_registro_recibido"
    OTRO = "otro"


# Prioridad por defecto de cada flujo. Kevin fue explicito con el primero.
PRIORIDAD_POR_TIPO = {
    # Sin esto el alumno NO puede entrar al sistema.
    TipoEmail.CREDENCIALES_PREINSCRIPCION: PrioridadEmail.CRITICA,
    TipoEmail.RESET_PASSWORD: PrioridadEmail.CRITICA,

    TipoEmail.VERIFICACION_EMAIL: PrioridadEmail.ALTA,
    TipoEmail.INSCRIPCION_APROBADA: PrioridadEmail.ALTA,
    TipoEmail.PAGO_APROBADO: PrioridadEmail.ALTA,
    TipoEmail.PRE_REGISTRO_RECIBIDO: PrioridadEmail.ALTA,

    TipoEmail.NOTA_VALIDADA: PrioridadEmail.NORMAL,
    TipoEmail.RECORDATORIO_PAGO: PrioridadEmail.NORMAL,
    TipoEmail.COMUNICADO: PrioridadEmail.NORMAL,
    TipoEmail.OTRO: PrioridadEmail.NORMAL,
}

# Tras 5 intentos fallidos se descarta: si el correo esta mal escrito o el
# buzon no existe, reintentar para siempre solo gasta cupo del dia.
MAX_INTENTOS = 5


def _inicio_del_dia_utc() -> datetime:
    """
    Comienzo del dia en hora de Bolivia (UTC-4), expresado en UTC.

    Importa: el tope de Brevo es por dia calendario, y si se contara por dia
    UTC el cupo se reiniciaria a las 20:00 hora local, en pleno horario de
    uso de la unidad.
    """
    ahora_bolivia = datetime.now(timezone.utc) - timedelta(hours=4)
    inicio_bolivia = datetime.combine(ahora_bolivia.date(), time.min)
    return inicio_bolivia.replace(tzinfo=timezone.utc) + timedelta(hours=4)


async def enviados_hoy() -> int:
    """Cuantos correos acepto SMTP en el dia (hora de Bolivia)."""
    return await EmailLog.find(
        {
            "estado": EstadoEmail.ENVIADO,
            "fecha_envio": {"$gte": _inicio_del_dia_utc()},
        }
    ).count()


async def cupo_disponible(prioridad: str) -> int:
    """
    Cuantos correos mas se pueden mandar hoy con esa prioridad.

    Los criticos usan la cuota completa; el resto se detiene antes, dejando
    intacto el colchon reservado. Asi un comunicado masivo no puede dejar sin
    cupo a las credenciales de un alumno que se preinscribe esa misma tarde.
    """
    usados = await enviados_hoy()
    if prioridad == PrioridadEmail.CRITICA:
        tope = settings.EMAIL_CUOTA_DIARIA
    else:
        tope = settings.EMAIL_CUOTA_DIARIA - settings.EMAIL_CUPO_RESERVADO_CRITICOS
    return max(0, tope - usados)


async def enviar(
    *,
    destinatario: str,
    asunto: str,
    html: str,
    tipo: str = TipoEmail.OTRO,
    prioridad: Optional[str] = None,
    destinatario_id: Optional[PydanticObjectId] = None,
    destinatario_nombre: Optional[str] = None,
) -> EmailLog:
    """
    Registra y (si hay cupo) envia un correo.

    SIEMPRE devuelve el EmailLog, incluso si no se envio: el que llama puede
    mirar `.estado` para saber que paso. Nunca lanza por un fallo de SMTP —
    que no salga un correo no debe romper el flujo de negocio que lo
    disparo (aprobar un pago, inscribir a alguien).
    """
    if prioridad is None:
        prioridad = PRIORIDAD_POR_TIPO.get(tipo, PrioridadEmail.NORMAL)

    log = EmailLog(
        destinatario=(destinatario or "").strip(),
        asunto=asunto,
        cuerpo_html=html,
        tipo=tipo,
        prioridad=prioridad,
        destinatario_id=destinatario_id,
        destinatario_nombre=destinatario_nombre,
        estado=EstadoEmail.ENCOLADO,
    )

    if not log.destinatario:
        log.estado = EstadoEmail.DESCARTADO
        log.error = "El destinatario no tiene email cargado."
        await log.create()
        logger.warning("[EMAIL] descartado sin destinatario: tipo=%s", tipo)
        return log

    await log.create()
    await _intentar_envio(log)
    return log


async def _intentar_envio(log: EmailLog) -> bool:
    """
    Un intento de envio sobre un EmailLog ya persistido.

    Si no hay cupo lo deja ENCOLADO sin tocar `intentos`: quedarse sin cupo
    no es un fallo del correo, y contarlo como intento lo acercaria al
    descarte por una razon que no es suya.
    """
    if await cupo_disponible(log.prioridad) <= 0:
        log.estado = EstadoEmail.ENCOLADO
        log.error = "Sin cupo diario disponible para esta prioridad."
        log.updated_at = datetime.now(timezone.utc)
        await log.save()
        logger.info(
            "[EMAIL] encolado por falta de cupo: tipo=%s prioridad=%s dest=%s",
            log.tipo, log.prioridad, log.destinatario,
        )
        return False

    log.intentos += 1
    try:
        ok = await _send_email_smtp(log.destinatario, log.asunto, log.cuerpo_html)
    except Exception as e:  # noqa: BLE001 - se registra y se sigue
        ok = False
        log.error = str(e)[:1000]

    ahora = datetime.now(timezone.utc)
    if ok:
        log.estado = EstadoEmail.ENVIADO
        log.fecha_envio = ahora
        log.error = None
    else:
        log.estado = (
            EstadoEmail.DESCARTADO if log.intentos >= MAX_INTENTOS else EstadoEmail.FALLIDO
        )
        if not log.error:
            log.error = "SMTP no acepto el correo."
    log.updated_at = ahora
    await log.save()

    if not ok:
        logger.warning(
            "[EMAIL] fallo (intento %d/%d): tipo=%s dest=%s error=%s",
            log.intentos, MAX_INTENTOS, log.tipo, log.destinatario, log.error,
        )
    return ok


async def procesar_pendientes(limite: int = 100) -> dict:
    """
    Reintenta los correos encolados y fallidos.

    Orden: primero los criticos y, dentro de cada prioridad, los mas viejos.
    Asi un lote grande de comunicados nunca posterga una credencial.

    Devuelve un resumen para poder mostrarlo en el panel.
    """
    orden_prioridad = {
        PrioridadEmail.CRITICA: 0,
        PrioridadEmail.ALTA: 1,
        PrioridadEmail.NORMAL: 2,
    }

    pendientes = await EmailLog.find(
        {"estado": {"$in": [EstadoEmail.ENCOLADO, EstadoEmail.FALLIDO]}}
    ).sort("+created_at").limit(limite * 3).to_list()

    pendientes.sort(
        key=lambda l: (orden_prioridad.get(l.prioridad, 9), l.created_at)
    )
    pendientes = pendientes[:limite]

    resumen = {"procesados": 0, "enviados": 0, "sin_cupo": 0, "fallidos": 0}
    for log in pendientes:
        resumen["procesados"] += 1
        antes = log.intentos
        ok = await _intentar_envio(log)
        if ok:
            resumen["enviados"] += 1
        elif log.intentos == antes:
            # No se toco el contador: fue falta de cupo, no un fallo.
            resumen["sin_cupo"] += 1
        else:
            resumen["fallidos"] += 1

    if resumen["procesados"]:
        logger.info("[EMAIL] procesar_pendientes: %s", resumen)
    return resumen


async def estadisticas() -> dict:
    """Resumen para el panel: cupo del dia y estado de la cola."""
    usados = await enviados_hoy()
    return {
        "cuota_diaria": settings.EMAIL_CUOTA_DIARIA,
        "cupo_reservado_criticos": settings.EMAIL_CUPO_RESERVADO_CRITICOS,
        "enviados_hoy": usados,
        "disponible_criticos": await cupo_disponible(PrioridadEmail.CRITICA),
        "disponible_resto": await cupo_disponible(PrioridadEmail.NORMAL),
        "encolados": await EmailLog.find({"estado": EstadoEmail.ENCOLADO}).count(),
        "fallidos": await EmailLog.find({"estado": EstadoEmail.FALLIDO}).count(),
        "descartados": await EmailLog.find({"estado": EstadoEmail.DESCARTADO}).count(),
    }
