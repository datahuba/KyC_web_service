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

Colección MongoDB: courses
"""

from datetime import datetime
from typing import Optional, List
from pydantic import Field, validator
from .base import MongoBaseModel, PyObjectId
from .enums import TipoCurso, Modalidad


class Course(MongoBaseModel):
    """
    Modelo de Curso/Programa Académico
    
    Representa un programa de posgrado que los estudiantes pueden cursar.
    
    ¿Qué información almacena?
    -------------------------
    
    1. IDENTIFICACIÓN:
       - codigo: Código único del curso
       - nombre_programa: Nombre descriptivo
       - tipo_curso: Curso, Taller, Diplomado, Maestría, etc.
       - modalidad: Presencial, Virtual, Híbrido
    
    2. PRECIOS PARA ESTUDIANTES INTERNOS:
       - costo_total_interno: Precio total para estudiantes de la U
       - matricula_interno: Costo de matrícula inicial
    
    3. PRECIOS PARA ESTUDIANTES EXTERNOS:
       - costo_total_externo: Precio total para público general
       - matricula_externo: Costo de matrícula inicial
    
    4. ESTRUCTURA DE PAGO:
       - cantidad_cuotas: En cuántas cuotas se puede dividir el pago
       - descuento_curso: Descuento del curso aplicable a todos
    
    5. INFORMACIÓN ADICIONAL:
       - observacion: Notas especiales del curso
       - inscritos: Lista de estudiantes inscritos
       - fechas: Inicio y fin del curso
    
    ¿Por qué precios diferenciados?
    ------------------------------
    La universidad ofrece precios preferenciales a sus propios estudiantes:
    
    Ejemplo: Diplomado en Ciencia de Datos
    - Estudiante interno: 3000 Bs total, 500 Bs cuota, 500 Bs matrícula
    - Estudiante externo: 5000 Bs total, 800 Bs cuota, 1000 Bs matrícula
    
    Esto permite:
    - Incentivar a estudiantes de la universidad
    - Mantener competitividad con otras instituciones
    - Generar ingresos del público general
    
    ¿Cómo funcionan las cuotas?
    --------------------------
    El costo total se divide en:
    1. Matrícula (pago inicial)
    2. N cuotas (pagos mensuales calculados automáticamente)
    
    Fórmula:
        monto_cuota = (costo_total - matricula) / cantidad_cuotas
    
    Ejemplo:
        5000 Bs total, 500 Bs matrícula, 5 cuotas
        → Cada cuota = (5000 - 500) / 5 = 900 Bs
    
    ¿Por qué validar los montos?
    ---------------------------
    Los validadores aseguran que:
    - Las cuotas sumen correctamente al total
    - No haya inconsistencias en los precios
    - Los datos sean coherentes antes de guardar
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
        ...,
        gt=0,
        description="Costo total del curso para estudiantes externos (público general)"
    )
    
    matricula_externo: float = Field(
        ...,
        ge=0,
        description="Costo de matrícula inicial para estudiantes externos"
    )
    
    # ========================================================================
    # ESTRUCTURA DE PAGO
    # ========================================================================
    
    cantidad_cuotas: int = Field(
        ...,
        ge=1,
        description="Número de cuotas en las que se puede dividir el pago"
    )
    
    descuento_curso: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Descuento del curso aplicable a todos los estudiantes (porcentaje)"
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
    # VALIDADORES
    # ========================================================================
    

    
    # ========================================================================
    # MÉTODOS HELPER
    # ========================================================================
    
    def get_costo_total(self, es_interno: bool) -> float:
        """
        Obtiene el costo total según el tipo de estudiante
        
        Args:
            es_interno: True si es estudiante interno, False si es externo
            
        Returns:
            Costo total correspondiente
        """
        return self.costo_total_interno if es_interno else self.costo_total_externo
    
    def calcular_monto_cuota(self, es_interno: bool) -> float:
        """
        Calcula el monto de cada cuota según el tipo de estudiante
        
        Fórmula: (costo_total - matricula) / cantidad_cuotas
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
                "descuento_curso": 10.0,
                "observacion": "Incluye certificación internacional",
                "fecha_inicio": "2024-03-01T00:00:00",
                "fecha_fin": "2024-08-31T00:00:00",
                "activo": True
            }
        }
