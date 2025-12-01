"""
Schemas de Curso
================

Define los schemas Pydantic para operaciones CRUD de cursos.

Schemas incluidos:
-----------------
1. CourseCreate: Para crear nuevos cursos
2. CourseResponse: Para mostrar cursos
3. CourseUpdate: Para actualizar cursos
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from models.enums import TipoCurso, Modalidad
from models.base import PyObjectId


class CourseCreate(BaseModel):
    """
    Schema para crear un nuevo curso
    
    Uso: POST /courses/
    
    ¿Qué incluye?
    ------------
    - Identificación (código, nombre, tipo, modalidad)
    - Precios para internos (costo total, cuota, matrícula)
    - Precios para externos (costo total, cuota, matrícula)
    - Estructura de pago (cantidad de cuotas, descuento)
    - Información adicional (observación, requisitos, fechas)
    
    ¿Qué NO incluye?
    ---------------
    - id: Se genera automáticamente
    - inscritos: Se llena cuando los estudiantes se inscriben
    - created_at, updated_at: Autogenerados
    """
    
    codigo: str = Field(..., description="Código único del curso")
    nombre_programa: str = Field(..., min_length=1, max_length=300)
    tipo_curso: TipoCurso
    modalidad: Modalidad
    
    # Precios internos
    costo_total_interno: float = Field(..., gt=0)
    monto_cuota_interno: float = Field(..., gt=0)
    matricula_interno: float = Field(..., ge=0)
    
    # Precios externos
    costo_total_externo: float = Field(..., gt=0)
    monto_cuota_externo: float = Field(..., gt=0)
    matricula_externo: float = Field(..., ge=0)
    
    # Estructura de pago
    cantidad_cuotas: int = Field(..., ge=1)
    descuento_general: Optional[float] = Field(None, ge=0, le=100)
    
    # Información adicional
    observacion: Optional[str] = None
    requisitos: List[str] = Field(default_factory=list)
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: bool = True
    
    @validator('monto_cuota_interno')
    def validar_monto_cuota_interno(cls, v, values):
        """Valida coherencia de cuota interna con costo total"""
        if 'costo_total_interno' in values and 'cantidad_cuotas' in values:
            costo_total = values['costo_total_interno']
            cantidad_cuotas = values['cantidad_cuotas']
            
            if 'matricula_interno' in values:
                costo_total -= values['matricula_interno']
            
            esperado = costo_total / cantidad_cuotas
            if abs(v - esperado) > 0.01:
                raise ValueError(
                    f"El monto de cuota interno ({v}) no coincide con "
                    f"(costo_total_interno - matricula_interno) / cantidad_cuotas ({esperado:.2f})"
                )
        return v
    
    @validator('monto_cuota_externo')
    def validar_monto_cuota_externo(cls, v, values):
        """Valida coherencia de cuota externa con costo total"""
        if 'costo_total_externo' in values and 'cantidad_cuotas' in values:
            costo_total = values['costo_total_externo']
            cantidad_cuotas = values['cantidad_cuotas']
            
            if 'matricula_externo' in values:
                costo_total -= values['matricula_externo']
            
            esperado = costo_total / cantidad_cuotas
            if abs(v - esperado) > 0.01:
                raise ValueError(
                    f"El monto de cuota externo ({v}) no coincide con "
                    f"(costo_total_externo - matricula_externo) / cantidad_cuotas ({esperado:.2f})"
                )
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "codigo": "DIPL-2024-001",
                "nombre_programa": "Diplomado en Ciencia de Datos",
                "tipo_curso": "diplomado",
                "modalidad": "híbrido",
                "costo_total_interno": 3000.0,
                "monto_cuota_interno": 500.0,
                "matricula_interno": 500.0,
                "costo_total_externo": 5000.0,
                "monto_cuota_externo": 900.0,
                "matricula_externo": 500.0,
                "cantidad_cuotas": 5,
                "descuento_general": 10.0,
                "observacion": "Incluye certificación internacional",
                "requisitos": ["Título profesional", "CV actualizado"],
                "fecha_inicio": "2024-03-01T00:00:00",
                "fecha_fin": "2024-08-31T00:00:00",
                "activo": True
            }
        }


class CourseResponse(BaseModel):
    """
    Schema para mostrar información de un curso
    
    Uso: GET /courses/{id}, respuestas de POST/PUT/PATCH
    
    Incluye todos los campos del curso, incluyendo la lista de inscritos.
    """
    
    id: PyObjectId = Field(..., alias="_id")
    codigo: str
    nombre_programa: str
    tipo_curso: TipoCurso
    modalidad: Modalidad
    
    costo_total_interno: float
    monto_cuota_interno: float
    matricula_interno: float
    
    costo_total_externo: float
    monto_cuota_externo: float
    matricula_externo: float
    
    cantidad_cuotas: int
    descuento_general: Optional[float]
    
    observacion: Optional[str]
    requisitos: List[str]
    inscritos: List[PyObjectId]
    
    fecha_inicio: Optional[datetime]
    fecha_fin: Optional[datetime]
    activo: bool
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        allow_population_by_field_name = True
        arbitrary_types_allowed = True
        schema_extra = {
            "example": {
                "_id": "507f1f77bcf86cd799439012",
                "codigo": "DIPL-2024-001",
                "nombre_programa": "Diplomado en Ciencia de Datos",
                "tipo_curso": "diplomado",
                "modalidad": "híbrido",
                "costo_total_interno": 3000.0,
                "monto_cuota_interno": 500.0,
                "matricula_interno": 500.0,
                "costo_total_externo": 5000.0,
                "monto_cuota_externo": 900.0,
                "matricula_externo": 500.0,
                "cantidad_cuotas": 5,
                "descuento_general": 10.0,
                "observacion": "Incluye certificación internacional",
                "requisitos": ["Título profesional", "CV actualizado"],
                "inscritos": [],
                "fecha_inicio": "2024-03-01T00:00:00",
                "fecha_fin": "2024-08-31T00:00:00",
                "activo": True,
                "created_at": "2024-01-15T10:30:00",
                "updated_at": "2024-01-15T10:30:00"
            }
        }


class CourseUpdate(BaseModel):
    """
    Schema para actualizar un curso existente
    
    Uso: PATCH /courses/{id}
    
    Todos los campos son opcionales para permitir actualizaciones parciales.
    Los validadores se mantienen para asegurar coherencia de precios.
    """
    
    codigo: Optional[str] = None
    nombre_programa: Optional[str] = Field(None, min_length=1, max_length=300)
    tipo_curso: Optional[TipoCurso] = None
    modalidad: Optional[Modalidad] = None
    
    costo_total_interno: Optional[float] = Field(None, gt=0)
    monto_cuota_interno: Optional[float] = Field(None, gt=0)
    matricula_interno: Optional[float] = Field(None, ge=0)
    
    costo_total_externo: Optional[float] = Field(None, gt=0)
    monto_cuota_externo: Optional[float] = Field(None, gt=0)
    matricula_externo: Optional[float] = Field(None, ge=0)
    
    cantidad_cuotas: Optional[int] = Field(None, ge=1)
    descuento_general: Optional[float] = Field(None, ge=0, le=100)
    
    observacion: Optional[str] = None
    requisitos: Optional[List[str]] = None
    inscritos: Optional[List[PyObjectId]] = None
    
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: Optional[bool] = None
    
    class Config:
        schema_extra = {
            "example": {
                "nombre_programa": "Diplomado en Ciencia de Datos e IA",
                "descuento_general": 15.0,
                "activo": True
            }
        }
