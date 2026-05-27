"""
Modelo de Curso
===============

Este módulo define el modelo de datos para los cursos/programas académicos.

¿Por qué existe este modelo?
----------------------------
Los cursos son los programas que la universidad ofrece. Necesitamos almacenar:
1. Información descriptiva (nombre, tipo, modalidad)
2. Precios diferenciados (internos vs externos)
3. Estructura de pago (cuotas, matrícula)
4. Estudiantes inscritos
5. Requisitos y fechas
6. Módulos que componen el curso (NUEVO)

Colección MongoDB: courses
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, validator
from .base import MongoBaseModel, PyObjectId
from .enums import TipoCurso, Modalidad
from .requisito import RequisitoTemplate

# ========================================================================
# SUB-MODELO: MÓDULOS DEL CURSO
# ========================================================================
class Modulo(BaseModel):
    """
    Representa un submódulo dentro de un diplomado o curso.
    Sirve como base para generar el plan de pagos del estudiante.
    """
    nombre: str = Field(..., description="Nombre del módulo (Ej: Módulo 1: IA)")
    costo: float = Field(..., ge=0, description="Costo individual de este módulo")
    
    # ISSUE R: Asignación granular de docente a nivel de módulo
    docente_id: Optional[PyObjectId] = Field(
        None, 
        description="ID del docente asignado a impartir y calificar este módulo"
    )


class Course(MongoBaseModel):
    """
    Modelo de Curso/Programa Académico
    
    Representa un programa de posgrado que los estudiantes pueden cursar.
    """
    
    # ========================================================================
    # IDENTIFICACIÓN
    # ========================================================================
    
    codigo: str = Field(
        ...,
        description="Código único del curso (ej: DIPL-2024-001)"
    )
    
    nombre_programa: str = Field(
        ...,
        min_length=1,
        max_length=300,
        description="Nombre completo del programa académico"
    )
    
    tipo_curso: TipoCurso = Field(
        ...,
        description="Tipo de programa: curso, taller, diplomado, maestría, doctorado, otro"
    )
    
    modalidad: Modalidad = Field(
        ...,
        description="Modalidad de enseñanza: presencial, virtual, híbrido"
    )
    
    # ========================================================================
    # PRECIOS PARA ESTUDIANTES INTERNOS
    # ========================================================================
    
    costo_total_interno: float = Field(
        ...,
        gt=0,
        description="Costo total del curso para estudiantes de la universidad"
    )
    
    matricula_interno: float = Field(
        ...,
        ge=0,
        description="Costo de matrícula inicial para estudiantes internos"
    )
    
    # ========================================================================
    # PRECIOS PARA ESTUDIANTES EXTERNOS
    # ========================================================================
    
    costo_total_externo: float = Field(
        0,
        ge=0,
        description="Costo total del curso para estudiantes externos (público general)"
    )
    
    matricula_externo: float = Field(
        ...,
        ge=0,
        description="Costo de matrícula inicial para estudiantes externos"
    )
    
    # ========================================================================
    # ESTRUCTURA DE PAGO Y MÓDULOS
    # ========================================================================
    
    cantidad_cuotas: int = Field(
        ...,
        ge=1,
        description="Número de cuotas en las que se puede dividir el pago"
    )

    modulos: List[Modulo] = Field(
        default_factory=list,
        description="Lista de módulos que componen el curso (con sus respectivos costos)"
    )
    
    descuento_curso: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Descuento del curso aplicable a todos los estudiantes (porcentaje)"
    )
    
    descuento_id: Optional[PyObjectId] = Field(
        None,
        description="ID del descuento asociado a este curso (opcional)"
    )
    
    # ========================================================================
    # INFORMACIÓN ADICIONAL
    # ========================================================================
    
    observacion: Optional[str] = Field(
        None,
        description="Observaciones especiales del curso (ej: 'Se usa cuando tipo_curso es OTRO')"
    )
    
    inscritos: List[PyObjectId] = Field(
        default_factory=list,
        description="Lista de IDs de estudiantes inscritos en este curso"
    )
    
    # ========================================================================
    # FECHAS
    # ========================================================================
    
    fecha_inicio: Optional[datetime] = Field(
        None,
        description="Fecha de inicio del curso"
    )
    
    fecha_fin: Optional[datetime] = Field(
        None,
        description="Fecha de finalización del curso"
    )
    
    # ========================================================================
    # ESTADO
    # ========================================================================
    
    activo: bool = Field(
        default=True,
        description="Si el curso está activo y acepta inscripciones"
    )
    
    # ========================================================================
    # REQUISITOS (DOCUMENTACIÓN)
    # ========================================================================
    
    requisitos: List['RequisitoTemplate'] = Field(
        default_factory=list,
        description="Lista de requisitos/documentos que debe presentar el estudiante al inscribirse"
    )
    
    # ========================================================================
    # MÉTODOS HELPER
    # ========================================================================
    
    def get_costo_total(self, es_interno: bool) -> float:
        """
        Obtiene el costo total según el tipo de estudiante
        """
        return self.costo_total_interno if es_interno else self.costo_total_externo
    
    def calcular_monto_cuota(self, es_interno: bool) -> float:
        """
        Calcula el monto de cada cuota según el tipo de estudiante
        """
        costo_total = self.get_costo_total(es_interno)
        matricula = self.get_matricula(es_interno)
        return (costo_total - matricula) / self.cantidad_cuotas
    
    def get_matricula(self, es_interno: bool) -> float:
        """Obtiene el costo de matrícula según el tipo de estudiante"""
        return self.matricula_interno if es_interno else self.matricula_externo
    
    class Settings:
        name = "courses"

    class Config:
        """Configuración y ejemplo de uso"""
        schema_extra = {
            "example": {
                "codigo": "DIPL-2024-001",
                "nombre_programa": "Diplomado en Ciencia de Datos",
                "tipo_curso": "diplomado",
                "modalidad": "híbrido",
                "costo_total_interno": 3000.0,
                "matricula_interno": 500.0,
                "costo_total_externo": 5000.0,
                "matricula_externo": 500.0,
                "cantidad_cuotas": 5,
                "modulos": [
                    {"nombre": "Módulo 1", "costo": 500.0, "docente_id": "60a7f1c4e1f4b8c9d4b8e5c1"}
                ],
                "descuento_curso": 10.0,
                "observacion": "Incluye certificación internacional",
                "fecha_inicio": "2024-03-01T00:00:00",
                "fecha_fin": "2024-08-31T00:00:00",
                "activo": True
            }
        }
        