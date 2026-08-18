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
from models.enums import (
    AmbitoFormacion,
    TIPOS_CURSO_SIEMPRE_PROFESIONAL,
    TIPOS_CURSO_DEFAULT_CONTINUA,
)

if TYPE_CHECKING:
    from models.course import Course
    from models.student import Student


def resolver_ambito(
    tipo_curso: Optional[str],
    ambito_explicito: Optional[str] = None,
    ambito_del_creador: Optional[str] = None,
) -> AmbitoFormacion:
    """
    P-AMBITO-FORMACION (2026-08-18): decide el ambito de un programa.

    Orden de precedencia, del mas fuerte al mas debil:

    1. El TIPO DE CURSO manda cuando no admite discusion. Kevin, 2026-08-18:
       "maestrias, doctorados, todos son profesionales". Una maestria no
       puede ser educacion continua ni aunque el formulario lo mande.
    2. Lo que se pidio explicitamente.
    3. El ambito del encargado que lo crea. Como cada encargado es de un
       solo tipo, esto permite NO preguntarle nada.
    4. El tipo de curso otra vez, ahora como default blando: curso y taller
       son educacion continua.
    5. Educacion continua como ultimo recurso, que es el caso conservador:
       cobra matricula. Es preferible que sobre un cobro visible y alguien
       lo corrija, a que falte en silencio y el programa cierre con menos
       ingresos de los que correspondia.

    El diplomado no aparece en ninguna regla dura a proposito: Kevin
    confirmo que "hay diplomados uno educacion continua y el otro
    profesional", asi que se resuelve por (2) o (3), nunca adivinando.
    """
    tipo = (tipo_curso or "").strip().lower()

    if tipo in TIPOS_CURSO_SIEMPRE_PROFESIONAL:
        return AmbitoFormacion.PROFESIONAL

    if ambito_explicito:
        return AmbitoFormacion(ambito_explicito)

    if ambito_del_creador:
        return AmbitoFormacion(ambito_del_creador)

    if tipo in TIPOS_CURSO_DEFAULT_CONTINUA:
        return AmbitoFormacion.EDUCACION_CONTINUA

    return AmbitoFormacion.EDUCACION_CONTINUA


def normalizar_matriculas(course: "Course") -> None:
    """
    P-AMBITO-FORMACION (2026-08-18): deja las matriculas del curso en un
    estado que no pueda malinterpretarse. Muta el course en memoria.

    EL BUG QUE ESTO ARREGLA
    -----------------------
    `matricula_primer_carrera` y `matricula_profesional` en None NO
    significan "sin matricula": significan "cobra el default global"
    (200 / 500 Bs). Pero el formulario los presenta como campos opcionales
    vacios, que todo el mundo lee como "no cobra nada".

    Peor: el campo que el encargado VE y completa es `matricula_interno`,
    que `get_matricula_for_student()` ni siquiera mira. En la capacitacion
    del 2026-08-18 se creo un programa profesional con "Matricula = 0" y el
    bloque diferenciado vacio; el resultado real es que cada estudiante
    queda con 200 o 500 Bs de matricula, y por la Regla de Matricula no
    pasa a "Activo" hasta pagar algo que no deberia existir.

    Despues de llamar a esta funcion, los tres campos son siempre numeros
    concretos y coherentes con el ambito. Ningun None sobrevive, asi que la
    pantalla y el cobro dicen lo mismo.
    """
    ambito = course.ambito

    if ambito == AmbitoFormacion.PROFESIONAL:
        # Matricula UNICA: la que el programa define en `matricula_interno`,
        # igual para todos los alumnos. Se copia a los dos campos
        # diferenciados para que queden coherentes y, sobre todo, para que
        # NUNCA queden en None — None significa "cobra el default global"
        # (200 / 500), que es justo lo que descolocaba el cobro.
        unica = float(course.matricula_interno or 0)
        course.matricula_interno = unica
        course.matricula_primer_carrera = unica
        course.matricula_profesional = unica
        return

    # Educacion continua: manda la matricula diferenciada. Si no vino, se
    # materializa el default global en el curso en vez de dejarlo implicito,
    # para que lo guardado sea exactamente lo que se va a cobrar.
    if course.matricula_primer_carrera is None:
        course.matricula_primer_carrera = float(settings.MATRICULA_PRIMER_CARRERA_DEFAULT or 0)
    if course.matricula_profesional is None:
        course.matricula_profesional = float(settings.MATRICULA_PROFESIONAL_DEFAULT or 0)


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
    # P-AMBITO-FORMACION (2026-08-18, corregido por Kevin la misma noche):
    # un programa PROFESIONAL cobra matricula UNICA, igual para todos, la que
    # el programa define en `matricula_interno`. Lo que es exclusivo de
    # educacion continua es la matricula DIFERENCIADA (200 primera carrera /
    # 500 profesional), que depende del alumno.
    #
    # Primera version de este fix asumia que profesional = sin matricula.
    # Kevin lo corrigio con dos casos reales: MAES-GTAF-2026/1 cobra 1300 y
    # DIPL-IA-2026 cobra 300, y los dos son profesionales.
    #
    # ESTE ES EL BUG DE FONDO: `matricula_interno` es el campo que el
    # encargado completa en el formulario, y hasta ahora esta funcion ni lo
    # miraba. Caia siempre en los diferenciados y, si estaban en None, en los
    # defaults globales. Efecto medido en produccion: los 87 inscritos de
    # MAES-GTAF-2026/1 quedaron con costo_matricula=200 en vez de 1300, o sea
    # 1.100 Bs menos por alumno — 95.700 Bs sin facturar.
    if getattr(course, "ambito", None) == AmbitoFormacion.PROFESIONAL:
        return float(course.matricula_interno or 0)

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
