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
from pydantic import BaseModel, Field, validator, field_validator
from models.enums import TipoCurso, Modalidad, EstadoInscripcion
from models.base import PyObjectId
from schemas.requisito import RequisitoTemplateCreate

class ModuloCreate(BaseModel):
    nombre: str
    costo: float
    # ISSUE R: PERMITIR QUE EL BACKEND RECIBA Y VALIDE EL DOCENTE_ID
    # F-FIX-CREAR-PROGRAMA-422 (2026-08-09, Kevin): aceptar "" como None
    # para que el frontend pueda enviar el campo vacio sin causar 422.
    # Tambien aceptar string que no es un ObjectId valido: si falla la
    # conversion, lo dejamos como None (no se asigna docente).
    docente_id: Optional[PyObjectId] = Field(None, description="ID del docente asignado al módulo")

    @field_validator('docente_id', mode='before')
    @classmethod
    def _empty_docente_to_none(cls, v):
        if v is None or v == '' or v == 'null' or v == 'undefined':
            return None
        return v


class CargoAdicionalItemCreate(BaseModel):
    """ISSUE-P-CARGO-MULTIITEM: un ítem individual de cargo adicional (nombre + costo)."""
    nombre: str = Field(..., min_length=1, max_length=200)
    costo: float = Field(..., ge=0)


class CourseCreate(BaseModel):
    """
    Schema para crear un nuevo curso
    
    Uso: POST /courses/
    """
    
    codigo: str = Field(..., description="Código único del curso")
    nombre_programa: str = Field(..., min_length=1, max_length=300)
    tipo_curso: TipoCurso
    modalidad: Modalidad
    
    # Precio único del programa (ISSUE-P-PRECIO-UNICO, 2026-07-08): mismo
    # costo para todos los estudiantes, sin distinción de procedencia.
    # F-HISTORICO (2026-07-31): en programas historicos estos campos pueden
    # ser 0 (no se exige costo/matricula/cuotas porque son datos pasados
    # que no necesariamente se conocen exactos). El frontend valida que
    # para programas en ejecucion sean > 0.
    costo_total_interno: float = Field(default=0, ge=0, description="Costo total (colegiatura) del programa. Obligatorio > 0 si NO es historico.")
    matricula_interno: float = Field(default=0, ge=0, description="Matrícula institucional del programa. Obligatorio si NO es historico.")

    # ISSUE-P-CARGO-MULTIITEM: lista de ítems de cargo adicional/complementario
    # al programa (ej. varios talleres, cada uno con su propio costo).
    cargo_adicional_items: Optional[List[CargoAdicionalItemCreate]] = Field(default_factory=list)

    # Estructura de pago y módulos
    cantidad_cuotas: int = Field(default=0, ge=0, description="Cantidad de cuotas/modulos. Obligatorio >= 1 si NO es historico.")
    modulos: Optional[List[ModuloCreate]] = Field(
        default_factory=list,
        description="Lista generada dinámicamente de módulos y sus costos"
    )

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

    # F-HISTORICO (2026-07-31): marca el programa como historico. Si es True,
    # no se exige estructura operacional (docentes/modulos/notas/pagos).
    es_historico: bool = Field(
        default=False,
        description="F-HISTORICO: True si es programa historico (solo datos basicos + resolucion)."
    )

    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): override manual del
    # estado calculado por fechas. Sin esto, si el usuario crea un programa
    # con fecha_inicio futura, el calculo automatico dira 'programado' y no
    # 'en_ejecucion' como el usuario queria. Valores: 'programado' |
    # 'en_ejecucion' | 'cerrado'. None = calcular segun fechas.
    estado_override: Optional[str] = Field(
        default=None,
        description="F-CREAR-PROGRAMA-EN-EJECUCION: override del estado calculado. None=calcular por fechas. 'programado'|'en_ejecucion'|'cerrado'=forzar."
    )

    @field_validator('fecha_inicio', 'fecha_fin', mode='before')
    @classmethod
    def _empty_date_to_none(cls, v):
        # F-FIX-CREAR-PROGRAMA-422 (2026-08-09, Kevin): aceptar "" como None
        # para que el frontend pueda enviar fechas vacias (ej. en programas
        # historicos donde las fechas son opcionales).
        if v is None or v == '' or v == 'null' or v == 'undefined':
            return None
        return v

    # Resolucion de respaldo (opcional para todos los programas)
    resolucion_pdf_url: Optional[str] = Field(
        default=None,
        description="URL del PDF de la resolucion que respalda el programa (F-080). Opcional."
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
                "cargo_adicional_items": [
                    {"nombre": "Taller de Excel Avanzado", "costo": 100.0}
                ],
                "cantidad_cuotas": 5,
                "modulos": [{"nombre": "Módulo 1", "costo": 580, "docente_id": "664cbb0a22a3e6181fcd3155"}],
                "descuento_id": "507f1f77bcf86cd799439077",
                "observacion": "Incluye materiales didácticos",
                "fecha_inicio": "2024-03-15T00:00:00",
                "fecha_fin": "2024-09-30T00:00:00",
                "activo": True,
                "requisitos": [
                    {"descripcion": "Curriculum Vitae actualizado"}
                ]
            }
        }
    }


