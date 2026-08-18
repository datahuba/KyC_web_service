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
from .enums import TipoCurso, Modalidad, AmbitoFormacion
from .estado_programa import EstadoPrograma, calcular_estado_actual
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

    # F-CERTIFICADOS (2026-07-29): fechas de inicio y fin del módulo para
    # Certificados de Notas y calendario por módulo. Opcionales para mantener
    # retrocompatibilidad con cursos existentes (backfill via script one-shot
    # scripts/backfill_modulo_fechas.py que copia Course.fecha_inicio/fin).
    fecha_inicio: Optional[datetime] = Field(
        default=None,
        description="Fecha de inicio del módulo (UTC). Usado para Certificados de Notas y calendario por módulo."
    )
    fecha_fin: Optional[datetime] = Field(
        default=None,
        description="Fecha de fin del módulo (UTC). Usado para Certificados de Notas y calendario por módulo."
    )

    # F-FIX-ESTADO-OPERACIONAL (2026-08-16): el frontend ya ofrecia este
    # selector desde hacia tiempo (CourseForm, solo visible al cargar un
    # programa con tipo_programa='en_ejecucion'), pero el campo NO existia
    # aca. Pydantic v2 descarta los campos extra, asi que lo que el
    # encargado elegia — que modulos ya se dictaron y cuales faltan al
    # cargar un programa a mitad de camino — se perdia en SILENCIO al
    # guardar. Opcional para no romper los cursos ya existentes.
    estado_operacional: Optional[str] = Field(
        default=None,
        description=(
            "Estado del módulo en el cronograma al cargar un programa ya en "
            "ejecución: 'Pendiente' | 'En Ejecucion' | 'Ejecutado'. None en "
            "programas nuevos, donde todos los módulos arrancan sin dictar."
        )
    )


