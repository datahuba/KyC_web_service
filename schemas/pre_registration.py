"""
Schemas de Pre-registro de Estudiantes
=======================================

- PreRegistrationFormCreate/Update/Response: CRUD del template
- PreRegistrationSubmit: lo que envía el visitante (público, sin auth)
- PreRegistrationResponse: para el panel admin con datos enriquecidos
"""

from datetime import datetime
from typing import Optional, List, Any
import re
from pydantic import BaseModel, Field, EmailStr, field_validator

from models.base import PyObjectId


# ============================================================================
# FORM TEMPLATE (admin / super admin)
# ============================================================================

class PreRegistrationFormCreate(BaseModel):
    """Crear formulario de pre-registro (solo super admin)."""
    nombre: str = Field(..., min_length=3, max_length=200)
    slug: str = Field(..., min_length=3, max_length=120, description="Identificador URL único. Se normaliza a minúsculas, sin espacios ni acentos.")
    descripcion: Optional[str] = Field(None, max_length=1000)
    programa_id: Optional[str] = Field(None, description="ID del programa asociado (ObjectId string). None = general")
    fecha_inicio: datetime
    fecha_fin: datetime

    @field_validator("slug")
    @classmethod
    def slug_valido(cls, v: str) -> str:
        s = v.strip().lower()
        # Solo minúsculas, números y guiones. Sin acentos ni espacios.
        if not re.match(r"^[a-z0-9][a-z0-9-]{2,119}$", s):
            raise ValueError(
                "El slug solo puede contener letras minúsculas, números y guiones. "
                "Mínimo 3 caracteres. No puede empezar ni terminar con guion."
            )
        return s

    @field_validator("fecha_fin")
    @classmethod
    def fechas_coherentes(cls, v: datetime, info) -> datetime:
        inicio = info.data.get("fecha_inicio")
        if inicio and v <= inicio:
            raise ValueError("La fecha de fin debe ser posterior a la fecha de inicio.")
        return v


class PreRegistrationFormUpdate(BaseModel):
    """Editar formulario (solo super admin)."""
    nombre: Optional[str] = Field(None, min_length=3, max_length=200)
    descripcion: Optional[str] = Field(None, max_length=1000)
    programa_id: Optional[str] = Field(None)
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    estado: Optional[str] = Field(None, description="activo | cerrado")


class PreRegistrationFormResponse(BaseModel):
    id: PyObjectId = Field(..., alias="_id")
    nombre: str
    slug: str
    descripcion: Optional[str] = None
    programa_id: Optional[PyObjectId] = None
    programa_nombre: Optional[str] = None
    programa_codigo: Optional[str] = None
    fecha_inicio: datetime
    fecha_fin: datetime
    estado: str
    created_by: str
    created_at: datetime
    # Contadores (útiles para la lista admin)
    submissions_total: int = 0
    submissions_pendientes: int = 0

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }


# ============================================================================
# SUBMISSION PÚBLICO (sin auth)
# ============================================================================

class PreRegistrationSubmit(BaseModel):
    """
    Lo que envía el visitante desde la página pública.
    Solo se piden los campos mínimos para crear el Student.
    El resto (sexo, estado civil, dirección, etc.) puede completar
    en su perfil después de loguearse.
    """
    nombre: str = Field(..., min_length=3, max_length=200)
    email: EmailStr
    carnet: str = Field(..., min_length=4, max_length=20, description="Solo dígitos, sin complemento")
    extension: Optional[str] = Field(None, max_length=10, description="Ej: SC, LPZ, CBBA")
    celular: str = Field(..., min_length=6, max_length=20, description="Solo dígitos, requerido para contacto")
    fecha_nacimiento: Optional[str] = Field(None, description="DD/MM/AAAA (formato Bolivia) o ISO YYYY-MM-DD")
    sexo: Optional[str] = Field(None, description="masculino | femenino")
    domicilio: Optional[str] = Field(None, max_length=300)
    mensaje: Optional[str] = Field(None, max_length=500, description="Mensaje o consulta opcional del visitante")

    # F-2026-08-11-CAMPOS-EC: campos opcionales del Diplomado Gestión
    # Tributaria y demás programas de educación continua (planilla de Lisa).
    # Si el visitante NO se inscribe a un diplomado EC, los deja vacíos.
    registro_universitario: Optional[str] = Field(None, max_length=30, description="Registro universitario UAGRM (de la ficha del estudiante, NO es el username).")
    avance_academico_codigo: Optional[int] = Field(None, ge=0, description="Código de avance académico (planilla de Lisa).")
    formulario_descuento_numero: Optional[int] = Field(None, ge=0, description="Número del formulario de descuento (planilla de Lisa).")
    carrera_codigo: Optional[str] = Field(None, max_length=20, description="Código de carrera (de la planilla de Lisa).")
    descuento_porcentaje: Optional[float] = Field(None, ge=0, le=1, description="Descuento pre-aprobado (0.0-1.0). Aplica SOLO a módulos.")

    @field_validator("carnet")
    @classmethod
    def carnet_valido(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("El carnet debe contener solo números.")
        return v

    @field_validator("celular")
    @classmethod
    def celular_valido(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit():
            raise ValueError("El celular debe contener solo números.")
        return v

    @field_validator("sexo")
    @classmethod
    def sexo_valido(cls, v):
        if v is None or v == "":
            return None
        if v not in ("masculino", "femenino"):
            raise ValueError("Sexo debe ser 'masculino' o 'femenino'.")
        return v


# ============================================================================
# SUBMISSION RESPONSE (admin con datos enriquecidos)
# ============================================================================

class PreRegistrationResponse(BaseModel):
    id: PyObjectId = Field(..., alias="_id")
    form_id: PyObjectId
    form_nombre: Optional[str] = None
    programa_id: Optional[PyObjectId] = None
    programa_nombre: Optional[str] = None
    data: dict
    estado: str
    motivo_rechazo: Optional[str] = None
    revisado_por: Optional[str] = None
    fecha_revision: Optional[datetime] = None
    migrated_to_student_id: Optional[PyObjectId] = None
    created_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
    }


class PreRegistrationReject(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=500)