class CourseResponse(BaseModel):
    """
    Schema para mostrar información de un curso
    """
    
    id: PyObjectId = Field(..., alias="_id")
    codigo: str
    nombre_programa: str
    tipo_curso: TipoCurso
    modalidad: Modalidad
    
    costo_total_interno: float
    matricula_interno: float

    cargo_adicional_items: List[CargoAdicionalItemCreate] = Field(default_factory=list)
    
    cantidad_cuotas: int
    modulos: List[ModuloCreate] = Field(default_factory=list)

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

    es_historico: bool = False
    resolucion_pdf_url: Optional[str] = None

    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): expone el estado
    # calculado (programado/en_ejecucion/cerrado) y el override manual.
    # El frontend prefiere el calculado pero el override es util para
    # debugging.
    estado: Optional[str] = None
    estado_override: Optional[str] = None
    estado_calculado: Optional[str] = None

    # FIX-F-2026-08-12-EC-CREADO-POR (Kevin 2026-08-12): ID del User que
    # creo el programa. None para cursos pre-existentes. El frontend lo usa
    # en listados para mostrar "Creado por: <username>" y como dato de
    # auditoria.
    creado_por_id: Optional[PyObjectId] = None

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
                "nombre_programa": "Diplomado en Sistemas de Gestión de Calidad",
                "tipo_curso": "diplomado",
                "modalidad": "hibrido",
                "costo_total_interno": 3500.0,
                "matricula_interno": 600.0,
                "cargo_adicional_items": [
                    {"nombre": "Taller de Excel Avanzado", "costo": 100.0}
                ],
                "cantidad_cuotas": 5,
                "modulos": [{"nombre": "Módulo 1", "costo": 580}],
                "descuento_id": "507f1f77bcf86cd799439077",
                "descuento_curso": 10.0,
                "observacion": "Incluye materiales didácticos",
                "inscritos": ["507f1f77bcf86cd799439011"],
                "fecha_inicio": "2024-03-15T00:00:00",
                "fecha_fin": "2024-09-30T00:00:00",
                "activo": True,
                "requisitos": [{"descripcion": "Curriculum Vitae actualizado"}],
                "created_at": "2024-02-01T10:30:00",
                "updated_at": "2024-02-01T10:30:00"
            }
        }
    }


class CourseUpdate(BaseModel):
    """
    Schema para actualizar un curso existente
    """
    
    codigo: Optional[str] = None
    nombre_programa: Optional[str] = Field(None, min_length=1, max_length=300)
    tipo_curso: Optional[TipoCurso] = None
    modalidad: Optional[Modalidad] = None
    
    costo_total_interno: Optional[float] = Field(None, ge=0)
    matricula_interno: Optional[float] = Field(None, ge=0)

    cargo_adicional_items: Optional[List[CargoAdicionalItemCreate]] = None

    # F-FIX-EDITAR-HISTORICO-422 (2026-08-08, Kevin): permitir 0 para que el
    # frontend pueda guardar un programa historico con costo 0 y 0 modulos
    # (son solo archivo, no se venden). Antes era ge=1, daba 422 al guardar.
    cantidad_cuotas: Optional[int] = Field(None, ge=0)
    modulos: Optional[List[ModuloCreate]] = None

    descuento_curso: Optional[float] = Field(None, ge=0, le=100)
    descuento_id: Optional[PyObjectId] = None
    
    observacion: Optional[str] = None
    inscritos: Optional[List[PyObjectId]] = None
    
    fecha_inicio: Optional[datetime] = None
    fecha_fin: Optional[datetime] = None
    activo: Optional[bool] = None

    # F-FIX-CREAR-PROGRAMA-422 (2026-08-09, Kevin): aceptar "" como None
    # para que el frontend pueda editar programas historicos sin fecha
    # sin causar 422.
    @field_validator('fecha_inicio', 'fecha_fin', mode='before')
    @classmethod
    def _empty_date_to_none(cls, v):
        if v is None or v == '' or v == 'null' or v == 'undefined':
            return None
        return v

    requisitos: Optional[List[RequisitoTemplateCreate]] = None

    es_historico: Optional[bool] = None
    resolucion_pdf_url: Optional[str] = None

    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): ver CourseCreate.
    estado_override: Optional[str] = Field(
        default=None,
        description="F-CREAR-PROGRAMA-EN-EJECUCION: override del estado calculado."
    )
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "nombre_programa": "Diplomado en Sistemas de Gestión de Calidad",
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
    # F-HISTORICO-EXCEL-ESTADO (2026-08-04): exponer matricula_pagada
    # para que el frontend pueda mostrar el badge correcto en la UI.
    matricula_pagada: bool = False

class FinancialInfo(BaseModel):
    total_a_pagar: float
    total_pagado: float
    saldo_pendiente: float
    avance_pago: float = Field(..., description="Porcentaje de pago completado (0-100)")
    # F-2026-08-22-PRE-REG-BADGE-DESCUENTO (Kevin 2026-08-22): exponer el
    # descuento aplicado al enrollment para que el frontend pueda mostrar
    # el badge "X% descuento" en el modal de Estudiantes Inscritos.
    # - `descuento_personalizado` viene de Enrollment (snapshot, en % 0-100)
    # - `descuento_origen` indica si fue por vicerrectorado, EC, o ninguno
    descuento_personalizado: Optional[float] = Field(
        None, ge=0, le=100,
        description="% de descuento aplicado (0-100). Null si no tiene descuento."
    )
    descuento_origen: Optional[str] = Field(
        None,
        description="Origen del descuento: 'vicerrectorado' | 'ec' | 'mixto' | None"
    )

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
    