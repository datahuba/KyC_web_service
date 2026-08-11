"""
F-2026-08-11-ASISTENCIA: sistema de registro de asistencia por sesion/clase
para educacion continua UAGRM (regla del 80% asistencia, reunion
2026-08-11). Hasta ahora el docente llenaba el % manualmente al cerrar
el modulo. Ahora se modelan sesiones y registros individuales.

Colecciones:
- `sesiones`: una clase/sesion de un modulo de un enrollment
  (ej "Modulo 1 / Clase 3 / 2026-09-15 19:00 / Tema: Impuestos directos")
- `asistencias`: el registro de cada estudiante en una sesion
  (presente, ausente, tarde, justificado)

El % de asistencia por modulo se calcula como:
  total_presentes / total_sesiones_registradas  * 100
donde `total_sesiones_registradas` cuenta todas las sesiones que tienen
al menos un registro para el estudiante (asi sesiones "fantasma" sin
asistencia no afectan).

Cuando un estudiante alcanza < 80% asistencia, el sistema fuerza
`estado_academico='Reprobado'` al cerrar el modulo (regla F-MODULOS-EC).
"""
from datetime import datetime
from typing import Optional
from pydantic import Field
from .base import MongoBaseModel, PyObjectId


class Sesion(MongoBaseModel):
    """
    F-2026-08-11-ASISTENCIA: una sesion/clase de un modulo de un enrollment.
    Se crea una Sesion por cada clase que da el docente. Por cada Sesion
    hay multiples AsistenciaRegistro (uno por estudiante).
    """
    # FK al enrollment
    enrollment_id: PyObjectId = Field(..., description="ID del enrollment (vincula con el estudiante y el curso)")
    # Indice del modulo en el array enrollment.modulos (0, 1, 2...)
    modulo_index: int = Field(..., ge=0, description="Indice del modulo en el array enrollment.modulos")
    # Fecha y hora de la sesion
    fecha: datetime = Field(..., description="Fecha y hora de la sesion (UTC)")
    # Tema de la clase
    tema: Optional[str] = Field(None, max_length=200, description="Tema/contenido de la sesion (ej 'Clase 1: Introduccion al Derecho Tributario')")
    # Quien registro la sesion
    creado_por: str = Field(..., description="Username del usuario que creo la sesion (docente/encargado/admin)")

    class Settings:
        name = "sesiones"
        indexes = [
            # Busqueda por enrollment + modulo (caso comun: listar sesiones de un modulo)
            [("enrollment_id", 1), ("modulo_index", 1), ("fecha", 1)],
        ]


class AsistenciaRegistro(MongoBaseModel):
    """
    F-2026-08-11-ASISTENCIA: registro individual de un estudiante en una
    sesion. El docente lo marca al pasar lista o al final de la clase.

    Estados:
    - presente: asistio a la sesion
    - ausente: no asistio
    - tarde: llego tarde (cuenta como 0.5 presente para el % asistencia)
    - justificado: no asistio pero justifico (NO cuenta como presente
      NI como ausente para el % asistencia; es neutro)
    """
    sesion_id: PyObjectId = Field(..., description="ID de la sesion")
    estudiante_id: PyObjectId = Field(..., description="ID del estudiante")
    estado: str = Field(..., description="'presente' | 'ausente' | 'tarde' | 'justificado'")
    observacion: Optional[str] = Field(None, max_length=500, description="Observacion opcional del docente/encargado")
    registrado_por: str = Field(..., description="Username del usuario que registro la asistencia")

    class Settings:
        name = "asistencias"
        indexes = [
            # Un estudiante solo puede tener un registro por sesion
            [("sesion_id", 1), ("estudiante_id", 1)],  # uniqueness enforced at API level
            # Busqueda por estudiante + sesion (calcular % asistencia)
            [("estudiante_id", 1), ("sesion_id", 1)],
        ]
