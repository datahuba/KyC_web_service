"""
Modelo de Descuento
==================

Este módulo define el modelo de datos para descuentos aplicables a estudiantes.

¿Por qué existe este modelo?
----------------------------
Los descuentos permiten ofrecer precios especiales a ciertos estudiantes:
1. Descuentos por grupo (ej: empleados de la universidad)
2. Descuentos promocionales (ej: early bird)
3. Becas parciales
4. Descuentos por curso específico

Colección MongoDB: discounts
"""

from datetime import datetime
from typing import Optional, List
from pydantic import Field, validator
from .base import MongoBaseModel, PyObjectId


class Discount(MongoBaseModel):
    """
    Modelo de Descuento
    
    Representa un descuento que puede aplicarse a uno o más estudiantes.
    
    ¿Qué información almacena?
    -------------------------
    
    1. IDENTIFICACIÓN:
       - nombre: Nombre descriptivo del descuento
       - porcentaje: Cuánto descuento se aplica (0-100%)
    
    2. APLICABILIDAD:
       - lista_estudiantes: Qué estudiantes tienen este descuento
       - curso_id: Si es específico de un curso (opcional)
    
    3. VIGENCIA:
       - fecha_inicio: Desde cuándo es válido
       - fecha_fin: Hasta cuándo es válido
       - activo: Si se puede usar actualmente
    
    ¿Cómo funcionan los descuentos?
    ------------------------------
    
    Tipos de descuentos:
    
    1. DESCUENTO GENERAL (sin curso_id):
       - Se aplica a cualquier curso
       - Ejemplo: "Empleados de la universidad: 20% en todos los cursos"
    
    2. DESCUENTO POR CURSO (con curso_id):
       - Solo válido para un curso específico
       - Ejemplo: "Early bird Diplomado IA: 15% de descuento"
    
    3. DESCUENTO TEMPORAL (con fechas):
       - Solo válido en un período
       - Ejemplo: "Promoción verano 2024: 10% hasta 31/03"
    
    4. DESCUENTO PERMANENTE (sin fechas):
       - Siempre válido mientras activo=True
       - Ejemplo: "Beca excelencia académica: 50%"
    
    ¿Cómo se aplican?
    ----------------
    Al crear una inscripción:
    1. Se buscan descuentos del estudiante
    2. Se filtran por curso (si aplica)
    3. Se filtran por fecha (si aplica)
    4. Se aplica el descuento más alto
    
    Ejemplo:
        Curso: 5000 Bs
        Descuento: 20%
        Total a pagar: 5000 - (5000 × 0.20) = 4000 Bs
    
    ¿Por qué lista de estudiantes?
    -----------------------------
    Permite descuentos grupales:
    - Agregar múltiples estudiantes al mismo descuento
    - Fácil gestión de becas grupales
    - Reportes de quién tiene descuentos
    """
    
    # ========================================================================
    # IDENTIFICACIÓN
    # ========================================================================
    
    nombre: str = Field(
        ...,
        min_length=1,
        max_length=200,
        description="Nombre descriptivo del descuento (ej: 'Beca Excelencia 2024')"
    )
    
    porcentaje: float = Field(
        ...,
        ge=0,
        le=100,
        description="Porcentaje de descuento (0-100)"
    )
    
    # ========================================================================
    # APLICABILIDAD
    # ========================================================================
    
    lista_estudiantes: List[PyObjectId] = Field(
        default_factory=list,
        description="Lista de IDs de estudiantes que tienen este descuento"
    )
    
    curso_id: Optional[PyObjectId] = Field(
        None,
        description=(
            "ID del curso al que aplica este descuento. "
            "Si es None, el descuento aplica a cualquier curso."
        )
    )
    
    # ========================================================================
    # VIGENCIA
    # ========================================================================
    
    fecha_inicio: Optional[datetime] = Field(
        None,
        description="Fecha desde la cual el descuento es válido (None = sin límite)"
    )
    
    fecha_fin: Optional[datetime] = Field(
        None,
        description="Fecha hasta la cual el descuento es válido (None = sin límite)"
    )
    
    activo: bool = Field(
        default=True,
        description="Si el descuento está activo y puede ser usado"
    )
    
    # ========================================================================
    # VALIDADORES
    # ========================================================================
    
    @validator('fecha_fin')
    def validar_fechas(cls, v, values):
        """
        Valida que la fecha de fin sea posterior a la fecha de inicio
        
        ¿Por qué validar?
        ----------------
        Previene errores como:
        - Descuentos que "terminan antes de empezar"
        - Períodos de vigencia inválidos
        """
        if v and 'fecha_inicio' in values and values['fecha_inicio']:
            if v < values['fecha_inicio']:
                raise ValueError(
                    "La fecha de fin debe ser posterior a la fecha de inicio"
                )
        return v
    
    # ========================================================================
    # MÉTODOS HELPER
    # ========================================================================
    
    def es_valido_en_fecha(self, fecha: datetime) -> bool:
        """
        Verifica si el descuento es válido en una fecha específica
        
        Args:
            fecha: Fecha a verificar
            
        Returns:
            True si el descuento es válido en esa fecha
            
        Ejemplo:
            descuento.es_valido_en_fecha(datetime.now())
        """
        if not self.activo:
            return False
        
        if self.fecha_inicio and fecha < self.fecha_inicio:
            return False
        
        if self.fecha_fin and fecha > self.fecha_fin:
            return False
        
        return True
    
    def aplica_a_curso(self, curso_id: PyObjectId) -> bool:
        """
        Verifica si el descuento aplica a un curso específico
        
        Args:
            curso_id: ID del curso a verificar
            
        Returns:
            True si el descuento aplica a ese curso
            
        Lógica:
            - Si curso_id es None → aplica a todos los cursos
            - Si curso_id tiene valor → solo aplica a ese curso
        """
        if self.curso_id is None:
            return True  # Descuento general
        
        return self.curso_id == curso_id
    
    def calcular_descuento(self, monto: float) -> float:
        """
        Calcula el monto de descuento para un precio dado
        
        Args:
            monto: Precio original
            
        Returns:
            Monto del descuento
            
        Ejemplo:
            descuento.porcentaje = 20
            descuento.calcular_descuento(5000) → 1000
        """
        return monto * (self.porcentaje / 100)
    
    class Config:
        """Configuración y ejemplos de uso"""
        schema_extra = {
            "examples": [
                {
                    "nombre": "Beca Excelencia Académica",
                    "porcentaje": 50.0,
                    "lista_estudiantes": ["507f1f77bcf86cd799439011"],
                    "curso_id": None,  # Aplica a todos los cursos
                    "fecha_inicio": None,
                    "fecha_fin": None,
                    "activo": True
                },
                {
                    "nombre": "Early Bird Diplomado IA",
                    "porcentaje": 15.0,
                    "lista_estudiantes": [],
                    "curso_id": "507f1f77bcf86cd799439012",  # Solo para este curso
                    "fecha_inicio": "2024-01-01T00:00:00",
                    "fecha_fin": "2024-02-28T23:59:59",
                    "activo": True
                },
                {
                    "nombre": "Descuento Empleados Universidad",
                    "porcentaje": 20.0,
                    "lista_estudiantes": [
                        "507f1f77bcf86cd799439011",
                        "507f1f77bcf86cd799439013"
                    ],
                    "curso_id": None,
                    "fecha_inicio": None,
                    "fecha_fin": None,
                    "activo": True
                }
            ]
        }
