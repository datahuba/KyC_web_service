"""
Schemas de Inscripción (Enrollment)
===================================
"""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from models.enums import EstadoInscripcion
from models.base import PyObjectId
from schemas.requisito import RequisitoResponse

# NUEVO SCHEMA PARA MÓDULOS DE INSCRIPCIÓN
class ModuloEstadoSchema(BaseModel):
    nombre: str
    costo: float
    estado: str
    monto_pagado: float
    # Campos académicos (ISSUE P)
    nota: Optional[float] = None
    estado_academico: Optional[str] = "Cursando"
    # ISSUE-P-RECALCULO-NOTA
    costo_sin_beca_personal: Optional[float] = None
    # ISSUE-Q-NOTA-BORRADOR
    nota_borrador: Optional[float] = None
    estado_validacion_nota: Optional[str] = "sin_borrador"
    # F-2026-08-11-MODULOS-EC: porcentaje de asistencia (0-100)
    asistencia_porcentaje: Optional[float] = None

class ModuloNotaUpdate(BaseModel):
    """Schema para actualizar la calificación de un submódulo (docente -> borrador; CPD/Admin -> oficial directa)"""
    nota: float = Field(..., ge=0, le=100, description="Calificación del módulo (0-100)")


class CargoAdicionalItemSchema(BaseModel):
    """ISSUE-P-CARGO-MULTIITEM: snapshot de un ítem de cargo adicional en la respuesta de la inscripción."""
    nombre: str
    costo: float

class EnrollmentCreate(BaseModel):
    """Schema para crear una nueva inscripción"""
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante a inscribir")
    curso_id: PyObjectId = Field(..., description="ID del curso")
    descuento_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "estudiante_id": "507f1f77bcf86cd799439011",
                "curso_id": "507f1f77bcf86cd799439012"
            }
        }
    }

class EnrollmentResponse(BaseModel):
    """Schema para mostrar información de una inscripción"""
    id: PyObjectId = Field(..., alias="_id")
    estudiante_id: PyObjectId
    curso_id: PyObjectId
    
    # Snapshot de precios y módulos
    costo_total: float
    costo_matricula: float
    cantidad_cuotas: int
    modulos: List[ModuloEstadoSchema] = Field(default_factory=list)

    # ISSUE-P-CARGO-MULTIITEM: snapshot de la lista de ítems de cargo adicional
    cargo_adicional_items: List[CargoAdicionalItemSchema] = Field(default_factory=list)
    
    # Descuentos
    # F-FIX-EXCLUIR-POR-COBRAR (2026-08-16): exponerlo para que la UI pueda
    # mostrar si una inscripción está excluida del Por Cobrar.
    excluir_por_cobrar: bool = False
    descuento_curso_id: Optional[PyObjectId] = None
    descuento_curso_aplicado: float
    descuento_estudiante_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float]
    
    # Totales
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    
    # Estado
    fecha_inscripcion: datetime
    estado: EstadoInscripcion
    nota_final: Optional[float] = None
    
    # Información Calculada
    siguiente_pago: Optional[dict] = None
    cuotas_pagadas_info: Optional[dict] = None
    
    created_at: datetime
    updated_at: datetime
    
    matricula_pagada: Optional[bool] = False
    matricula_exenta: Optional[bool] = False  # ISSUE-M-EXENCION
    matricula_exenta_otorgada_por: Optional[str] = None  # ISSUE-M-EXENCION
    matricula_exenta_fecha: Optional[datetime] = None  # ISSUE-M-EXENCION
    nota_minima_beca: Optional[float] = None  # ISSUE-P-RECALCULO-NOTA
    beca_respaldo_url: Optional[str] = None  # ISSUE-P-BECA-RESPALDO
    formulario_inscripcion_url: Optional[str] = None  # Formulario de inscripción lleno
    # ISSUE-P-CONGELADO
    motivo_suspension: Optional[str] = None
    fecha_congelamiento: Optional[datetime] = None
    tasa_congelamiento_pagada: Optional[bool] = False
    fecha_abandono: Optional[datetime] = None
    multa_reincorporacion_pendiente: Optional[bool] = False

    # ISSUE-Q-DOCUMENTOS-KYC (2026-07-09, reportado por el usuario): el
    # sistema de subida/aprobación de documentos (Requisito) ya existía en
    # el backend desde antes (endpoints PUT /requisitos/{index},
    # /aprobar, /rechazar), pero EnrollmentResponse nunca expuso este campo
    # -- el frontend no tenía forma de mostrarlo ni de construir una UI
    # sobre él, quedando la función completamente sin usar.
    requisitos: List[RequisitoResponse] = Field(default_factory=list)

    # F-LOGICA-DESCUENTOS-MAX (2026-08-05, Kevin): campos informativos que
    # enrich_enrollment_dates() agrega al response de TODOS los endpoints
    # que devuelven enrollment. El frontend los usa para mostrar el mensaje
    # "se aplicó el descuento de mayor porcentaje" cuando el personal es
    # menor al del curso.
    descuento_efectivo: Optional[float] = None  # % realmente aplicado (max)
    descuento_efectivo_origen: Optional[str] = None  # 'curso' | 'personal' | 'ninguno'
    advertencia_descuento: Optional[str] = None  # mensaje si personal < curso

    # F-FIX-DESCONOCIDO-ENROLLMENTS (2026-08-09, Kevin): campos joineados
    # del estudiante y del curso para que el frontend NO muestre
    # "Desconocido" en /enrollments/ (bug del cliente que cargaba solo
    # los primeros 100 estudiantes en un map local). El backend los joinea
    # con una query batch de students (In) y otra de courses.
    estudiante_nombre: Optional[str] = None
    estudiante_registro: Optional[str] = None
    estudiante_ci: Optional[str] = None
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }

