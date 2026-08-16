"""
Modelo de Certificado
=====================

Representa un certificado emitido por la Unidad de Postgrado a un estudiante
(Certificado de Notas o Certificado de No Deudor).

Cada certificado es un documento INMUTABLE: al emitirse se guarda un snapshot
de los datos relevantes y el PDF generado se persiste en Cloudinary. Aunque
los datos del estudiante cambien después, el certificado emitido NO se altera.

Colección MongoDB: certificates

F-CERTIFICADOS (2026-07-29): ver spec completo en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md
"""

from datetime import datetime
from typing import Optional, List
import pymongo
from pydantic import BaseModel, Field
from .base import MongoBaseModel, PyObjectId
from .enums import TipoCertificado


class ModuloCertificado(BaseModel):
    """
    Snapshot de un módulo al emitir el certificado (inmutable).

    Para Certificado de Notas: nombre + nota + literal + rango de fechas.
    Para Certificado de No Deudor: solo nombre + estado de pago + fechas
    (sin nota/literal porque no son relevantes para acreditar pagos).
    """
    nombre: str = Field(..., description="Nombre del módulo (Ej: 'Módulo 1: Fundamentos del Derecho Tributario')")
    nota: Optional[int] = Field(default=None, ge=0, le=100, description="Calificación 0-100. Solo Certificado de Notas.")
    literal: Optional[str] = Field(default=None, description="Calificación en letras (ej. 'Noventa y tres'). Solo Certificado de Notas.")
    estado: Optional[str] = Field(default=None, description="Estado de pago al momento de emisión: 'Pagado' | 'Parcial' | 'Pendiente'. Solo No Deudor.")
    fecha_inicio: Optional[datetime] = Field(default=None, description="Fecha de inicio del módulo (UTC).")
    fecha_fin: Optional[datetime] = Field(default=None, description="Fecha de fin del módulo (UTC).")


