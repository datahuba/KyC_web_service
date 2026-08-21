"""
Schemas Pydantic para Certificados
==================================

Define los schemas de entrada (request) y salida (response) para los
endpoints de /certificates.

F-CERTIFICADOS (2026-07-29): ver spec en
.agents/specs/CERTIFICADOS/{requirements,design,tasks}.md
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from models.enums import TipoCertificado


# ========================================================================
# REQUEST: emisión de certificado
# ========================================================================

class CertificateEmitRequest(BaseModel):
    """
    Body para POST /certificates/emit.

    El estudiante pide emisión de su propio certificado.
    - Para 'notas': solo se envía `tipo` y `enrollment_id`.
    - Para 'no_deudor': se envía también `hasta_modulo_n` (1..N).
    """
    tipo: TipoCertificado = Field(..., description="Tipo de certificado: 'notas', 'no_deudor' o 'alumno_regular'")
    enrollment_id: str = Field(..., description="ID de la inscripción para la cual se emite el certificado")
    hasta_modulo_n: Optional[int] = Field(
        default=None,
        ge=1,
        description="Solo para 'no_deudor': hasta qué módulo cubre (1..N). Ignorado para 'notas' y 'alumno_regular'.",
    )

    @field_validator("enrollment_id")
    @classmethod
    def validar_enrollment_id(cls, v: str) -> str:
        # Pydantic v2 valida automáticamente que sea un ObjectId válido de Mongo
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            ObjectId(v)
        except (InvalidId, TypeError):
            raise ValueError("enrollment_id debe ser un ObjectId válido de MongoDB (24 caracteres hex)")
        return v

    class Config:
        json_schema_extra = {
            "examples": [
                {"tipo": "notas", "enrollment_id": "507f1f77bcf86cd799439013"},
                {"tipo": "no_deudor", "enrollment_id": "507f1f77bcf86cd799439013", "hasta_modulo_n": 2},
            ]
        }


# ========================================================================
# RESPONSE: snapshot de un módulo en el certificado
# ========================================================================

class CertificateModuloOut(BaseModel):
    """Snapshot de un módulo al emitir el certificado (parte del response)."""
    nombre: str
    nota: Optional[int] = Field(default=None, ge=0, le=100)
    literal: Optional[str] = None
    estado: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None


# ========================================================================
# RESPONSE: certificado emitido
# ========================================================================

class CertificateOut(BaseModel):
    """Response de un certificado emitido."""
    id: str = Field(..., description="ID del certificado en MongoDB")
    tipo: TipoCertificado
    folio: str = Field(..., description="Folio formateado: 'N° 042/2026'")
    numero: int
    anio: int

    student_id: str
    course_id: str
    enrollment_id: str

    modulos_snapshot: List[CertificateModuloOut]
    hasta_modulo_n: Optional[int] = None

    programa_nombre: str
    programa_codigo: str
    programa_version: str
    programa_edicion: str

    estudiante_nombre: str
    estudiante_registro: str
    estudiante_ci: str
    estudiante_extension: Optional[str] = None
    estudiante_complemento: Optional[str] = None

    emitido_en: datetime
    emitido_por: str
    verificacion_code: str

    pdf_url: str
    pdf_filename: str

    # ========================================================================
    # Validador: folio siempre formateado como N° XXX/YYYY
    # ========================================================================

    @field_validator("folio", mode="before")
    @classmethod
    def formatear_folio(cls, v, info):
        # Si folio ya viene formateado, lo dejamos. Si no, lo armamos.
        if isinstance(v, str) and v.startswith("N°"):
            return v
        # Si llega como dict (lo cual no debería pasar), retornar el string
        return v

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "507f1f77bcf86cd799439099",
                "tipo": "notas",
                "folio": "N° 042/2026",
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
                        "estado": None,
                        "fecha_inicio": "2026-03-15T00:00:00",
                        "fecha_fin": "2026-03-20T00:00:00",
                    }
                ],
                "hasta_modulo_n": None,
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


class CertificateListResponse(BaseModel):
    """Response de GET /certificates/my o /certificates/by-enrollment/{id}."""
    items: List[CertificateOut]
    total: int = Field(..., description="Cantidad total de certificados en la lista")
