"""
Modelo de Inscripción
====================

Representa la inscripción de un estudiante a un curso específico.
Colección MongoDB: enrollments
"""

from datetime import datetime
from core.timezone_utils import utcnow_naive
from typing import Optional, List
import pymongo
from pydantic import BaseModel, Field, field_validator
from .base import MongoBaseModel, PyObjectId
from .enums import EstadoInscripcion
from .requisito import Requisito

# ========================================================================
# SUB-MODELO: ESTADO DEL MÓDULO (FINANCIERO Y ACADÉMICO)
# ========================================================================
class ModuloEstado(BaseModel):
    """
    Copia del módulo del curso para este estudiante específico.
    Lleva el control financiero (pagos) y académico (notas) del módulo.
    """
    nombre: str = Field(..., description="Nombre del módulo (Ej: Módulo 1)")
    
    # --- Control Financiero ---
    costo: float = Field(..., ge=0, description="Costo que debe pagar por este módulo")
    estado: str = Field(default="Pendiente", description="Puede ser: Pendiente, Parcial, Pagado")
    monto_pagado: float = Field(default=0.0, ge=0, description="Cuánto ha pagado de este módulo")
    
    # --- Control Académico (ISSUE P) ---
    nota: Optional[float] = Field(default=None, ge=0, le=100, description="Calificación obtenida en el módulo (0-100)")
    estado_academico: str = Field(default="Cursando", description="Puede ser: Cursando, Aprobado, Reprobado")

    # F-CUENTAS-POR-COBRAR (2026-07-29): marca cuándo Sandra/Rocío (encargado
    # del programa) habilitó manualmente este módulo como "en curso". Solo los
    # módulos con iniciado_en != null cuentan para la CxC real (a la fecha).
    # El Módulo 1 de enrollments activos se backfillea con fecha_inscripcion en
    # el script scripts/backfill_modulo_iniciado.py.
    iniciado_en: Optional[datetime] = Field(
        default=None,
        description="UTC. Cuándo el encargado del programa marcó este módulo como 'en curso'. None = aún no se ha iniciado.",
    )

    # F-MODULOS-MODAL (2026-07-31): marca cuándo el encargado marcó este
    # módulo como "finalizado/cerrado" (el estudiante ya terminó de cursarlo).
    # Un módulo finalizado NO puede volver a abrirse para pagos -- el siguiente
    # paso es calcular la nota final. Se implementó para que el kardex pueda
    # tener el ciclo completo: Pendiente → En curso → Finalizado.
    finalizado_en: Optional[datetime] = Field(
        default=None,
        description="UTC. Cuándo el encargado cerró este módulo. None = aún no se cerró.",
    )

    # ISSUE-P-RECALCULO-NOTA: costo de respaldo sin el descuento personal (beca)
    costo_sin_beca_personal: Optional[float] = Field(
        default=None, ge=0,
        description="Costo de este módulo aplicando solo el descuento del curso, sin el descuento personal. Referencia si el estudiante pierde la beca por nota."
    )

    # ISSUE-Q-NOTA-BORRADOR: nota propuesta por el docente, pendiente de validación de CPD
    nota_borrador: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="Nota propuesta por el docente, pendiente de validación de CPD. No afecta cálculos hasta ser validada."
    )
    estado_validacion_nota: str = Field(
        default="sin_borrador",
        description="'sin_borrador' | 'pendiente_validacion' | 'validada'"
    )


