"""
Helper de cálculo de matrícula
==============================

F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12, reunion UAGRM):
Logica para calcular el monto de la matricula de un estudiante en un
curso, con regla HIBRIDA:
- Si el Course define `matricula_primer_carrera` o `matricula_profesional`,
  se usa ese override (especifico del curso).
- Si el Course NO los define (None), se usan los defaults GLOBALES del
  sistema (`settings.MATRICULA_PRIMER_CARRERA_DEFAULT=200` y
  `settings.MATRICULA_PROFESIONAL_DEFAULT=500`).

Regla de decision (segun `Student.es_primer_carrera`):
- True (es primera carrera en la UAGRM): cobra matricula primer carrera.
- False (ya tiene titulo profesional): cobra matricula profesional.
- None o sin estudiante: usa matricula primer carrera (mas seguro, cobra
  menos si no se sabe el dato).

El descuento_porcentaje (de EC, si lo trae) sigue aplicando SOLO a modulos,
NUNCA a matricula (regla F-074-FIX-4 Kevin 2026-07-23, ratificada por
Kevin 2026-08-12: "un primer carrera PUEDE tener descuento en modulos").

Por que existe este helper:
- Antes (regla F-074-FIX-4 + ISSUE-P-PRECIO-UNICO 2026-07-08), la matricula
  era UN SOLO precio por curso (`Course.matricula_interno`), sin importar
  si el estudiante era primer carrera o profesional. Kevin decidio el
  2026-08-12 que eso era injusto: el primer carrera paga menos.
- Concentrar la logica aca evita que se duplique en payment_service,
  course_service, etc.
"""

from typing import Optional, TYPE_CHECKING

from core.config import settings

if TYPE_CHECKING:
    from models.course import Course
    from models.student import Student


def get_matricula_for_student(
    course: "Course",
    student: Optional["Student"] = None,
) -> float:
    """
    Devuelve el monto de la matricula que el estudiante debe pagar en este
    curso, segun la regla hibrida (override por curso + default global).

    Args:
        course: Course (programa) en el que se va a inscribir.
        student: Student (opcional). Si es None, asume primer carrera
            (mas seguro: cobra menos si no se sabe).

    Returns:
        float: monto en Bs de la matricula a cobrar. 0.0 si el curso es
        historico o el monto es None.

    Examples:
        >>> # Diplomado normal, defaults globales
        >>> get_matricula_for_student(curso, estudiante_primer_carrera)
        200.0
        >>> get_matricula_for_student(curso, estudiante_profesional)
        500.0
        >>> # Curso con override
        >>> curso.matricula_profesional = 600
        >>> get_matricula_for_student(curso, estudiante_profesional)
        600.0
    """
    # Default conservador: si no hay estudiante, asumimos primer carrera
    # (cobra menos, mas seguro). Tambien si el dato es None o False
    # por error, cobramos como primer carrera.
    es_primer_carrera = True
    if student is not None and getattr(student, "es_primer_carrera", None) is False:
        es_primer_carrera = False

    if es_primer_carrera:
        # Override del curso o default global
        return float(
            (course.matricula_primer_carrera
             if course.matricula_primer_carrera is not None
             else settings.MATRICULA_PRIMER_CARRERA_DEFAULT)
            or 0
        )
    else:
        return float(
            (course.matricula_profesional
             if course.matricula_profesional is not None
             else settings.MATRICULA_PROFESIONAL_DEFAULT)
            or 0
        )
