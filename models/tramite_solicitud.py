"""
Modelo de Solicitud de Trámite (Tramite Solicitud)
==================================================

F-TRAMITES-SOLICITUD (2026-07-29): solicitudes que el estudiante crea desde
/app/requests. Sandra/Rocío pidieron 4 tipos (reunión 2026-07-29):

  - CONVALIDACION: convalidar materias cursadas en otra institución.
    Requisitos: carta + certificado de nota (emitido por escuela postgrado) + pago.
  - TUTORIA: solicitar tutoría para su trabajo final / tesis.
    Requisitos: carta + certificado de nota + pago.
  - READMISION: personas que estudiaron hace años y no defendieron; la
    escuela de postgrado autoriza por algún motivo X/Z.
  - TITULACION: solicitud formal del título una vez completado el programa.

Flujo:
  1. Estudiante crea la solicitud (POST /tramites/).
  2. Sube archivos adjuntos (carta, certificado de nota, comprobante de pago) a Cloudinary.
  3. Staff (CPD / Admin / Superadmin / MAE / Coordinador) la revisa y
     aprueba o rechaza.
  4. Estado final: aprobada | rechazada. El estudiante puede cancelar
     mientras esté pendiente o en revisión.

Colección MongoDB: tramite_solicitudes
"""

from datetime import datetime
from typing import Optional, List
import pymongo
from pydantic import BaseModel, Field
from beanie import PydanticObjectId

from .base import MongoBaseModel, PyObjectId


class ArchivoAdjunto(BaseModel):
    """
    Archivo adjunto a la solicitud (carta, certificado de nota, comprobante).
    Subido a Cloudinary; se guarda la URL pública.
    """
    nombre_campo: str = Field(..., description="Identificador del archivo: 'carta' | 'certificado_nota' | 'comprobante_pago' | 'otro'")
    url: str = Field(..., description="URL pública de Cloudinary")
    nombre_archivo: Optional[str] = Field(None, description="Nombre original del archivo (display)")
    mime_type: Optional[str] = Field(None, description="image/jpeg, application/pdf, etc.")
    subido_en: datetime = Field(default_factory=datetime.utcnow)


class TramiteSolicitud(MongoBaseModel):
    """
    Solicitud de trámite creada por un estudiante.
    """

    # --- Identificación ---
    tipo: str = Field(
        ..., description="TipoTramite: convalidacion | tutoria | readmision | titulacion"
    )
    estudiante_id: PyObjectId = Field(..., description="ID del Student que solicita")
    enrollment_id: Optional[PyObjectId] = Field(
        None, description="ID del Enrollment asociado (opcional; no aplica a todas las solicitudes)"
    )

    # --- Datos del solicitante ---
    nombre_completo: str = Field(..., min_length=3, max_length=200)
    ci: Optional[str] = Field(None, description="C.I. del estudiante (referencia)")
    email: Optional[str] = Field(None, description="Email de contacto (referencia)")
    telefono: Optional[str] = Field(None, description="Teléfono (opcional)")

    # --- Detalle de la solicitud ---
    motivo: str = Field(
        ..., min_length=10, max_length=2000,
        description="Detalle / motivo de la solicitud (descripción libre del estudiante)"
    )
    programa_relacionado: Optional[str] = Field(
        None, max_length=300,
        description="Programa o curso al que se refiere (texto libre, ej. 'Diplomado IA 2026')"
    )
    modulos_relacionados: Optional[List[str]] = Field(
        default_factory=list,
        description="Módulos a los que aplica (ej. ['Módulo 1', 'Módulo 2']) — opcional"
    )
    monto_pago_bs: Optional[float] = Field(
        None, ge=0, description="Monto pagado por el trámite (si aplica)"
    )

    # --- Archivos adjuntos (Cloudinary) ---
    archivos: List[ArchivoAdjunto] = Field(
        default_factory=list,
        description="Archivos subidos a Cloudinary: carta, certificado, comprobante, etc."
    )

    # --- Estado y workflow ---
    estado: str = Field(
        default="pendiente", description="pendiente | en_revision | aprobada | rechazada | cancelada"
    )
    fecha_revision: Optional[datetime] = Field(None, description="Cuando pasó a aprobada/rechazada")
    revisado_por: Optional[str] = Field(None, description="Username del staff que revisó")
    motivo_rechazo: Optional[str] = Field(None, max_length=2000, description="Motivo si fue rechazada")
    motivo_cancelacion: Optional[str] = Field(None, max_length=2000, description="Motivo si fue cancelada por el estudiante")
    fecha_cancelacion: Optional[datetime] = Field(None, description="Cuando se canceló")

    class Settings:
        name = "tramite_solicitudes"
        use_revision = True
        indexes = [
            # Listado general más reciente primero
            [("created_at", pymongo.DESCENDING)],
            # Filtro por estado (panel staff)
            [("estado", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            # Filtro por estudiante
            "estudiante_id",
            # Filtro por tipo (tabs UI)
            "tipo",
            # Filtros compuestos
            [("tipo", pymongo.ASCENDING), ("estado", pymongo.ASCENDING)],
        ]
