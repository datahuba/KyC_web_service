"""
Servicio de Cuentas por Cobrar
==============================

F-CUENTAS-POR-COBRAR (2026-07-29): lógica de CxC real vs estimada para
informes financieros del staff (Sandra, Rocío, MAE, Cobranza).

Concepto contable:
- CxC estimada (o "Por Cobrar Total") = suma de todos los saldo_pendiente
  de todos los enrollments activos. Es lo que la universidad espera cobrar
  si todos los estudiantes terminan el programa completo.
- CxC a la fecha (o "Por Cobrar Real") = suma de (total_a_pagar -
  pagos aprobados) por cada enrollment activo. Refleja el saldo contable
  real basado en los pagos efectivamente aprobados, independiente de si
  el módulo está marcado como iniciado o no.

  F-CUENTAS-POR-COBRAR v2 (2026-08-03): se cambió la definición. Antes era
  "módulos iniciados" pero eso podía inflar la CxC con módulos marcados
  manualmente como iniciados sin pago. Ahora es contable puro.

Excluidos automáticamente del reporte:
- Enrollments SUSPENDIDO (pasivos), RETIRADO, CANCELADO, COMPLETADO.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from beanie import PydanticObjectId

from models.course import Course
from models.enrollment import Enrollment, ModuloEstado
from models.enums import EstadoInscripcion, EstadoPago
from models.payment import Payment
from models.student import Student
from models.user import User


# Estados que NO cuentan para CxC (Kevin: pasivo, abandono, retirado)
ESTADOS_EXCLUIDOS_CXC = {
    EstadoInscripcion.SUSPENDIDO,
    EstadoInscripcion.RETIRADO,
    EstadoInscripcion.CANCELADO,
    EstadoInscripcion.COMPLETADO,
}


@dataclass
class CxCResumenModulo:
    """Resumen de un módulo dentro del reporte de CxC."""
    nombre: str
    modulo_index: int
    costo: float
    monto_pagado: float
    saldo_pendiente: float
    iniciado_en: Optional[datetime]
    # True si cuenta para CxC real (iniciado Y enrollment no excluido)
    cuenta_cxc_real: bool


@dataclass
class CxCResumenEnrollment:
    """Resumen de un enrollment en el reporte de CxC."""
    enrollment_id: str
    estudiante_id: str
    estudiante_nombre: str
    estudiante_registro: Optional[str]
    curso_id: str
    curso_nombre: str
    estado: str  # EstadoInscripcion.value
    total_a_pagar: float
    total_pagado: float
    saldo_estimado: float  # CxC estimada
    saldo_a_la_fecha: float  # CxC real
    modulos: List[CxCResumenModulo]


@dataclass
class CxCResumenCurso:
    """Resumen agrupado por curso en el reporte de CxC."""
    curso_id: str
    curso_nombre: str
    curso_codigo: Optional[str]
    cantidad_estudiantes: int
    total_estimado: float
    total_a_la_fecha: float


@dataclass
class CxCResumen:
    """Resumen global del reporte de CxC."""
    total_estimado: float
    total_a_la_fecha: float
    total_modulos_iniciados: int
    total_modulos_no_iniciados: int
    cantidad_enrollments: int
    cantidad_cursos: int
    por_curso: List[CxCResumenCurso]
    detalle: List[CxCResumenEnrollment]
    generado_en: datetime


def _calcular_saldo_modulo(m: ModuloEstado) -> float:
    """Saldo pendiente de un módulo (costo - monto_pagado)."""
    costo = getattr(m, "costo", 0) or 0
    pagado = getattr(m, "monto_pagado", 0) or 0
    return max(0.0, costo - pagado)


def _modulo_cuenta_cxc(m: ModuloEstado) -> bool:
    """True si el módulo cuenta para la CxC real (fue iniciado)."""
    return m.iniciado_en is not None


def _enrollment_excluido(e: Enrollment) -> bool:
    """True si el enrollment no debe contar para CxC (pasivo, retirado, etc.)."""
    return e.estado in ESTADOS_EXCLUIDOS_CXC


async def generar_resumen_cxc(
    current_user: User,
    curso_id: Optional[str] = None,
) -> CxCResumen:
    """
    Genera el resumen de CxC para el usuario actual.

    Aplica filtro de cursos por rol (cursos_asignados si es encargado_segmentado).
    Filtra enrollments excluidos (pasivos, retirados, cancelados, completados).

    Args:
        current_user: Usuario autenticado (debe tener permisos de staff).
        curso_id: Filtro opcional por curso específico.

    Returns:
        CxCResumen con totales y detalle por curso/enrollment/módulo.
    """
    # Filtro de cursos por segmentación
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
    if current_user.cursos_asignados:
        cursos_permitidos = [
            PydanticObjectId(cid) for cid in current_user.cursos_asignados
        ]

    # Construir query base
    estados_incluidos = [e for e in EstadoInscripcion if e not in ESTADOS_EXCLUIDOS_CXC]
    query: dict = {"estado": {"$in": [e.value for e in estados_incluidos]}}
    if cursos_permitidos is not None:
        query["curso_id"] = {"$in": cursos_permitidos}
    if curso_id:
        try:
            query["curso_id"] = PydanticObjectId(curso_id)
        except Exception:
            pass  # curso_id inválido → ignorar

    enrollments = await Enrollment.find(query).to_list()

    # Indexar cursos en un mapa (una sola query)
    curso_ids = list({e.curso_id for e in enrollments})
    cursos = await Course.find({"_id": {"$in": curso_ids}}).to_list()
    curso_map: dict = {c.id: c for c in cursos}

    # Indexar estudiantes
    estudiante_ids = list({e.estudiante_id for e in enrollments})
    estudiantes = await Student.find({"_id": {"$in": estudiante_ids}}).to_list()
    estudiante_map: dict = {s.id: s for s in estudiantes}

    # Construir detalle
    detalle: List[CxCResumenEnrollment] = []
    total_estimado = 0.0
    total_a_la_fecha = 0.0
    total_modulos_iniciados = 0
    total_modulos_no_iniciados = 0

    # Acumuladores por curso
    curso_acc: dict = {}

    for e in enrollments:
        s = estudiante_map.get(e.estudiante_id)
        c = curso_map.get(e.curso_id)
        curso_nombre = c.nombre_programa if c else "Curso desconocido"
        curso_codigo = c.codigo if c else None

        # Saldo del enrollment
        saldo_estimado = e.saldo_pendiente
        # F-CUENTAS-POR-COBRAR v2 (2026-08-03, Kevin): CxC real ahora es
        # "Inscripción total - Pagos aprobados", NO depende de los módulos
        # marcados como iniciados. Recalculamos en tiempo real con los pagos
        # de la tabla payments (estado_pago=APROBADO) para corregir
        # automáticamente cualquier desincronización del campo
        # enrollment.total_pagado.
        pagos_aprobados = await Payment.find(
            Payment.inscripcion_id == e.id,
            Payment.estado_pago == EstadoPago.APROBADO,
        ).to_list()
        total_pagado_real = sum(p.cantidad_pago for p in pagos_aprobados)
        saldo_a_la_fecha = max(0.0, e.total_a_pagar - total_pagado_real)

        # Contar módulos
        for m in e.modulos:
            if _modulo_cuenta_cxc(m):
                total_modulos_iniciados += 1
            else:
                total_modulos_no_iniciados += 1

        # Acumular por curso
        if e.curso_id not in curso_acc:
            curso_acc[e.curso_id] = {
                "curso_id": str(e.curso_id),
                "curso_nombre": curso_nombre,
                "curso_codigo": curso_codigo,
                "cantidad_estudiantes": 0,
                "total_estimado": 0.0,
                "total_a_la_fecha": 0.0,
            }
        acc = curso_acc[e.curso_id]
        acc["cantidad_estudiantes"] += 1
        acc["total_estimado"] += saldo_estimado
        acc["total_a_la_fecha"] += saldo_a_la_fecha

        # Detalle de módulos
        modulos_detalle: List[CxCResumenModulo] = []
        for idx, m in enumerate(e.modulos):
            modulos_detalle.append(CxCResumenModulo(
                nombre=m.nombre,
                modulo_index=idx,
                costo=getattr(m, "costo", 0) or 0,
                monto_pagado=getattr(m, "monto_pagado", 0) or 0,
                saldo_pendiente=_calcular_saldo_modulo(m),
                iniciado_en=m.iniciado_en,
                cuenta_cxc_real=_modulo_cuenta_cxc(m),
            ))

        detalle.append(CxCResumenEnrollment(
            enrollment_id=str(e.id),
            estudiante_id=str(e.estudiante_id),
            estudiante_nombre=s.nombre if s else "—",
            estudiante_registro=s.registro if s else None,
            curso_id=str(e.curso_id),
            curso_nombre=curso_nombre,
            estado=e.estado.value if hasattr(e.estado, "value") else str(e.estado),
            total_a_pagar=e.total_a_pagar,
            total_pagado=e.total_pagado,
            saldo_estimado=saldo_estimado,
            saldo_a_la_fecha=saldo_a_la_fecha,
            modulos=modulos_detalle,
        ))

        total_estimado += saldo_estimado
        total_a_la_fecha += saldo_a_la_fecha

    por_curso = [CxCResumenCurso(**acc) for acc in curso_acc.values()]

    return CxCResumen(
        total_estimado=round(total_estimado, 2),
        total_a_la_fecha=round(total_a_la_fecha, 2),
        total_modulos_iniciados=total_modulos_iniciados,
        total_modulos_no_iniciados=total_modulos_no_iniciados,
        cantidad_enrollments=len(enrollments),
        cantidad_cursos=len(curso_acc),
        por_curso=por_curso,
        detalle=detalle,
        generado_en=datetime.now(timezone.utc),
    )


async def iniciar_modulo(
    enrollment: Enrollment,
    modulo_index: int,
    current_user: User,
    force: bool = False,
) -> Enrollment:
    """
    Marca un módulo como 'iniciado_en = utcnow()'.

    Validaciones:
    - modulo_index está en rango.
    - el módulo no estaba ya iniciado (idempotencia: si ya lo está, no-op).
    - el enrollment no está excluido (COMPLETADO, RETIRADO, SUSPENDIDO,
      CANCELADO).
    - F-MODAL-GESTION-MODULOS (2026-08-03, Kevin): el módulo anterior debe
      estar FINALIZADO (encadenamiento académico), excepto el primero.
      Se puede saltar con `force=True` (solo superadmin en el endpoint).

    Raises:
        HTTPException 400 / 404 / 409 según el caso.
    """
    from fastapi import HTTPException, status

    if _enrollment_excluido(enrollment):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"No se puede iniciar un módulo en un enrollment con estado "
                f"'{enrollment.estado.value}'. Solo estados activos."
            ),
        )

    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Índice de módulo inválido: {modulo_index}. "
                f"El programa tiene {len(enrollment.modulos)} módulos (0..{len(enrollment.modulos) - 1})."
            ),
        )

    # F-MODAL-GESTION-MODULOS (2026-08-03, Kevin): encadenamiento.
    # El módulo N+1 solo se puede iniciar si el módulo N está finalizado
    # (refleja el flujo académico real). El superadmin puede saltarse esta
    # regla con force=True (caso de excepción o plan especial).
    if modulo_index > 0 and not force:
        anterior = enrollment.modulos[modulo_index - 1]
        if not anterior.finalizado_en:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"No se puede iniciar el módulo #{modulo_index + 1} "
                    f"('{enrollment.modulos[modulo_index].nombre[:40]}') "
                    f"porque el módulo anterior #{modulo_index} no está finalizado. "
                    f"Cierra el módulo anterior primero, o usa force=true "
                    f"si eres superadmin."
                ),
            )

    m = enrollment.modulos[modulo_index]
    if m.iniciado_en is not None:
        # Idempotente: ya estaba iniciado, no-op
        return enrollment

    m.iniciado_en = datetime.now(timezone.utc)
    await enrollment.save()
    return enrollment


async def deshacer_inicio_modulo(
    enrollment: Enrollment,
    modulo_index: int,
    current_user: User,
) -> Enrollment:
    """
    Revierte un módulo a 'iniciado_en = None' (caso de error humano).

    Raises:
        HTTPException 400 / 404 / 409 según el caso.
    """
    from fastapi import HTTPException, status

    if modulo_index < 0 or modulo_index >= len(enrollment.modulos):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Índice de módulo inválido: {modulo_index}.",
        )

    m = enrollment.modulos[modulo_index]
    if m.iniciado_en is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"El módulo {modulo_index + 1} aún no estaba iniciado.",
        )

    m.iniciado_en = None
    await enrollment.save()
    return enrollment
