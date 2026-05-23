"""
Modelo de Inscripción
====================

Representa la inscripción de un estudiante a un curso específico.
Colección MongoDB: enrollments
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoInscripcion, TipoEstudiante
from .requisito import Requisito

# ========================================================================
# SUB-MODELO: ESTADO DEL MÓDULO (NUEVO)
# ========================================================================
class ModuloEstado(BaseModel):
    """
    Copia del módulo del curso para este estudiante específico.
    Lleva el control de si el estudiante ya pagó esta cuota/módulo o no.
    """
    nombre: str = Field(..., description="Nombre del módulo (Ej: Módulo 1)")
    costo: float = Field(..., ge=0, description="Costo que debe pagar por este módulo")
    estado: str = Field(default="Pendiente", description="Puede ser: Pendiente, Parcial, Pagado")
    monto_pagado: float = Field(default=0.0, ge=0, description="Cuánto ha pagado de este módulo")


class Enrollment(MongoBaseModel):
    """
    Modelo de Inscripción - Vincula estudiante con curso
    """
    
    # ========================================================================
    # REFERENCIAS (IDs únicamente, no duplicar datos)
    # ========================================================================
    
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante inscrito")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    
    # ========================================================================
    # SNAPSHOT DE PRECIOS Y MÓDULOS (momento de inscripción)
    # ========================================================================
    
    es_estudiante_interno: TipoEstudiante = Field(..., description="Tipo de estudiante al momento de inscribirse (snapshot)")
    
    costo_total: float = Field(..., gt=0, description="Costo total del curso para este estudiante")
    costo_matricula: float = Field(..., ge=0, description="Costo de matrícula")
    cantidad_cuotas: int = Field(..., ge=1, description="Cantidad de cuotas para pagar")
    
    modulos: List[ModuloEstado] = Field(
        default_factory=list,
        description="Fotocopia de los módulos del curso con el estado de pago del estudiante"
    )
    
    # ========================================================================
    # DESCUENTOS APLICADOS (Snapshots y Referencias)
    # ========================================================================
    
    descuento_curso_id: Optional[PyObjectId] = Field(None, description="ID del descuento del curso")
    descuento_curso_aplicado: float = Field(default=0.0, ge=0, le=100)
    
    descuento_estudiante_id: Optional[PyObjectId] = Field(None, description="ID del descuento seleccionado para el estudiante")
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    
    # ========================================================================
    # TOTALES FINANCIEROS
    # ========================================================================
    
    total_a_pagar: float = Field(..., ge=0, description="Total final a pagar")
    total_pagado: float = Field(default=0.0, ge=0, description="Total pagado hasta ahora")
    saldo_pendiente: float = Field(..., ge=0, description="Saldo pendiente de pago")
    
    # ========================================================================
    # ESTADO Y FECHAS
    # ========================================================================
    
    fecha_inscripcion: datetime = Field(default_factory=datetime.utcnow)
    estado: EstadoInscripcion = Field(default=EstadoInscripcion.PENDIENTE_PAGO)
    
    # ========================================================================
    # REQUISITOS (DOCUMENTACIÓN)
    # ========================================================================
    
    requisitos: List['Requisito'] = Field(default_factory=list)
    nota_final: Optional[float] = Field(None, ge=0, le=100)
    
# >>> AGREGAR ESTE CAMPO AL FINAL DE LOS ATRIBUTOS <<<
    matricula_pagada: bool = Field(default=False, description="¿Ya pagó la matrícula el estudiante para este curso?")

    # ========================================================================
    # VALIDADORES
    # ========================================================================
    
    @field_validator('saldo_pendiente')
    @classmethod
    def validar_saldo(cls, v, info):
        if 'total_a_pagar' in info.data and 'total_pagado' in info.data:
            calculado = info.data['total_a_pagar'] - info.data['total_pagado']
            esperado = max(0.0, calculado)
            if abs(v - esperado) > 0.01:
                raise ValueError(f"Saldo pendiente inválido")
        return v
    
    # ========================================================================
    # MÉTODOS
    # ========================================================================
    
    def calcular_monto_cuota(self) -> float:
        if self.cantidad_cuotas == 0:
            return 0.0
        return (self.total_a_pagar - self.costo_matricula) / self.cantidad_cuotas
    
    def actualizar_saldo(self, monto_pago_aprobado: float):
        self.total_pagado += monto_pago_aprobado
        self.saldo_pendiente = max(0, self.total_a_pagar - self.total_pagado)
        self.updated_at = datetime.utcnow()
    
    def esta_completamente_pagado(self) -> bool:
        return self.saldo_pendiente <= 0.01
    
    @property
    def siguiente_pago(self) -> dict:
        """
        Calcula los detalles del siguiente pago sugerido.
        """
        if self.esta_completamente_pagado():
            return {"concepto": "Pago Completado", "numero_cuota": 0, "monto_sugerido": 0.0}
            
        if self.total_pagado < self.costo_matricula:
            pendiente_matricula = self.costo_matricula - self.total_pagado
            if pendiente_matricula > 0.01:
                return {"concepto": "Matrícula", "numero_cuota": 0, "monto_sugerido": round(pendiente_matricula, 2)}
        
        # AHORA TAMBIÉN PODRÍA LEER LA LISTA DE MÓDULOS PENDIENTES
        for i, mod in enumerate(self.modulos):
            if mod.estado != "Pagado":
                monto_sugerido = mod.costo - mod.monto_pagado
                return {
                    "concepto": mod.nombre,
                    "numero_cuota": i + 1,
                    "monto_sugerido": round(monto_sugerido, 2)
                }
                
        # Fallback
        return {"concepto": "Pago Pendiente", "numero_cuota": 1, "monto_sugerido": round(self.saldo_pendiente, 2)}
    
    @property
    def cuotas_pagadas_info(self) -> dict:
        if self.cantidad_cuotas == 0:
            return {"cuotas_pagadas": 0, "cuotas_totales": 0, "porcentaje": 0.0}
        
        pagado_a_cuotas = max(0.0, self.total_pagado - self.costo_matricula)
        total_a_pagar_cuotas = self.total_a_pagar - self.costo_matricula
        monto_por_cuota = total_a_pagar_cuotas / self.cantidad_cuotas if total_a_pagar_cuotas > 0 else 0
        
        cuotas_pagadas = int(pagado_a_cuotas / monto_por_cuota) if monto_por_cuota > 0 else 0
        cuotas_pagadas = min(cuotas_pagadas, self.cantidad_cuotas)
        porcentaje = (cuotas_pagadas / self.cantidad_cuotas * 100) if self.cantidad_cuotas > 0 else 0.0
        
        return {"cuotas_pagadas": cuotas_pagadas, "cuotas_totales": self.cantidad_cuotas, "porcentaje": round(porcentaje, 2)}
    
    class Settings:
        name = "enrollments"