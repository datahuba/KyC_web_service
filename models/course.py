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
import pymongo
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
    # PRECIO ÚNICO DEL PROGRAMA
    # ========================================================================
    # DECISIÓN DE NEGOCIO (2026-07-08): el precio del programa es EL MISMO
    # para todos los estudiantes, sin importar si son de Santa Cruz o de
    # otro lugar (Student.es_estudiante_interno sigue existiendo solo como
    # dato informativo de procedencia, ya NO determina el precio a pagar).
    # Los campos que antes se llamaban "costo_total_externo"/"matricula_externo"
    # se retiraron de este propósito; ver cargo_adicional_monto/concepto abajo
    # para el nuevo significado (gasto complementario opcional al programa).

    costo_total_interno: float = Field(
        ...,
        gt=0,
        description="Costo total (colegiatura) del programa. Precio único, aplica a todos los estudiantes por igual."
    )
    
    matricula_interno: float = Field(
        ...,
        ge=0,
        description="Costo de matrícula institucional. Precio único, aplica a todos los estudiantes por igual."
    )

    # ========================================================================
    # CARGO ADICIONAL (opcional): gasto complementario al programa
    # ========================================================================
    # Ej: "Taller de Excel Avanzado" con un costo extra de 100 Bs, necesario
    # o recomendado además de la colegiatura del programa. Si se define,
    # se suma al total a pagar de TODOS los estudiantes inscritos a este
    # curso (no es opcional por estudiante individual; es una condición del
    # programa en su conjunto). Si el usuario quiere que sea opcional por
    # estudiante, deberá gestionarse manualmente por ahora (fuera de alcance).
    cargo_adicional_monto: Optional[float] = Field(
        None,
        ge=0,
        description="Monto del cargo adicional/complementario al programa (ej. un taller incluido). None = sin cargo adicional."
    )

    cargo_adicional_concepto: Optional[str] = Field(
        None,
        max_length=200,
        description="Concepto/descripción del cargo adicional (ej. 'Taller de Excel Avanzado'). Obligatorio si cargo_adicional_monto está definido."
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
    
    def get_costo_total(self) -> float:
        """
        Obtiene el costo total (colegiatura) del programa. Precio único
        para todos los estudiantes (ISSUE-P-PRECIO-UNICO, 2026-07-08).
        """
        return self.costo_total_interno
    
    def calcular_monto_cuota(self) -> float:
        """
        Calcula el monto de cada cuota. Precio único para todos los estudiantes.
        """
        costo_total = self.get_costo_total()
        matricula = self.get_matricula()
        return (costo_total - matricula) / self.cantidad_cuotas
    
    def get_matricula(self) -> float:
        """Obtiene el costo de matrícula. Precio único para todos los estudiantes."""
        return self.matricula_interno
    
    class Settings:
        name = "courses"
        indexes = [
            # Índice único para búsquedas rápidas de validación de código
            pymongo.IndexModel([("codigo", pymongo.ASCENDING)], unique=True),
            # Índice simple para búsquedas de texto por nombre de diplomado
            "nombre_programa",
            # Índice compuesto para optimizar el filtrado de cursos activos en inscripciones
            [("activo", pymongo.ASCENDING), ("created_at", pymongo.DESCENDING)],
            # Índice simple de ordenamiento temporal
            [("created_at", pymongo.DESCENDING)]
        ]

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
                "cargo_adicional_monto": 100.0,
                "cargo_adicional_concepto": "Taller de Excel Avanzado (complementario)",
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
