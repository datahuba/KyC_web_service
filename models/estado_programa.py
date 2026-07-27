"""
F-080 · Estado de programas académicos
=====================================

Módulo aislado (sin dependencias de beanie/fastapi/motor) que define:

  - `EstadoPrograma`: enum con los 3 estados posibles
    (PROGRAMADO, EN_EJECUCION, CERRADO).
  - `calcular_estado_actual`: función pura que, dadas las fechas
    de inicio/fin y un override opcional, devuelve el estado
    correspondiente.

Por estar aislado, este módulo es trivialmente testeable sin venv ni
mocks. Los modelos (Course, etc.) lo importan de aquí para reutilizar
la misma lógica.
"""

from enum import Enum
from datetime import datetime
from typing import Optional


class EstadoPrograma(str, Enum):
    """
    Estados del ciclo de vida de un programa académico (F-080).

    El estado es **calculado automáticamente** a partir de las fechas:
      - PROGRAMADO:      fecha_inicio > hoy
      - EN_EJECUCION:    fecha_inicio <= hoy <= fecha_fin
      - CERRADO:         fecha_fin < hoy

    Para casos especiales (suspensiones, extensiones) se puede usar
    `Course.estado_override` para forzar manualmente. Si está definido
    tiene prioridad sobre el cálculo automático.

    Uso del estado:
      - CERRADO: NO se aceptan nuevas solicitudes de inscripción.
      - EN_EJECUCION: sí acepta inscripciones (mientras queden plazas).
      - PROGRAMADO: sí acepta inscripciones anticipadas.

    El campo `activo: bool` sigue existiendo como un flag independiente
    (e.g. desactivar manualmente un programa de la plataforma sin
    considerarlo "cerrado" por fechas).
    """
    PROGRAMADO = "programado"
    EN_EJECUCION = "en_ejecucion"
    CERRADO = "cerrado"


def calcular_estado_actual(
    fecha_inicio: Optional[datetime],
    fecha_fin: Optional[datetime],
    estado_override: Optional[str] = None,
    ahora: Optional[datetime] = None,
) -> str:
    """
    F-080: calcula el estado del programa según fechas (función pura,
    testeable, sin dependencias de Mongo).

    Reglas (en orden de evaluación):
      1. Si `estado_override` está definido y es válido → se respeta.
      2. Si NO hay fecha_inicio NI fecha_fin → EN_EJECUCION (default
         conservador: el programa se considera en curso hasta que tenga
         fechas explícitas).
      3. Si fecha_fin < ahora → CERRADO.
      4. Si fecha_inicio > ahora → PROGRAMADO.
      5. Si fecha_inicio <= ahora <= fecha_fin → EN_EJECUCION.

    Args:
        fecha_inicio: fecha de inicio del programa (o None)
        fecha_fin: fecha de fin del programa (o None)
        estado_override: forzar manualmente (opcional). Acepta los
            valores del enum EstadoPrograma o sus strings.
        ahora: timestamp "actual" para tests deterministas. Si no se
            pasa, usa datetime.utcnow() (naive UTC).

    Returns:
        Uno de los 3 valores de EstadoPrograma como string:
        "programado", "en_ejecucion" o "cerrado".
    """
    # 1. Override manual tiene prioridad
    if estado_override:
        try:
            return EstadoPrograma(estado_override).value
        except ValueError:
            # override inválido → cae a cálculo automático
            pass

    # 2. Sin fechas: default conservador
    if fecha_inicio is None and fecha_fin is None:
        return EstadoPrograma.EN_EJECUCION.value

    if ahora is None:
        ahora = datetime.utcnow()

    # Solo fecha_fin definida: si ya pasó, cerrado; si no, en ejecución
    if fecha_inicio is None and fecha_fin is not None:
        return EstadoPrograma.CERRADO.value if fecha_fin < ahora else EstadoPrograma.EN_EJECUCION.value

    # Solo fecha_inicio definida: si aún no llega, programado; si no, en ejecución
    if fecha_inicio is not None and fecha_fin is None:
        return EstadoPrograma.PROGRAMADO.value if fecha_inicio > ahora else EstadoPrograma.EN_EJECUCION.value

    # Ambas fechas: la lógica completa
    if fecha_fin < ahora:
        return EstadoPrograma.CERRADO.value
    if fecha_inicio > ahora:
        return EstadoPrograma.PROGRAMADO.value
    return EstadoPrograma.EN_EJECUCION.value
