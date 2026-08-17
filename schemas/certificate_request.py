"""
Schemas Pydantic para CertificateRequest
========================================

F-CERT-APROBACION (2026-07-30): el estudiante crea la solicitud, el
encargado del programa (o admin) la aprueba y eso emite el Certificate.
"""

from datetime import datetime
from typing import Optional, List, Any
from pydantic import BaseModel, Field, field_validator


# ========================================================================
# REQUEST: crear solicitud
# ========================================================================

class CertificateRequestCreate(BaseModel):
    """
    Body para POST /certificates/requests.

    El estudiante autenticado pide emisión de su certificado. La solicitud
    queda en estado 'pendiente' hasta que el encargado del programa la apruebe.
    """
    tipo: str = Field(..., description="TipoCertificado: 'notas' | 'no_deudor'")
    enrollment_id: str = Field(..., description="ID de la inscripción para la cual se solicita el certificado")
    hasta_modulo_n: Optional[int] = Field(
        default=None, ge=1,
        description="Solo 'no_deudor': hasta qué módulo cubre (1..N). Ignorado para 'notas'.",
    )
    motivo: str = Field(
        ..., min_length=5, max_length=2000,
        description="Motivo o comentario del estudiante (mín 5 caracteres)",
    )

    @field_validator("enrollment_id")
    @classmethod
    def validar_enrollment_id(cls, v: str) -> str:
        from bson import ObjectId
        from bson.errors import InvalidId
        try:
            ObjectId(v)
        except (InvalidId, TypeError):
            raise ValueError("enrollment_id debe ser un ObjectId válido de MongoDB (24 caracteres hex)")
        return v

    @field_validator("tipo")
    @classmethod
    def validar_tipo(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in {"notas", "no_deudor"}:
            raise ValueError("tipo debe ser 'notas' o 'no_deudor'")
        return v


# ========================================================================
# F-CERT-NO-DEUDOR-COBRO (Kevin 2026-08-17): aprobar y confirmar firma
# ========================================================================

# Tratamientos admitidos. Kevin: "a los profesionales debe decir lic. o ing.
# o lo que sea respecto a su carrera". Los de diplomado continuo NO llevan
# tratamiento, por eso None es una opcion valida y es el default.
TRATAMIENTOS_VALIDOS = {"Lic.", "Lic.a", "Ing.", "Arq.", "Dr.", "Dra.", "Msc.", "Tec."}


class CertificateRequestAprobar(BaseModel):
    """
    Body para PATCH /certificates/requests/{id}/approve.

    El tratamiento lo elige quien aprueba, no el estudiante: es el que conoce
    el titulo real y el que firma el documento. Va vacio para los de diplomado
    continuo.
    """
    tratamiento: Optional[str] = Field(
        default=None, max_length=20,
        description="Tratamiento profesional a imprimir antes del nombre. "
                    "Vacio para estudiantes de diplomado continuo.",
    )

    @field_validator("tratamiento")
    @classmethod
    def validar_tratamiento(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        v = v.strip()
        if not v:
            return None
        if v not in TRATAMIENTOS_VALIDOS:
            raise ValueError(
                f"Tratamiento invalido. Debe ser uno de: {', '.join(sorted(TRATAMIENTOS_VALIDOS))}, "
                f"o vacio si no corresponde."
            )
        return v


class CertificateRequestConfirmarFirma(BaseModel):
    """
    Body para PATCH /certificates/requests/{id}/confirmar-firma.

    Segundo paso de la aprobacion: el coordinador ya hizo firmar la copia
    fisica y recien ahi habilita al estudiante a descargar el PDF.
    """
    observacion: Optional[str] = Field(
        default=None, max_length=500,
        description="Nota opcional (ej. a quien se le entrego la copia fisica)",
    )


# ========================================================================
# REQUEST: rechazar
# ========================================================================

class CertificateRequestRechazar(BaseModel):
    """Body para PATCH /certificates/requests/{id}/rechazar."""
    motivo_rechazo: str = Field(
        ..., min_length=5, max_length=2000,
        description="Motivo del rechazo (obligatorio, mín 5 caracteres)",
    )


# ========================================================================
# REQUEST: cancelar (estudiante)
# ========================================================================

class CertificateRequestCancelar(BaseModel):
    """Body para PATCH /certificates/requests/{id}/cancelar."""
    motivo_cancelacion: Optional[str] = Field(
        default=None, max_length=2000,
        description="Motivo de la cancelación (opcional)",
    )


# ========================================================================
# RESPONSE
# ========================================================================

class CertificateRequestOut(BaseModel):
    """Response de una solicitud de certificado."""
    id: str
    tipo: str
    estado: str

    estudiante_id: str
    enrollment_id: str
    course_id: str
    hasta_modulo_n: Optional[int] = None

    nombre_completo: str
    programa_nombre: str
    programa_codigo: str
    motivo: str

    fecha_revision: Optional[datetime] = None
    revisado_por: Optional[str] = None
    motivo_rechazo: Optional[str] = None
    motivo_cancelacion: Optional[str] = None
    fecha_cancelacion: Optional[datetime] = None

    certificate_id: Optional[str] = None

    # F-CERT-NO-DEUDOR-COBRO (2026-08-17): arancel, comprobante, tratamiento
    # y firma física. Van en el mismo Out porque el panel del coordinador
    # necesita los cuatro para decidir.
    monto: Optional[float] = None
    comprobante_url: Optional[str] = None
    tratamiento: Optional[str] = None
    firma_fisica_confirmada: bool = False
    fecha_firma_fisica: Optional[datetime] = None
    confirmada_por: Optional[str] = None
    observacion_firma: Optional[str] = None
    # Calculado, no persistido: si el estudiante ya puede bajarse el PDF.
    # Para 'notas' es True apenas se aprueba; para 'no_deudor' exige la firma.
    descargable: bool = False

    # Fechas de auditoría (vienen de MongoBaseModel: created_at, updated_at)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CertificateRequestListResponse(BaseModel):
    """Response paginada de lista de solicitudes."""
    items: List[CertificateRequestOut]
    total: int


# ========================================================================
# ESTADÍSTICAS (panel del encargado)
# ========================================================================

class CertificateRequestEstadisticas(BaseModel):
    """Métricas del panel de solicitudes para el encargado/admin."""
    pendientes: int
    en_revision: int
    aprobadas_hoy: int
    rechazadas_hoy: int
    total_pendientes: int
