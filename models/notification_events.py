"""
Eventos de notificación
=======================

F-NOTIF-TIPOS (Kevin 2026-08-17): "mejorar como llegan las notificaciones a
los estudiantes y a todos los usuarios".

El problema que resuelve: `Notification.tipo_alerta` guardaba solo
`info | success | warning | error`, que es la SEVERIDAD visual, no QUE PASO.
Medido contra produccion el 2026-08-17: 849 notificaciones emitidas y apenas
4 valores distintos, todos severidades. Sin saber que evento las origino no
se puede filtrar, ni agrupar, ni dejar que cada uno elija que quiere recibir.

Este catalogo sale de los titulos que el codigo ya venia usando en los 35
puntos donde se notifica — no es una taxonomia inventada, es la que ya
existia implicita en el texto.

`evento` es OPCIONAL en el modelo a proposito: las 849 notificaciones
historicas no lo tienen y no se van a reescribir. El codigo nuevo lo manda;
lo viejo sigue funcionando.
"""


class EventoNotificacion:
    """Que paso. Complementa a `tipo_alerta`, que es como se ve."""

    # --- Pagos ---
    PAGO_REGISTRADO = "pago_registrado"
    PAGO_PENDIENTE_REVISION = "pago_pendiente_revision"
    PAGO_APROBADO = "pago_aprobado"
    PAGO_RECHAZADO = "pago_rechazado"
    PAGO_ANULADO = "pago_anulado"
    PAGO_EN_CAJA = "pago_en_caja"
    COMPROBANTE_SUBIDO = "comprobante_subido"
    RECORDATORIO_PAGO = "recordatorio_pago"
    ALERTA_MORA = "alerta_mora"

    # --- Notas ---
    NOTA_BORRADOR_PENDIENTE = "nota_borrador_pendiente"
    NOTA_BORRADOR_RECHAZADO = "nota_borrador_rechazado"
    NOTA_VALIDADA = "nota_validada"
    NOTA_OFICIALIZADA = "nota_oficializada"
    NOTA_AJUSTADA = "nota_ajustada"

    # --- Inscripciones ---
    INSCRIPCION_SOLICITADA = "inscripcion_solicitada"
    INSCRIPCION_APROBADA = "inscripcion_aprobada"
    INSCRIPCION_RECHAZADA = "inscripcion_rechazada"
    INSCRIPCION_RETIRADA = "inscripcion_retirada"
    INSCRIPCION_ABANDONO = "inscripcion_abandono"
    ESTUDIOS_CONGELADOS = "estudios_congelados"

    # --- Documentos (KYC) ---
    DOCUMENTO_POR_REVISAR = "documento_por_revisar"
    DOCUMENTO_APROBADO = "documento_aprobado"
    DOCUMENTO_RECHAZADO = "documento_rechazado"
    FORMULARIO_POR_REVISAR = "formulario_por_revisar"

    # --- Solicitudes ---
    SOLICITUD_CUENTA = "solicitud_cuenta"
    SOLICITUD_PASIVO = "solicitud_pasivo"
    SOLICITUD_PASIVO_RECHAZADA = "solicitud_pasivo_rechazada"
    PRE_INSCRIPCION_NUEVA = "pre_inscripcion_nueva"

    # --- Cursos ---
    CURSO_PAUSADO = "curso_pausado"
    CURSO_REACTIVADO = "curso_reactivado"

    # --- Certificados ---
    CERTIFICADO_APROBADO = "certificado_aprobado"
    CERTIFICADO_LISTO = "certificado_listo"

    OTRO = "otro"

    @classmethod
    def todos(cls) -> list:
        return [
            v for k, v in vars(cls).items()
            if not k.startswith("_") and isinstance(v, str)
        ]


# Agrupacion para la UI: permite mostrar "Pagos (12)" en vez de una lista
# plana de 30 eventos sueltos.
GRUPO_POR_EVENTO = {
    EventoNotificacion.PAGO_REGISTRADO: "Pagos",
    EventoNotificacion.PAGO_PENDIENTE_REVISION: "Pagos",
    EventoNotificacion.PAGO_APROBADO: "Pagos",
    EventoNotificacion.PAGO_RECHAZADO: "Pagos",
    EventoNotificacion.PAGO_ANULADO: "Pagos",
    EventoNotificacion.PAGO_EN_CAJA: "Pagos",
    EventoNotificacion.COMPROBANTE_SUBIDO: "Pagos",
    EventoNotificacion.RECORDATORIO_PAGO: "Pagos",
    EventoNotificacion.ALERTA_MORA: "Pagos",

    EventoNotificacion.NOTA_BORRADOR_PENDIENTE: "Notas",
    EventoNotificacion.NOTA_BORRADOR_RECHAZADO: "Notas",
    EventoNotificacion.NOTA_VALIDADA: "Notas",
    EventoNotificacion.NOTA_OFICIALIZADA: "Notas",
    EventoNotificacion.NOTA_AJUSTADA: "Notas",

    EventoNotificacion.INSCRIPCION_SOLICITADA: "Inscripciones",
    EventoNotificacion.INSCRIPCION_APROBADA: "Inscripciones",
    EventoNotificacion.INSCRIPCION_RECHAZADA: "Inscripciones",
    EventoNotificacion.INSCRIPCION_RETIRADA: "Inscripciones",
    EventoNotificacion.INSCRIPCION_ABANDONO: "Inscripciones",
    EventoNotificacion.ESTUDIOS_CONGELADOS: "Inscripciones",

    EventoNotificacion.DOCUMENTO_POR_REVISAR: "Documentos",
    EventoNotificacion.DOCUMENTO_APROBADO: "Documentos",
    EventoNotificacion.DOCUMENTO_RECHAZADO: "Documentos",
    EventoNotificacion.FORMULARIO_POR_REVISAR: "Documentos",

    EventoNotificacion.SOLICITUD_CUENTA: "Solicitudes",
    EventoNotificacion.SOLICITUD_PASIVO: "Solicitudes",
    EventoNotificacion.SOLICITUD_PASIVO_RECHAZADA: "Solicitudes",
    EventoNotificacion.PRE_INSCRIPCION_NUEVA: "Solicitudes",

    EventoNotificacion.CURSO_PAUSADO: "Cursos",
    EventoNotificacion.CURSO_REACTIVADO: "Cursos",

    EventoNotificacion.CERTIFICADO_APROBADO: "Certificados",
    EventoNotificacion.CERTIFICADO_LISTO: "Certificados",

    EventoNotificacion.OTRO: "Otros",
}