# ========================================================================
# SUB-MODELO: SNAPSHOT DE UN ÍTEM DE CARGO ADICIONAL (ISSUE-P-CARGO-MULTIITEM)
# ========================================================================
class CargoAdicionalItemSnapshot(BaseModel):
    """Copia (snapshot) de un ítem de Course.cargo_adicional_items al momento de inscribirse."""
    nombre: str = Field(..., description="Concepto del ítem (ej. 'Taller de Excel Avanzado')")
    costo: float = Field(..., ge=0, description="Costo de este ítem al momento de inscribirse")


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
    
    costo_total: float = Field(..., ge=0, description="Costo total del curso para este estudiante")
    costo_matricula: float = Field(..., ge=0, description="Costo de matrícula")
    amount_cuotas: Optional[int] = None # Campo deprecado, mantenido para compatibilidad
    cantidad_cuotas: int = Field(..., ge=1, description="Cantidad de cuotas para pagar")

    # ISSUE-P-CARGO-MULTIITEM (2026-07-08): snapshot de la LISTA de ítems de
    # cargo adicional/complementario al programa (ej. varios talleres
    # incluidos), tomada del Course al momento de inscribirse. Ningún ítem
    # recibe descuentos; la suma se agrega íntegra a total_a_pagar.
    cargo_adicional_items: List[CargoAdicionalItemSnapshot] = Field(
        default_factory=list,
        description="Snapshot de los ítems de cargo adicional del curso al momento de inscribirse. Lista vacía = sin cargo adicional."
    )
    
    modulos: List[ModuloEstado] = Field(
        default_factory=list,
        description="Fotocopia de los módulos del curso con el estado académico y financiero del estudiante"
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
    
    matricula_pagada: bool = Field(default=False, description="¿Ya pagó la matrícula el estudiante para este curso?")

    # F-US-006-3TIPOS-3A (2026-08-04): marca si esta inscripcion fue creada
    # como carga inicial del programa (caso retroactivo, programa en_ejecucion
    # o historico). Sirve para auditoria: distinguir una inscripcion que
    # el estudiante hizo por su cuenta vs una que el admin/encargado metio
    # manualmente al crear el programa.
    es_carga_inicial: bool = Field(
        default=False,
        description="True si la inscripcion fue creada como carga inicial del programa "
                    "(estudiante ya estaba/curso en el programa antes de que el sistema "
                    "lo registrara). Usado para auditoria."
    )

    # ISSUE-M-EXENCION: bypass de matrícula otorgado por MAE. NO condona la
    # deuda financiera (saldo_pendiente sigue reflejando la realidad); solo
    # desacopla el estado académico (poder cursar) del pago de matrícula.
    matricula_exenta: bool = Field(default=False, description="Si MAE autorizó cursar sin haber pagado la matrícula. La deuda financiera se mantiene intacta.")
    matricula_exenta_otorgada_por: Optional[str] = Field(default=None, description="Username del MAE/Admin/Superadmin que otorgó la exención.")
    matricula_exenta_fecha: Optional[datetime] = Field(default=None, description="Fecha (UTC) en que se otorgó la exención vigente.")

    # US-004 v4 (2026-08-04): Kevin. Excluir esta inscripción del cálculo del
    # "Por Cobrar" del dashboard sin cambiar su estado. Caso típico: estudiante
    # con inscripción PENDIENTE_PAGO en un curso NUEVO que Sandra aún no incluye
    # en su planilla (porque es un programa recién comenzando). No queremos
    # que sume al Por Cobrar del curso viejo, pero tampoco queremos marcarlos
    # como SUSPENDIDO (todavía pueden iniciar el nuevo curso). Se salta
    # en get_resumen_economico pero sigue visible en otras vistas.
    excluir_por_cobrar: bool = Field(default=False, description="Si True, esta inscripción NO suma al Por Cobrar del dashboard. El estado se mantiene.")

    # ISSUE-P-CONGELADO: motivo específico cuando estado=SUSPENDIDO. Reutiliza
    # el mismo estado que ISSUE-R-SOLICITUD-PASIVO ('pasivo') para no explotar
    # el enum EstadoInscripcion con valores redundantes; este campo diferencia
    # el origen real de la suspensión para reglas de reincorporación distintas.
    motivo_suspension: Optional[str] = Field(
        default=None,
        description="'pasivo' | 'congelado' | 'abandono'. None si estado no es SUSPENDIDO."
    )
    fecha_congelamiento: Optional[datetime] = Field(default=None, description="Fecha (UTC) en que se congeló voluntariamente la inscripción.")
    tasa_congelamiento_pagada: bool = Field(default=False, description="Si se registró el pago de la tasa de congelamiento (150 Bs).")
    fecha_abandono: Optional[datetime] = Field(default=None, description="Fecha (UTC) en que el sistema detectó y marcó el abandono automático.")
    multa_reincorporacion_pendiente: bool = Field(default=False, description="Si al reactivar esta inscripción corresponde cobrar la multa de reincorporación (300 Bs) por abandono.")
    mora_notificada: bool = Field(default=False, description="Si ya se notificó al encargado/CPD de mora preventiva (evita re-notificar en cada corrida del job).")

    # F-083 (2026-07-28): estado RETIRADO (abandono definitivo, no vuelve).
    # Distinto de SUSPENDIDO+abandono: el retirado es VOLUNTARIO (decisión del
    # estudiante o decisión administrativa), mientras que el abandono es
    # AUTOMÁTICO (el sistema lo detectó por inactividad). El retirado NO
    # genera multa de reincorporación.
    motivo_retiro: Optional[str] = Field(
        default=None,
        description="Motivo del retiro (ej: 'cambio de ciudad', 'problemas económicos', 'decisión administrativa'). None si estado != RETIRADO."
    )
    fecha_retiro: Optional[datetime] = Field(
        default=None,
        description="Fecha (UTC) en que se marcó la inscripción como RETIRADO. None si estado != RETIRADO."
    )
    retirado_por: Optional[str] = Field(
        default=None,
        description="Username del usuario (admin/cpd/superadmin) que registró el retiro. None si fue el estudiante via autoservicio."
    )

    # ISSUE-P-RECALCULO-NOTA: snapshot de la nota mínima exigida por el descuento personal
    nota_minima_beca: Optional[float] = Field(
        default=None, ge=0, le=100,
        description="Nota mínima exigida por el descuento personal al momento de inscribirse. None = sin condición académica."
    )

    # ISSUE-P-BECA-RESPALDO: documento de respaldo de la beca/descuento aplicado
    beca_respaldo_url: Optional[str] = Field(
        default=None,
        description="URL del documento de respaldo (resolución académica o de directorio) de la beca aplicada. None si aún no se ha subido."
    )

    # Formulario de inscripción lleno por el estudiante (PDF o imagen del
    # documento oficial firmado). Requisito por programa. None si aún no se subió.
    formulario_inscripcion_url: Optional[str] = Field(
        default=None,
        description="URL del formulario de inscripción oficial lleno/firmado por el estudiante. None si aún no se ha subido."
    )

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

    def get_cargo_adicional_total(self) -> float:
        """Suma de todos los ítems del snapshot de cargo adicional (ISSUE-P-CARGO-MULTIITEM)."""
        return round(sum(item.costo for item in self.cargo_adicional_items), 2)
    
    def actualizar_saldo(self, monto_pago_aprobado: float):
        self.total_pagado += monto_pago_aprobado
        self.saldo_pendiente = max(0, self.total_a_pagar - self.total_pagado)
        self.updated_at = utcnow_naive()
    
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
        
        for i, mod in enumerate(self.modulos):
            if mod.estado != "Pagado":
                monto_sugerido = mod.costo - mod.monto_pagado
                return {
                    "concepto": mod.nombre,
                    "numero_cuota": i + 1,
                    "monto_sugerido": round(monto_sugerido, 2)
                }
                
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
        # AUDITORÍA: optimistic locking. Enrollment es el recurso más
        # concurrido del sistema (pagos, notas, becas, pasivo/congelado
        # pueden mutarlo casi simultáneamente); sin esto cualquier par de
        # operaciones "leer-mutar-guardar" solapadas se pisan entre sí
        # (last-writer-wins) perdiendo la escritura más reciente en silencio.
        use_revision = True
        indexes = [
            # Índices de referencia cruzada acelerada para kyardex
            "estudiante_id",
            "curso_id",
            # Índice único compuesto para evitar doble inscripción del mismo alumno al mismo curso
            pymongo.IndexModel([("estudiante_id", pymongo.ASCENDING), ("curso_id", pymongo.ASCENDING)], unique=True),
            # Índices para ordenación temporal y filtrado por estado operacional
            [("estado", pymongo.ASCENDING), ("fecha_inscripcion", pymongo.DESCENDING)],
            [("fecha_inscripcion", pymongo.DESCENDING)]
        ]
        