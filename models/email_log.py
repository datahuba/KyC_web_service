"""
Registro de correos enviados
============================

F-CORREOS-REGISTRO (Kevin 2026-08-17): "ver cuales son las que llegan a los
usuarios".

Hasta ahora NO quedaba rastro de ningun correo: `send_email()` devolvia un
bool y los errores iban a `print()`. Nadie podia responder "¿le llego el
correo al estudiante?". Esta coleccion es ese rastro.

Ademas resuelve el problema del tope: Brevo (plan gratis) admite 300 correos
por dia y solo los estudiantes ya son 305, asi que un comunicado masivo
agota el dia entero. Kevin decidio quedarse en el plan gratis y **priorizar
los correos con las credenciales de los estudiantes** (los del formulario de
preinscripcion), porque sin esos el alumno directamente no puede entrar al
sistema.

Para eso cada correo lleva una PRIORIDAD y el envio consulta cuanto cupo
queda en el dia antes de mandar. Los criticos tienen cupo reservado; los
demas se encolan para el dia siguiente en vez de perderse.

Coleccion MongoDB: email_logs
"""

from datetime import datetime, timezone
from typing import Optional

import pymongo
from pydantic import Field

from .base import MongoBaseModel, PyObjectId


class PrioridadEmail:
    """
    Prioridad de un correo. No es un Enum de Python a proposito: se guarda
    como string plano para poder agregar niveles sin migrar la coleccion.

    CRITICA  - sin este correo el usuario NO puede usar el sistema
               (credenciales de acceso, reset de contraseña). Tiene cupo
               reservado: se manda aunque el dia este casi agotado.
    ALTA     - el usuario espera el correo y su ausencia genera un reclamo
               (pago aprobado, inscripcion aprobada, verificacion de email).
    NORMAL   - informativo (notas, recordatorios, comunicados). Es lo
               primero que se difiere cuando no hay cupo.
    """

    CRITICA = "critica"
    ALTA = "alta"
    NORMAL = "normal"

    TODAS = (CRITICA, ALTA, NORMAL)


class EstadoEmail:
    """Estado de un correo dentro del registro."""

    ENVIADO = "enviado"      # SMTP lo acepto
    FALLIDO = "fallido"      # se intento y fallo (se reintenta)
    ENCOLADO = "encolado"    # no habia cupo en el dia, espera al siguiente
    DESCARTADO = "descartado"  # se agotaron los reintentos

    TODOS = (ENVIADO, FALLIDO, ENCOLADO, DESCARTADO)


class EmailLog(MongoBaseModel):
    """Un correo que el sistema intento (o va a intentar) enviar."""

    # --- A quien y que ---
    destinatario: str = Field(..., max_length=255, description="Email de destino")
    asunto: str = Field(..., max_length=500)
    # El cuerpo se guarda para poder reintentar sin re-generarlo, y para que
    # el staff pueda ver exactamente que se envio cuando un usuario reclama.
    cuerpo_html: str = Field(default="", description="HTML enviado")

    # --- Clasificacion ---
    # Identifica el FLUJO que lo origino (credenciales_preinscripcion,
    # pago_aprobado, comunicado, ...). Es lo que permite responder "¿que
    # correos de tal tipo salieron?".
    tipo: str = Field(..., max_length=80, description="Flujo que originó el correo")
    prioridad: str = Field(
        default=PrioridadEmail.NORMAL,
        description="critica | alta | normal",
    )

    # --- Resultado ---
    estado: str = Field(
        default=EstadoEmail.ENCOLADO,
        description="enviado | fallido | encolado | descartado",
    )
    intentos: int = Field(default=0, ge=0)
    error: Optional[str] = Field(None, max_length=1000, description="Último error de SMTP")
    fecha_envio: Optional[datetime] = Field(None, description="Cuando SMTP lo aceptó")

    # --- Trazabilidad ---
    # A quien pertenece, para poder buscar "todos los correos de este
    # estudiante" cuando llama diciendo que no le llego nada.
    destinatario_id: Optional[PyObjectId] = Field(None)
    destinatario_nombre: Optional[str] = Field(None, max_length=200)

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    class Settings:
        name = "email_logs"
        indexes = [
            [("created_at", pymongo.DESCENDING)],
            "estado",
            "tipo",
            "prioridad",
            "destinatario",
            "destinatario_id",
            # Para contar lo enviado en el dia (control de cupo) sin escanear
            # la coleccion entera.
            [("estado", pymongo.ASCENDING), ("fecha_envio", pymongo.DESCENDING)],
        ]
