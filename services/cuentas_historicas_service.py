"""
Servicio de Cuentas Históricas
==============================

F-CUENTAS-HISTORICAS (2026-08-16, Kevin): los programas marcados con
`es_historico=True` dejaron de contar en el Dashboard y en Cuentas por
Cobrar — son carga retroactiva, expediente para tener guardado, no cartera
corriente. Pero Kevin pidió explícitamente NO perderlos de vista:

    "todo programa historico ya no debe contarse como actual, solo son
     datos para tener guardados pero debemos siempre tenerlos en cuenta
     con nuevos informes solo de esos programas"

Este servicio es la contraparte: arma el mismo tipo de resumen económico
que `cuentas_por_cobrar_service`, pero EXCLUSIVAMENTE sobre los programas
históricos.

Diferencias de criterio respecto de Cuentas por Cobrar, y por qué:

- CxC excluye enrollments SUSPENDIDO / RETIRADO / CANCELADO / COMPLETADO
  porque son cartera que ya no se persigue. Acá se conservan COMPLETADO,
  porque en un programa histórico lo normal es justamente que las
  inscripciones estén completadas: si se excluyeran, casi todo el reporte
  quedaría vacío y no serviría como expediente.
  Se siguen excluyendo CANCELADO y RETIRADO (nunca fueron cartera real).

- El saldo se recalcula contra los pagos aprobados, igual que CxC v2, para
  no depender de que `total_pagado` esté sincronizado.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional

from beanie import PydanticObjectId

from models.course import Course
from models.enrollment import Enrollment
from models.enums import EstadoInscripcion, EstadoPago
from models.payment import Payment
from models.student import Student
from models.user import User


# En un historico, COMPLETADO es el estado esperado: no se excluye.
ESTADOS_EXCLUIDOS_HIST = {
    EstadoInscripcion.CANCELADO,
    EstadoInscripcion.RETIRADO,
}


@dataclass
class HistEnrollment:
    enrollment_id: str
    estudiante_id: str
    estudiante_nombre: str
    estudiante_registro: Optional[str]
    curso_id: str
    curso_nombre: str
    estado: str
    total_a_pagar: float
    total_pagado: float
    saldo: float


@dataclass
class HistCurso:
    curso_id: str
    curso_nombre: str
    curso_codigo: Optional[str]
    fecha_inicio: Optional[datetime]
    fecha_fin: Optional[datetime]
    cantidad_estudiantes: int
    total_esperado: float
    total_cobrado: float
    saldo_pendiente: float
    avance_pct: float


@dataclass
class HistResumen:
    total_programas: int
    total_estudiantes: int
    total_esperado: float
    total_cobrado: float
    saldo_pendiente: float
    avance_pct: float
    por_curso: List[HistCurso]
    detalle: List[HistEnrollment]
    generado_en: datetime


def _nombre_estudiante(s) -> str:
    """Igual criterio que en CxC: siempre devuelve string. Ver F-FIX-CXC-NOMBRE-NULO."""
    if s is None:
        return "—"
    nombre = getattr(s, "nombre", None)
    if nombre:
        return str(nombre)
    registro = getattr(s, "registro", None)
    if registro:
        return "(sin nombre) Reg. %s" % registro
    return "—"


async def generar_resumen_historico(
    current_user: User,
    curso_id: Optional[str] = None,
) -> HistResumen:
    """
    Resumen económico de los programas históricos.

    Respeta el alcance por rol: si el usuario tiene `cursos_asignados`
    (encargado/coordinador segmentado), solo ve los suyos.
    """
    # 1. Cursos historicos dentro del alcance del usuario
    query_curso: dict = {"es_historico": True}
    if current_user.cursos_asignados:
        query_curso["_id"] = {
            "$in": [PydanticObjectId(c) for c in current_user.cursos_asignados]
        }
    if curso_id:
        try:
            query_curso["_id"] = PydanticObjectId(curso_id)
        except Exception:
            pass  # id invalido -> se ignora el filtro

    cursos = await Course.find(query_curso).to_list()
    if not cursos:
        return HistResumen(
            total_programas=0, total_estudiantes=0, total_esperado=0.0,
            total_cobrado=0.0, saldo_pendiente=0.0, avance_pct=0.0,
            por_curso=[], detalle=[], generado_en=datetime.now(timezone.utc),
        )

    curso_map = {c.id: c for c in cursos}
    curso_ids = list(curso_map.keys())

    # 2. Enrollments de esos cursos
    estados_ok = [
        e.value for e in EstadoInscripcion if e not in ESTADOS_EXCLUIDOS_HIST
    ]
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": curso_ids}, "estado": {"$in": estados_ok}}
    ).to_list()

    # 3. Estudiantes y pagos, en lote (mismo patron que CxC tras F-FIX-CXC-N1:
    #    nada de una query por inscripcion).
    estudiante_ids = list({e.estudiante_id for e in enrollments})
    estudiantes = await Student.find({"_id": {"$in": estudiante_ids}}).to_list()
    estudiante_map = {s.id: s for s in estudiantes}

    pagos_por_inscripcion: dict = {}
    if enrollments:
        pagos = await Payment.find(
            {
                "inscripcion_id": {"$in": [e.id for e in enrollments]},
                "estado_pago": EstadoPago.APROBADO.value,
            }
        ).to_list()
        for p in pagos:
            pagos_por_inscripcion.setdefault(p.inscripcion_id, []).append(p)

    # 4. Armar detalle y acumular por curso
    detalle: List[HistEnrollment] = []
    acc: dict = {}

    for e in enrollments:
        c = curso_map.get(e.curso_id)
        s = estudiante_map.get(e.estudiante_id)
        total_a_pagar = float(getattr(e, "total_a_pagar", 0) or 0)
        cobrado = sum(
            float(p.cantidad_pago or 0) for p in pagos_por_inscripcion.get(e.id, [])
        )
        saldo = max(0.0, total_a_pagar - cobrado)

        detalle.append(HistEnrollment(
            enrollment_id=str(e.id),
            estudiante_id=str(e.estudiante_id),
            estudiante_nombre=_nombre_estudiante(s),
            estudiante_registro=getattr(s, "registro", None) if s else None,
            curso_id=str(e.curso_id),
            curso_nombre=c.nombre_programa if c else "Programa desconocido",
            # `e.estado` puede venir como enum o como str segun de donde se
            # cargue. `str(enum)` da "EstadoInscripcion.PENDIENTE_PAGO", que es
            # basura para la UI; hay que quedarse con el .value.
            estado=getattr(e.estado, "value", None) or str(e.estado),
            total_a_pagar=round(total_a_pagar, 2),
            total_pagado=round(cobrado, 2),
            saldo=round(saldo, 2),
        ))

        a = acc.setdefault(e.curso_id, {"n": 0, "esperado": 0.0, "cobrado": 0.0})
        a["n"] += 1
        a["esperado"] += total_a_pagar
        a["cobrado"] += cobrado

    por_curso: List[HistCurso] = []
    for cid, a in acc.items():
        c = curso_map.get(cid)
        saldo = max(0.0, a["esperado"] - a["cobrado"])
        por_curso.append(HistCurso(
            curso_id=str(cid),
            curso_nombre=c.nombre_programa if c else "Programa desconocido",
            curso_codigo=getattr(c, "codigo", None) if c else None,
            fecha_inicio=getattr(c, "fecha_inicio", None) if c else None,
            fecha_fin=getattr(c, "fecha_fin", None) if c else None,
            cantidad_estudiantes=a["n"],
            total_esperado=round(a["esperado"], 2),
            total_cobrado=round(a["cobrado"], 2),
            saldo_pendiente=round(saldo, 2),
            avance_pct=round(100 * a["cobrado"] / a["esperado"], 1) if a["esperado"] else 0.0,
        ))

    # Los que mas deuda arrastran primero: es lo primero que se quiere mirar.
    por_curso.sort(key=lambda x: -x.saldo_pendiente)
    detalle.sort(key=lambda x: (-x.saldo, x.estudiante_nombre))

    total_esperado = sum(c.total_esperado for c in por_curso)
    total_cobrado = sum(c.total_cobrado for c in por_curso)

    return HistResumen(
        total_programas=len(por_curso),
        total_estudiantes=len(detalle),
        total_esperado=round(total_esperado, 2),
        total_cobrado=round(total_cobrado, 2),
        saldo_pendiente=round(max(0.0, total_esperado - total_cobrado), 2),
        avance_pct=round(100 * total_cobrado / total_esperado, 1) if total_esperado else 0.0,
        por_curso=por_curso,
        detalle=detalle,
        generado_en=datetime.now(timezone.utc),
    )