# ========================================================================
# SUB-MODELO: CARGO ADICIONAL MULTI-ÍTEM (ISSUE-P-CARGO-MULTIITEM, 2026-07-08)
# ========================================================================
class CargoAdicionalItem(BaseModel):
    """
    Un ítem individual del cargo adicional/complementario al programa
    (ej. "Taller de Excel Avanzado" con costo 100 Bs). Reemplaza el diseño
    anterior de un solo monto+concepto (ISSUE-P-PRECIO-UNICO): la reunión
    de postgrado contaduría del 2026-07-08 confirmó que puede haber VARIOS
    gastos complementarios simultáneos (ej. dos talleres distintos), cada
    uno con su propio nombre y costo, igual que la lista de módulos.
    """
    nombre: str = Field(..., min_length=1, max_length=200, description="Concepto del ítem (ej. 'Taller de Excel Avanzado')")
    costo: float = Field(..., ge=0, description="Costo individual de este ítem")


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
    # se retiraron de este propósito; ver cargo_adicional_items abajo para el
    # nuevo significado (gastos complementarios opcionales al programa).

    costo_total_interno: float = Field(
        default=0,
        ge=0,
        description="Costo total (colegiatura) del programa. Precio único, aplica a todos los estudiantes por igual. "
                    "En programas historicos (es_historico=True) puede ser 0 (no se exige)."
    )

    matricula_interno: float = Field(
        default=0,
        ge=0,
        description="Costo de matrícula institucional. Precio único, aplica a todos los estudiantes por igual. "
                    "En programas historicos (es_historico=True) puede ser 0 (no se exige)."
    )

    # F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12, reunion UAGRM):
    # Matriculas DIFERENCIADAS por tipo de estudiante (educacion continua).
    # Si ambos son None, se usan los defaults globales del sistema
    # (MATRICULA_PRIMER_CARRERA_DEFAULT=200, MATRICULA_PROFESIONAL_DEFAULT=500).
    # Si el Course define estos campos, son el override para ESTE curso.
    # Ver `get_matricula_for_student()` en services/payment_service.py para
    # la regla hibrida (default global + override por curso).
    matricula_primer_carrera: Optional[float] = Field(
        default=None,
        ge=0,
        description="F-2026-08-12-DESCUENTO-BECA: override de matricula para estudiantes de PRIMERA CARRERA en la UAGRM. "
                    "Si None, usa settings.MATRICULA_PRIMER_CARRERA_DEFAULT (200 Bs por default)."
    )
    matricula_profesional: Optional[float] = Field(
        default=None,
        ge=0,
        description="F-2026-08-12-DESCUENTO-BECA: override de matricula para estudiantes que YA TIENEN TITULO PROFESIONAL. "
                    "Si None, usa settings.MATRICULA_PROFESIONAL_DEFAULT (500 Bs por default)."
    )

    # ========================================================================
    # P-AMBITO-FORMACION (2026-08-18, Kevin en la capacitacion)
    # ========================================================================
    # Que ES el programa. Es la fuente de verdad para las reglas de matricula
    # y lo que permite separar ingresos de educacion continua vs postgrado en
    # los reportes.
    #
    # Vive en el Course y no solo en el usuario a proposito: si dependiera de
    # quien lo creo, al editarlo un CPD o superadmin (que no son ni una cosa
    # ni la otra) no habria forma de saber que reglas aplicar.
    #
    # Optional por compatibilidad: los programas creados antes de este campo
    # lo tienen en None. `resolver_ambito()` los interpreta por su tipo_curso.
    ambito: Optional[AmbitoFormacion] = Field(
        default=None,
        description=(
            "P-AMBITO-FORMACION: educacion_continua (cobra matricula "
            "diferenciada) o profesional (sin matricula institucional). "
            "None en programas anteriores al campo; se deduce del tipo_curso."
        ),
    )

    # ========================================================================
    # CARGO ADICIONAL (opcional): gastos complementarios al programa
    # ========================================================================
    # ISSUE-P-CARGO-MULTIITEM (2026-07-08, reunión de postgrado contaduría):
    # rediseñado de un solo monto+concepto a una LISTA de ítems (mismo patrón
    # que `modulos`), ya que puede haber varios gastos complementarios
    # simultáneos (ej. "Taller de Excel Avanzado" 100 Bs + "Certificación
    # Internacional" 50 Bs). Si la lista tiene elementos, la suma se agrega
    # al total a pagar de TODOS los estudiantes inscritos a este curso (no
    # es opcional por estudiante individual; es una condición del programa
    # en su conjunto). Si el usuario quiere que sea opcional por estudiante,
    # deberá gestionarse manualmente por ahora (fuera de alcance).
    cargo_adicional_items: List[CargoAdicionalItem] = Field(
        default_factory=list,
        description="Lista de ítems de cargo adicional/complementario al programa (ej. talleres incluidos). Lista vacía = sin cargo adicional."
    )
    
    # ========================================================================
    # ESTRUCTURA DE PAGO Y MÓDULOS
    # ========================================================================
    
    cantidad_cuotas: int = Field(
        default=0,
        ge=0,
        description="Número de cuotas en las que se puede dividir el pago. "
                    "En programas historicos (es_historico=True) puede ser 0 (no se exige)."
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

    # F-080: estado calculado automáticamente por fechas (programado /
    # en_ejecucion / cerrado). Se persiste como string para evitar migraciones
    # futuras si agregamos más valores. El frontend debe preferir el campo
    # calculado `estado_calculado` del response, no este.
    estado: str = Field(
        default=EstadoPrograma.EN_EJECUCION.value,
        description="Estado persistido del programa (F-080). Por default 'en_ejecucion' para retrocompatibilidad con cursos existentes."
    )

    estado_override: Optional[str] = Field(
        default=None,
        description="Override manual del estado (F-080). Si está definido y es válido, tiene prioridad sobre el cálculo por fechas. Útil para suspensiones o extensiones manuales."
    )

    # F-CREAR-PROGRAMA-EN-EJECUCION (2026-08-05, Kevin): estado calculado
    # en runtime segun fechas/override. Se persiste (no es un @property)
    # porque Beanie/Pydantic v2 no permite setear atributos dinamicos
    # que no esten en el schema. El endpoint lo popula antes de retornar.
    estado_calculado: Optional[str] = Field(
        default=None,
        description="F-CREAR-PROGRAMA-EN-EJECUCION: estado calculado por fechas+override. Populado por el endpoint antes de retornar."
    )

    resolucion_pdf_url: Optional[str] = Field(
        default=None,
        description="URL del PDF de la resolución que respalda el programa (F-080)."
    )

    # F-HISTORICO (2026-07-31): marca un programa como "historico" (curso pasado
    # o registro retroactivo). Cuando es True, el sistema NO exige datos
    # operacionales (docentes, modulos con notas, pagos, requisitos) — solo
    # identifica el programa (codigo, nombre, tipo, modalidad, fechas) y
    # opcionalmente una resolucion de respaldo. Esto permite cargar rapidamente
    # el catalogo de programas antiguos sin tener que reconstruir toda la
    # estructura academica y financiera de cada uno.
    es_historico: bool = Field(
        default=False,
        description="F-HISTORICO: True si es un programa historico/cerrado del que solo "
                    "queremos guardar datos basicos + resolucion de respaldo. "
                    "False (default) si es un programa en ejecucion o por ejecutarse, "
                    "donde se exige la estructura completa (docentes, modulos, pagos, etc.)."
    )

    # FIX-F-2026-08-12-EC-CREADO-POR (Kevin 2026-08-12): trazabilidad de quien
    # creo el programa. Antes no se guardaba, lo que impedia hacer migraciones
    # retroactivas ("asignar a este EC los programas que el creo") y rompia el
    # flujo de auto-asignacion cuando el EC se equivocaba de boton. Ahora cada
    # curso tiene un `creado_por_id` apuntando al User que lo creo (sea
    # EC/COORDINADOR/CPD/ADMIN/SUPERADMIN). Para cursos pre-existentes (sin
    # este campo), el endpoint de migracion `POST /admin/migrate/ec-creador`
    # hace el backfill una sola vez.
    creado_por_id: Optional[PyObjectId] = Field(
        default=None,
        description="FIX-F-2026-08-12-EC-CREADO-POR: ID del User que creo el programa. "
                    "None para cursos pre-existentes (usar endpoint de migracion)."
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

    def get_cargo_adicional_total(self) -> float:
        """
        Suma de todos los ítems de cargo adicional/complementario
        (ISSUE-P-CARGO-MULTIITEM). 0.0 si la lista está vacía.
        """
        return round(sum(item.costo for item in self.cargo_adicional_items), 2)

    def get_estado_actual(self, ahora: Optional[datetime] = None) -> str:
        """
        F-080: devuelve el estado actual del programa, aplicando la lógica
        de cálculo automático con override (helper `calcular_estado_actual`
        de este mismo módulo). El parámetro `ahora` se acepta para tests
        deterministas.
        """
        return calcular_estado_actual(
            self.fecha_inicio,
            self.fecha_fin,
            self.estado_override,
            ahora=ahora,
        )

    def acepta_inscripciones(self) -> bool:
        """
        F-080 + F-US-006-3TIPOS (2026-08-04): True SOLO si el estado actual
        del programa es PROGRAMADO. Un programa en_ejecucion, cerrado o
        histórico NO acepta nuevas solicitudes de inscripción de estudiantes
        (los ya inscritos siguen, pero nadie nuevo puede entrar por su cuenta).

        Razón: Kevin decidió que un programa en ejecución ya cerró inscripciones
        — los rezagados los mete el admin/encargado manualmente a un módulo
        futuro. Un histórico/cerrado es solo archivo, no se inscribe nadie nuevo
        (salvo superadmin en caso retroactivo excepcional).
        """
        return self.get_estado_actual() == EstadoPrograma.PROGRAMADO.value
    
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
        json_schema_extra = {
            "example": {
                "codigo": "DIPL-2024-001",
                "nombre_programa": "Diplomado en Ciencia de Datos",
                "tipo_curso": "diplomado",
                "modalidad": "híbrido",
                "costo_total_interno": 3000.0,
                "matricula_interno": 500.0,
                "cargo_adicional_items": [
                    {"nombre": "Taller de Excel Avanzado", "costo": 100.0}
                ],
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