class EnrollmentUpdate(BaseModel):
    """Schema para actualizar una inscripción existente"""
    descuento_id: Optional[PyObjectId] = None
    descuento_personalizado: Optional[float] = Field(None, ge=0, le=100)
    estado: Optional[EstadoInscripcion] = None
    # F-FIX-EXCLUIR-POR-COBRAR (2026-08-16): US-004 v4 agrego este flag al
    # modelo y los dos calculos de dinero ya lo respetan, pero no habia forma
    # de ACTIVARLO: ningun schema lo declaraba. Era un interruptor muerto.
    # None = no tocar; True/False = setear explicitamente.
    excluir_por_cobrar: Optional[bool] = Field(
        None,
        description="Si True, esta inscripción deja de sumar al Por Cobrar del dashboard. El estado de la inscripción NO cambia."
    )
    # AUDITORÍA (BAJO #18): nota_final se eliminó de este schema. Es un campo
    # 100% CALCULADO (promedio de las notas de módulos, ver
    # actualizar_nota_modulo en enrollment_service.py) -- el endpoint nunca
    # lo procesaba aunque el schema lo aceptara, dando la falsa impresión de
    # que se podía editar directamente. Para cambiar la nota de un módulo,
    # usar PATCH /enrollments/{id}/modulos/{index}/nota.

class EnrollmentWithDetails(EnrollmentResponse):
    """Schema para mostrar inscripción con detalles de Student y Course"""
    estudiante_nombre: Optional[str] = None
    estudiante_email: Optional[str] = None
    curso_nombre: Optional[str] = None
    curso_codigo: Optional[str] = None
    monto_cuota: Optional[float] = None
    porcentaje_pagado: Optional[float] = None

    model_config = {
        "populate_by_name": True,
        "arbitrary_types_allowed": True,
        "from_attributes": True
    }


class BulkEnrollmentRequest(BaseModel):
    """
    F-INSCRIPCION-LOTE (2026-07-31): esquema para inscribir múltiples
    estudiantes al mismo programa en una sola operación.

    Pensado para el caso real: llega una lista de admitidos (excel del
    CPD) y hay que inscribirlos a todos al mismo programa. Antes había
    que hacerlo de uno en uno desde la UI de Nueva Inscripción.
    """
    curso_id: PyObjectId = Field(..., description="ID del curso/programa")
    estudiantes_ids: List[PyObjectId] = Field(
        ...,
        min_length=1,
        max_length=200,
        description="IDs de los estudiantes a inscribir (1-200)",
    )
    # Opcionales: aplicar el mismo descuento/beca a todos los del lote.
    descuento_id: Optional[PyObjectId] = Field(None, description="ID de un Discount a aplicar a todos")
    descuento_personalizado: Optional[float] = Field(
        None, ge=0, le=100, description="% libre de descuento (0-100) para todos"
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "curso_id": "507f1f77bcf86cd799439012",
                "estudiantes_ids": [
                    "507f1f77bcf86cd799439011",
                    "507f1f77bcf86cd799439013",
                ],
                "descuento_personalizado": 10,
            }
        }
    }


class BulkEnrollmentErrorItem(BaseModel):
    """Detalle de un fallo dentro de la inscripción en lote."""
    estudiante_id: str
    error: str


class BulkEnrollmentResponse(BaseModel):
    """
    F-INSCRIPCION-LOTE: respuesta de la inscripción en lote con
    desglose de éxitos, duplicados y errores para que la UI pueda
    mostrar un resumen accionable.
    """
    total_solicitados: int
    exitosos: int
    ya_inscritos: int
    fallidos: int
    enrollments_creados: List[EnrollmentResponse] = Field(default_factory=list)
    errores: List[BulkEnrollmentErrorItem] = Field(default_factory=list)


# ========================================================================
# Bulk Grades Upload (Docente -> CPD Borrador)
# ========================================================================
class BulkNotaDocenteItem(BaseModel):
    enrollment_id: PyObjectId
    modulo_index: int = Field(..., ge=0)
    nota: float = Field(..., ge=0, le=100)


class BulkNotasDocenteRequest(BaseModel):
    items: List[BulkNotaDocenteItem] = Field(..., min_length=1, max_length=500)
    curso_id: Optional[PyObjectId] = None
    modulo_nombre: Optional[str] = None


class BulkNotasDocenteResultado(BaseModel):
    enrollment_id: str
    modulo_index: int
    exito: bool
    error: Optional[str] = None
    nota_guardada: Optional[float] = None


class BulkNotasDocenteResponse(BaseModel):
    total_solicitados: int
    exitosos: int
    fallidos: int
    resultados: List[BulkNotasDocenteResultado] = Field(default_factory=list)

    