"""
Schemas de Curso
================

Define los schemas Pydantic para operaciones CRUD de cursos.

Schemas incluidos:
-----------------
1. CourseCreate: Para crear nuevos cursos
2. CourseResponse: Para mostrar cursos
3. CourseUpdate: Para actualizar cursos
4. CourseEnrolledStudent: Reporte de estudiantes inscritos
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from models.enums import TipoCurso, Modalidad, EstadoInscripcion, TipoEstudiante
from models.base import PyObjectId
from schemas.requisito import RequisitoTemplateCreate


class CourseCreate(BaseModel):
    """
    Schema para crear un nuevo curso
    
    Uso: POST /courses/
    
    ¿Qué incluye?
    ------------
    - Identificación (código, nombre, tipo, modalidad)
    - Precios para internos (costo total, matrícula)
    - Precios para externos (costo total, matrícula)
    - Estructura de pago (cantidad de cuotas, descuento del curso)
    - Información adicional (observación, fechas)
    
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
    matricula_interno: float = Field(..., ge=0)
    
    # Precios externos (opcionales; si no se envían, se asumen en 0)
    costo_total_externo: float = Field(0, ge=0)
    matricula_externo: float = Field(0, ge=0)
    
    # Estructura de pago
    cantidad_cuotas: int = Field(..., ge=1)
    descuento_curso: Optional[float] = Field(None, ge=0, le=100)
    descuento_id: Optional[PyObjectId] = None
    
    # Información adicional
    observacion: Optional[str] = None
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: bool = True
    
    # Requisitos
    requisitos: List[RequisitoTemplateCreate] = Field(
        default_factory=list,
        description="Lista de requisitos que debe cumplir el estudiante al inscribirse"
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "codigo": "DIP-SGC-2024",
                "nombre_programa": "Diplomado en Sistemas de Gestión de Calidad ISO 9001:2015",
                "tipo_curso": "diplomado",
                "modalidad": "hibrido",
                "costo_total_interno": 3500.0,
                "matricula_interno": 600.0,
                "costo_total_externo": 4500.0,
                "matricula_externo": 700.0,
                "cantidad_cuotas": 5,
                "descuento_id": "507f1f77bcf86cd799439077",
                "observacion": "Incluye materiales didácticos y certificación internacional",
                "fecha_inicio": "2024-03-15T00:00:00",
                "fecha_fin": "2024-09-30T00:00:00",
                "activo": True,
                "requisitos": [
                    {"descripcion": "Curriculum Vitae actualizado"},
                    {"descripcion": "Fotocopia de Cédula de Identidad (ambos lados)"},
                    {"descripcion": "Título profesional en provisión nacional o certificado de egreso"}
                ]
            }
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
    matricula_interno: float
    
    costo_total_externo: float
    matricula_externo: float
    
    cantidad_cuotas: int
    descuento_curso: Optional[float]
    descuento_id: Optional[PyObjectId]
    
    observacion: Optional[str]
    inscritos: List[PyObjectId]
    
    fecha_inicio: Optional[datetime]
    fecha_fin: Optional[datetime]
    activo: bool
    
    requisitos: List[RequisitoTemplateCreate] = Field(
        default_factory=list,
        description="Requisitos del curso"
    )
    
    created_at: datetime
    updated_at: datetime
    
    
    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True,
        "json_schema_extra": {
            "example": {
                "_id": "507f1f77bcf86cd799439012",
                "codigo": "DIP-SGC-2024",
                "nombre_programa": "Diplomado en Sistemas de Gestión de Calidad ISO 9001:2015",
                "tipo_curso": "diplomado",
                "modalidad": "hibrido",
                "costo_total_interno": 3500.0,
                "matricula_interno": 600.0,
                "costo_total_externo": 4500.0,
                "matricula_externo": 700.0,
                "cantidad_cuotas": 5,
                "descuento_id": "507f1f77bcf86cd799439077",
                "descuento_curso": 10.0,
                "observacion": "Incluye materiales didácticos y certificación internacional",
                "inscritos": ["507f1f77bcf86cd799439011"],
                "fecha_inicio": "2024-03-15T00:00:00",
                "fecha_fin": "2024-09-30T00:00:00",
                "activo": True,
                "requisitos": [
                    {"descripcion": "Curriculum Vitae actualizado"},
                    {"descripcion": "Fotocopia de Cédula de Identidad"}
                ],
                "created_at": "2024-02-01T10:30:00",
                "updated_at": "2024-02-01T10:30:00"
            }
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
    matricula_interno: Optional[float] = Field(None, ge=0)
    
    costo_total_externo: Optional[float] = Field(None, ge=0)
    matricula_externo: Optional[float] = Field(None, ge=0)
    
    cantidad_cuotas: Optional[int] = Field(None, ge=1)
    descuento_curso: Optional[float] = Field(None, ge=0, le=100)
    descuento_id: Optional[PyObjectId] = None
    
    observacion: Optional[str] = None
    inscritos: Optional[List[PyObjectId]] = None
    
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: Optional[bool] = None
    
    requisitos: Optional[List[RequisitoTemplateCreate]] = None
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre_programa": "Diplomado en Sistemas de Gestión de Calidad ISO 9001:2015 y 14001:2015",
                "costo_total_interno": 3800.0,
                "activo": True
            }
        }
    }


# ============================================================================
# SCHEMAS DE REPORTE
# ============================================================================

class StudentContactInfo(BaseModel):
    email: Optional[str] = None
    celular: Optional[str] = None

class EnrollmentInfo(BaseModel):
    id: PyObjectId
    fecha_inscripcion: datetime
    estado: EstadoInscripcion
    tipo_estudiante: TipoEstudiante

class FinancialInfo(BaseModel):
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    avance_pago: float = Field(..., description="Porcentaje de pago completado (0-100)")

class CourseEnrolledStudent(BaseModel):
    """
    Schema para reporte de estudiantes inscritos en un curso.
    Combina datos del estudiante y de su inscripción.
    """
    estudiante_id: PyObjectId
    nombre: Optional[str] = "Sin nombre"
    carnet: Optional[str] = None
    contacto: StudentContactInfo
    inscripcion: EnrollmentInfo
    financiero: FinancialInfo

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }
