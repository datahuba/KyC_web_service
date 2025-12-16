"""
Modelo de Inscripción
====================

Representa la inscripción de un estudiante a un curso específico.
Colección MongoDB: enrollments
"""

from datetime import datetime
from typing import Optional
from pydantic import Field, field_validator
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoInscripcion, TipoEstudiante


class Enrollment(MongoBaseModel):
    """
    Modelo de Inscripción - Vincula estudiante con curso
    
    Diseño sin duplicación:
    -----------------------
    - NO guarda datos del estudiante (están en Student)
    - NO guarda datos del curso (están en Course)
    - SÍ guarda snapshot de precios al momento de inscripción
    - SÍ guarda resumen financiero (calculado desde Payments)
    
    ¿Por qué guardar precios?
    ------------------------
    Si el curso cambia de precio después de la inscripción,
    el estudiante mantiene el precio original que acordó pagar.
    
    Ejemplo:
    - Juan se inscribe cuando el curso costaba 3000 Bs
    - Después el curso sube a 4000 Bs
    - Juan sigue pagando 3000 Bs (su inscripción tiene el snapshot)
    """
    
    # ========================================================================
    # REFERENCIAS (IDs únicamente, no duplicar datos)
    # ========================================================================
    
    estudiante_id: PyObjectId = Field(
        ...,
        description="ID del estudiante inscrito"
    )
    
    curso_id: PyObjectId = Field(
        ...,
        description="ID del curso"
    )
    
    # ========================================================================
    # SNAPSHOT DE PRECIOS (momento de inscripción)
    # ========================================================================
    
    es_estudiante_interno: TipoEstudiante = Field(
        ...,
        description="Tipo de estudiante al momento de inscribirse (snapshot)"
    )
    
    costo_total: float = Field(
        ...,
        gt=0,
        description="Costo total del curso para este estudiante (copiado de Course)"
    )
    
    costo_matricula: float = Field(
        ...,
        ge=0,
        description="Costo de matrícula (copiado de Course)"
    )
    
    cantidad_cuotas: int = Field(
        ...,
        ge=1,
        description="Cantidad de cuotas para pagar (copiado de Course)"
    )
    
    # ========================================================================
    # DESCUENTOS APLICADOS
    # ========================================================================
    
    # ========================================================================
    # DESCUENTOS APLICADOS (Snapshots y Referencias)
    # ========================================================================
    
    # 1. Descuento del Curso
    descuento_curso_id: Optional[PyObjectId] = Field(
        None,
        description="ID del descuento que tenía el curso al momento de inscribirse"
    )
    
    descuento_curso_aplicado: float = Field(
        default=0.0,
        ge=0,
        le=100,
        description="Porcentaje de descuento del curso aplicado (Snapshot)"
    )
    
    # 2. Descuento del Estudiante (Seleccionado al inscribir)
    descuento_estudiante_id: Optional[PyObjectId] = Field(
        None,
        description="ID del descuento seleccionado para el estudiante"
    )
    
    descuento_personalizado: Optional[float] = Field(
        None,
        ge=0,
        le=100,
        description="Porcentaje de descuento del estudiante aplicado (Snapshot)"
    )
    
    # ========================================================================
    # TOTALES FINANCIEROS
    # ========================================================================
    
    total_a_pagar: float = Field(
        ...,
        ge=0,
        description="Total final a pagar (con todos los descuentos aplicados)"
    )
    
    total_pagado: float = Field(
        default=0.0,
        ge=0,
        description="Total pagado hasta ahora (suma de Payments APROBADOS)"
    )
    
    saldo_pendiente: float = Field(
        ...,
        ge=0,
        description="Saldo pendiente de pago (total_a_pagar - total_pagado)"
    )
    
    # ========================================================================
    # ESTADO Y FECHAS
    # ========================================================================
    
    fecha_inscripcion: datetime = Field(
        default_factory=datetime.utcnow,
        description="Fecha y hora de inscripción"
    )
    
    estado: EstadoInscripcion = Field(
        default=EstadoInscripcion.PENDIENTE_PAGO,
        description="Estado actual de la inscripción"
    )
    
    # ========================================================================
    # VALIDADORES
    # ========================================================================
    
    @field_validator('saldo_pendiente')
    @classmethod
    def validar_saldo(cls, v, info):
        """Valida que el saldo pendiente sea correcto"""
        if 'total_a_pagar' in info.data and 'total_pagado' in info.data:
            calculado = info.data['total_a_pagar'] - info.data['total_pagado']
            
            # Si hay sobrepago (calculado < 0), el saldo debe ser 0
            esperado = max(0.0, calculado)
            
            if abs(v - esperado) > 0.01:  # Tolerancia de 1 centavo
                raise ValueError(
                    f"Saldo pendiente inválido: {v} Bs. "
                    f"Debería ser {esperado:.2f} Bs "
                    f"(total_a_pagar {info.data['total_a_pagar']} - "
                    f"total_pagado {info.data['total_pagado']})"
                )
        return v
    
    # ========================================================================
    # MÉTODOS
    # ========================================================================
    
    def calcular_monto_cuota(self) -> float:
        """
        Calcula el monto de cada cuota
        
        Fórmula: (total_a_pagar - costo_matricula) / cantidad_cuotas
        
        Returns:
            Monto de cada cuota en Bs
        """
        if self.cantidad_cuotas == 0:
            return 0.0
        return (self.total_a_pagar - self.costo_matricula) / self.cantidad_cuotas
    
    def actualizar_saldo(self, monto_pago_aprobado: float):
        """
        Actualiza el saldo cuando se aprueba un pago
        
        Args:
            monto_pago_aprobado: Monto del pago que fue aprobado
        """
        self.total_pagado += monto_pago_aprobado
        self.saldo_pendiente = max(0, self.total_a_pagar - self.total_pagado)
        self.updated_at = datetime.utcnow()
    
    def esta_completamente_pagado(self) -> bool:
        """Verifica si la inscripción está completamente pagada"""
        return self.saldo_pendiente <= 0.01  # Tolerancia de 1 centavo
    
    @property
    def siguiente_pago(self) -> dict:
        """
        Calcula los detalles del siguiente pago sugerido.
        
        Returns:
            dict: {
                "concepto": str,       # "Matrícula" o "Cuota X"
                "numero_cuota": int,   # 0 para matrícula, 1-N para cuotas
                "monto_sugerido": float
            }
        """
        if self.esta_completamente_pagado():
            return {
                "concepto": "Pago Completado",
                "numero_cuota": 0,
                "monto_sugerido": 0.0
            }
            
        # 1. Verificar Matrícula
        if self.total_pagado < self.costo_matricula:
            pendiente_matricula = self.costo_matricula - self.total_pagado
            # Si el pendiente es muy pequeño (por errores de redondeo), asumimos pagado
            if pendiente_matricula > 0.01:
                return {
                    "concepto": "Matrícula",
                    "numero_cuota": 0,
                    "monto_sugerido": round(pendiente_matricula, 2)
                }
        
        # 2. Calcular Cuotas
        # Saldo disponible para cuotas
        pagado_a_cuotas = max(0.0, self.total_pagado - self.costo_matricula)
        total_a_pagar_cuotas = self.total_a_pagar - self.costo_matricula
        
        if self.cantidad_cuotas > 0:
            monto_por_cuota = total_a_pagar_cuotas / self.cantidad_cuotas
            
            # Cuántas cuotas enteras se han pagado
            cuotas_pagadas = int(pagado_a_cuotas / monto_por_cuota)
            
            # La siguiente cuota
            siguiente_cuota = cuotas_pagadas + 1
            
            # Si es la última cuota, ajustamos el monto al saldo pendiente real
            if siguiente_cuota >= self.cantidad_cuotas:
                siguiente_cuota = self.cantidad_cuotas
                monto_sugerido = self.saldo_pendiente
            else:
                monto_sugerido = monto_por_cuota
                
            return {
                "concepto": f"Cuota {siguiente_cuota}",
                "numero_cuota": siguiente_cuota,
                "monto_sugerido": round(monto_sugerido, 2)
            }
            
        # Fallback (si no hay cuotas definidas pero hay saldo)
        return {
            "concepto": "Pago Pendiente",
            "numero_cuota": 1,
            "monto_sugerido": round(self.saldo_pendiente, 2)
        }
    
    class Settings:
        name = "enrollments"