class Certificate(MongoBaseModel):
    """
    Modelo de Certificado emitido.

    Flujo:
    1. Estudiante pide emisión desde /app/certificates
    2. Backend valida requisitos (programa finalizado+pagado, o módulos 1..N pagados)
    3. Backend genera PDF con reportlab
    4. Backend sube PDF a Cloudinary (folder kyc/certificates/)
    5. Backend persiste este documento con snapshot inmutable + URL del PDF
    6. Estudiante descarga el PDF vía GET /certificates/{id}/pdf
    """

    # ========================================================================
    # IDENTIFICACIÓN
    # ========================================================================

    tipo: TipoCertificado = Field(..., description="Tipo de certificado: 'notas' o 'no_deudor'")
    numero: int = Field(..., ge=1, description="Correlativo anual (sin ceros a la izquierda en BD; se formatea como 3 dígitos en el PDF)")
    anio: int = Field(..., ge=2000, le=2100, description="Año del correlativo (usado para el folio 'N° XXX/YYYY')")

    # ========================================================================
    # RELACIONES (redundantes para queries rápidas)
    # ========================================================================

    student_id: PyObjectId = Field(..., description="ID del estudiante dueño del certificado")
    course_id: PyObjectId = Field(..., description="ID del curso/programa")
    enrollment_id: PyObjectId = Field(..., description="ID de la inscripción (1 certificado de Notas por enrollment)")

    # ========================================================================
    # SNAPSHOT INMUTABLE DE DATOS AL MOMENTO DE EMISIÓN
    # ========================================================================

    modulos_snapshot: List[ModuloCertificado] = Field(
        default_factory=list,
        description="Copia de los módulos al momento de emisión. Para Notas: todos. Para No Deudor: los que cubre el certificado."
    )
    hasta_modulo_n: Optional[int] = Field(
        default=None,
        ge=1,
        description="Solo para No Deudor: hasta qué módulo cubre el certificado (1 = solo módulo 1; N = todo el programa)."
    )

    # Metadata del programa (snapshot, en caso que el curso se renombre después)
    programa_nombre: str = Field(..., description="Nombre del programa al momento de emisión")
    programa_codigo: str = Field(..., description="Código del programa (ej: 'DIPL-2024-001')")
    programa_version: str = Field(default="", description="Versión del programa (ej: '5' para 'Ver. 5')")
    programa_edicion: str = Field(default="", description="Edición del programa (ej: '1' para 'Edic. 1')")

    # Datos del estudiante al momento de emisión (snapshot)
    estudiante_nombre: str = Field(..., description="Nombre completo del estudiante al emitir")
    estudiante_registro: str = Field(..., description="Registro universitario al emitir")
    estudiante_ci: str = Field(..., description="Carnet de identidad (solo números) al emitir")
    estudiante_extension: Optional[str] = Field(default=None, description="Extensión del CI (ej: 'SC', 'BEN')")
    estudiante_complemento: Optional[str] = Field(default=None, description="Complemento del CI (ej: '1D')")

    # ========================================================================
    # AUDITORÍA Y VERIFICACIÓN
    # ========================================================================

    emitido_en: datetime = Field(..., description="Fecha y hora UTC de emisión")
    emitido_por: str = Field(..., description="Username del usuario que pidió la emisión (registro del estudiante)")
    verificacion_code: str = Field(..., description="Código único de 12 chars hex para verificación futura")

    # ========================================================================
    # PERSISTENCIA DEL PDF (snapshot inmutable en Cloudinary)
    # ========================================================================

    pdf_url: str = Field(..., description="URL pública del PDF en Cloudinary (folder kyc/certificates/)")
    pdf_filename: str = Field(..., description="Nombre del archivo PDF para descarga (ej: 'certificado_notas_N042_2026_SANGUINO_RIBERA.pdf')")

    class Settings:
        name = "certificates"
        # AUDITORÍA: optimistic locking (consistente con Payment, Enrollment).
        # Evita race conditions si dos requests emiten el mismo certificado
        # casi simultáneamente (aunque el endpoint ya valida unicidad por
        # enrollment_id+tipo, esto añade defensa en profundidad).
        use_revision = True
        indexes = [
            # Búsquedas por estudiante (lista de "mis certificados")
            "student_id",
            # Búsquedas por enrollment (auditoría / evitar duplicados)
            "enrollment_id",
            # Búsquedas por curso (reportes / filtros admin)
            "course_id",
            # Unicidad: 1 certificado de NOTAS por enrollment (F-CERTIFICADOS §5.2)
            pymongo.IndexModel(
                [("enrollment_id", pymongo.ASCENDING), ("tipo", pymongo.ASCENDING)],
                unique=True,
                name="uniq_enrollment_tipo",
            ),
            # Correlativo anual único (F-CERTIFICADOS §5.1)
            pymongo.IndexModel(
                [("anio", pymongo.ASCENDING), ("numero", pymongo.ASCENDING)],
                unique=True,
                name="uniq_anio_numero",
            ),
            # Ordenación por fecha de emisión
            [("emitido_en", pymongo.DESCENDING)],
        ]

    class Config:
        json_schema_extra = {
            "example": {
                "tipo": "notas",
                "numero": 42,
                "anio": 2026,
                "student_id": "507f1f77bcf86cd799439011",
                "course_id": "507f1f77bcf86cd799439012",
                "enrollment_id": "507f1f77bcf86cd799439013",
                "modulos_snapshot": [
                    {
                        "nombre": "Módulo 1: Fundamentos",
                        "nota": 93,
                        "literal": "Noventa y tres",
                        "fecha_inicio": "2026-03-15T00:00:00",
                        "fecha_fin": "2026-03-20T00:00:00",
                    }
                ],
                "programa_nombre": "Educación Continua en Gestión Tributaria",
                "programa_codigo": "DIPL-2026-001",
                "programa_version": "5",
                "programa_edicion": "1",
                "estudiante_nombre": "SANGUINO RIBERA ERLINDA KAORI",
                "estudiante_registro": "214138348",
                "estudiante_ci": "10781482",
                "estudiante_extension": "BEN",
                "estudiante_complemento": None,
                "emitido_en": "2026-07-29T18:30:00",
                "emitido_por": "214138348",
                "verificacion_code": "a3f9b2c1d4e5",
                "pdf_url": "https://res.cloudinary.com/kyc/raw/upload/v1/certificates/cert_notas_042_2026.pdf",
                "pdf_filename": "certificado_notas_N042_2026_SANGUINO_RIBERA.pdf",
            }
        }
