"""
F-2026-08-11-ASISTENCIA: schemas Pydantic para el sistema de registro
de asistencia por sesion/clase.
"""
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from models.base import PyObjectId
from models.enums import EstadoAsistencia


class SesionCreate(BaseModel):
    """Schema para crear una nueva sesion/clase."""
    enrollment_id: PyObjectId = Field(..., description="ID del enrollment")
    modulo_index: int = Field(..., ge=0, description="Indice del modulo en enrollment.modulos")
    fecha: datetime = Field(..., description="Fecha y hora de la sesion (UTC)")
    tema: Optional[str] = Field(None, max_length=200, description="Tema/contenido de la sesion")


class SesionResponse(BaseModel):
    """Schema de respuesta con la sesion creada o consultada."""
    id: PyObjectId = Field(..., alias="_id")
    enrollment_id: PyObjectId
    modulo_index: int
    fecha: datetime
    tema: Optional[str] = None
    creado_por: str
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class AsistenciaItem(BaseModel):
    """Un registro de asistencia individual (un estudiante en una sesion)."""
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    estado: EstadoAsistencia = Field(..., description="Estado de asistencia")
    observacion: Optional[str] = Field(None, max_length=500, description="Observacion opcional")


class AsistenciaBulkRegister(BaseModel):
    """
    Schema para registrar la asistencia de N estudiantes en una sesion
    de una sola vez. Tipico: el docente pasa lista al inicio/final de
    la clase y registra todos juntos.
    """
    registros: List[AsistenciaItem] = Field(..., min_length=1, description="Lista de registros (1 por estudiante)")


class AsistenciaRegistroResponse(BaseModel):
    """Schema de respuesta con un registro individual."""
    id: PyObjectId = Field(..., alias="_id")
    sesion_id: PyObjectId
    estudiante_id: PyObjectId
    estado: str
    observacion: Optional[str] = None
    registrado_por: str
    created_at: datetime
    updated_at: datetime

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class PorcentajeAsistenciaModulo(BaseModel):
    """
    F-2026-08-11-ASISTENCIA: resumen de asistencia de UN estudiante en UN
    modulo. Devuelve el % calculado, la cantidad de sesiones registradas
    y el detalle (presentes/ausentes/tarde/justificados).
    """
    enrollment_id: PyObjectId
    modulo_index: int
    estudiante_id: PyObjectId
    total_sesiones: int = Field(..., description="Cantidad de sesiones con al menos un registro para este estudiante")
    presentes: int = Field(..., description="Cantidad de registros con estado='presente'")
    ausentes: int = Field(..., description="Cantidad de registros con estado='ausente'")
    tardes: int = Field(..., description="Cantidad de registros con estado='tarde' (cuenta como 0.5)")
    justificados: int = Field(..., description="Cantidad de registros con estado='justificado' (neutro)")
    porcentaje: float = Field(..., ge=0, le=100, description="% asistencia calculado: (presentes + 0.5*tardes) / total_sesiones * 100")
    cumple_regla_80: bool = Field(..., description="True si porcentaje >= 80")
