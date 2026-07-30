"""
Modelo de Solicitud de Certificado
==================================

F-CERT-APROBACION (2026-07-30): certificado de Notas / No Deudor con flujo
de aprobación. El estudiante NO descarga directo — primero crea una solicitud
que el ENCARGADO_CURSO del programa (o admin/superadmin) debe APROBAR. Solo
después de aprobada se emite el Certificate (con su folio y PDF) y el
estudiante puede descargarlo.

Esto es homólogo al flujo de TramiteSolicitud (convalidación, tutoría,
readmisión, titulación) — misma máquina de estados, mismo patrón de
aprobación por encargado.

Colección MongoDB: certificate_requests
"""

from datetime import datetime
from typing import Optional
import pymongo
from pydantic import Field

from .base import MongoBaseModel, PyObjectId


class CertificateRequest(MongoBaseModel):
    """
    Solicitud de certificado creada por un estudiante.

    Flujo:
      1. Estudiante crea la solicitud (POST /certificates/requests).
      2. Encargado del programa (o admin/superadmin) la ve en su cola.
      3. La marca en_revision → aprobada (emite el Certificate) o
         rechazada (con motivo).
      4. Estudiante puede descargar el PDF solo si fue aprobada.
      5. Si fue rechazada, puede crear una nueva solicitud.

    Estados:
      - pendiente: recién creada, sin revisar
      - en_revision: encargado la está mirando
      - aprobada: aprobada + Certificate emitido (certificate_id != null)
      - rechazada: rechazada con motivo_rechazo
      - cancelada: el estudiante la canceló antes de ser revisada
    """

    # --- Identificación ---
    tipo: str = Field(..., description="TipoCertificado: 'notas' | 'no_deudor'")
    estudiante_id: PyObjectId = Field(..., description="ID del Student que solicita")
    enrollment_id: PyObjectId = Field(..., description="ID del Enrollment asociado")
    course_id: PyObjectId = Field(
        ..., description="ID del curso/programa (para asignar al encargado)"
    )
    hasta_modulo_n: Optional[int] = Field(
        default=None, ge=1,
        description="Solo 'no_deudor': hasta qué módulo cubre (1..N). None para 'notas'.",
    )

    # --- Datos del solicitante (snapshot al crear) ---
    nombre_completo: str = Field(..., min_length=3, max_length=200)
    programa_nombre: str = Field(..., description="Nombre del programa (snapshot)")
    programa_codigo: str = Field(..., description="Código del programa (snapshot)")

    # --- Detalle / motivo ---
    motivo: str = Field(
        ..., min_length=5, max_length=2000,
        description="Motivo o comentario del estudiante (ej. 'Necesito el certificado para presentarlo en mi trabajo')"
    )

    # --- Estado y workflow ---
    estado: str = Field(
        default="pendiente",
        description="pendiente | en_revision | aprobada | rechazada | cancelada",
    )
    fecha_revision: Optional[datetime] = Field(
        None, description="Cuando pasó a aprobada/rechazada"
    )
    revisado_por: Optional[str] = Field(
        None, description="Username del staff que revisó/aprobó/rechazó"
    )
    motivo_rechazo: Optional[str] = Field(
        None, max_length=2000,
        description="Motivo si fue rechazada (obligatorio al rechazar)",
    )
    motivo_cancelacion: Optional[str] = Field(
        None, max_length=2000,
        description="Motivo si fue cancelada por el estudiante (opcional)",
    )
    fecha_cancelacion: Optional[datetime] = Field(
        None, description="Cuando se canceló"
    )

    # --- Certificate emitido al aprobar ---
    certificate_id: Optional[PyObjectId] = Field(
        None, description="ID del Certificate emitido al aprobar (null mientras pendiente)"
    )

    class Settings:
        name = "certificate_requests"
        use_revision = True
        indexes = [
            # Listado general más reciente primero
            [("created_at", pymongo.DESCENDING)],
            # Filtros por estado (panel staff)
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            # Filtros por estudiante (mis solicitudes)
            "estudiante_id",
            # Filtros por curso (cola del encargado del programa)
            "course_id",
            # Filtros por enrollment (auditoría)
            "enrollment_id",
            # Filtros por tipo (tab en UI)
            "tipo",
            # Compuesto: cola del encargado filtrada por estado
            [("course_id", pymongo.ASCENDING), ("estado", pymongo.ASCENDING)],
        ]
