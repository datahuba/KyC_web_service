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
    # Capas contables (2026-08-21, Kevin: Principio de Devengado)
    recaudacion_efectiva: float  # Pagos aprobados en esta inscripción
    total_devengado: float       # Matrícula + Módulos iniciados
    cxc_devengada: float         # Exigible real en mora: max(0, total_devengado - recaudacion_efectiva)
    proyeccion_futura: float     # Módulos no iniciados (no devengado aún)
    saldo_estimado: float        # Saldo contrato total: max(0, total_a_pagar - recaudacion_efectiva)
    saldo_a_la_fecha: float      # Mantener compatibilidad: igual a cxc_devengada
    modulos: List[CxCResumenModulo]


@dataclass
class CxCResumenCurso:
    """Resumen agrupado por curso en el reporte de CxC."""
    curso_id: str
    curso_nombre: str
    curso_codigo: Optional[str]
    cantidad_estudiantes: int
    recaudacion_efectiva: float
    total_devengado: float
    cxc_devengada: float         # Exigible real en mora del curso
    proyeccion_futura: float     # Módulos no iniciados del curso
    total_estimado: float        # Saldo contrato total
    total_a_la_fecha: float      # Mantener compatibilidad: igual a cxc_devengada


@dataclass
class CxCResumen:
    """Resumen global del reporte de CxC (Capas Contables Devengado vs Proyección)."""
    recaudacion_efectiva: float
    total_devengado: float
    cxc_devengada: float         # VERDADERA CUENTA POR COBRAR EN MORA (Exigible)
    proyeccion_futura: float     # PROYECCIÓN FUTURA NO DEVENGADA
    total_estimado: float        # CONTRATOS TOTALES PENDIENTES
    total_a_la_fecha: float      # Mantener compatibilidad: igual a cxc_devengada
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


def _nombre_estudiante(s) -> str:
    """Nombre mostrable de un estudiante, tolerante a datos incompletos.

    Devuelve SIEMPRE un string porque el schema de salida lo exige. Orden de
    preferencia: nombre real -> registro (util para que cobranzas igual pueda
    identificar la fila) -> guion. Ver F-FIX-CXC-NOMBRE-NULO.
    """
    if s is None:
        return "—"
    nombre = getattr(s, "nombre", None)
    if nombre:
        return str(nombre)
    registro = getattr(s, "registro", None)
    if registro:
        return "(sin nombre) Reg. %s" % registro
    return "—"


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

    # F-CXC-EXCLUIR-HISTORICOS (2026-08-04, Kevin): los cursos HISTORICOS
    # (es_historico=True) NO cuentan para CxC. Esos programas ya terminaron
    # (son de carga retroactiva/auditoria), no se les cobra nada.
    # Kevin: "todo curso historico o programa en este caso no debe tomarse
    # en cuenta para cuentas por cobrar si es que las tienen solamente las
    # de en ejecucion de modulos ejecutandose y modulos por ejecutarse
    # como programas por ejecutarse".
    # En resumen, los que SÍ cuentan para CxC:
    #   - en_ejecucion: modulos ejecutandose
    #   - programado:    programas por ejecutarse
    # Los que NO cuentan:
    #   - historico:    ya terminaron
    #   - cerrado:       cancelados/finalizados
    cursos_a_excluir = set()
    for c in cursos:
        estado = c.get_estado_actual() if hasattr(c, "get_estado_actual") else None
        es_historico_flag = getattr(c, "es_historico", False)
        if es_historico_flag or estado == "cerrado":
            # historicos y cerrados: NO cuentan para CxC
            cursos_a_excluir.add(c.id)
    if cursos_a_excluir:
        enrollments = [e for e in enrollments if e.curso_id not in cursos_a_excluir]

    # Indexar estudiantes
    estudiante_ids = list({e.estudiante_id for e in enrollments})
    estudiantes = await Student.find({"_id": {"$in": estudiante_ids}}).to_list()
    estudiante_map: dict = {s.id: s for s in estudiantes}

    # Construir detalle
    detalle: List[CxCResumenEnrollment] = []
    global_recaudacion_efectiva = 0.0
    global_total_devengado = 0.0
    global_cxc_devengada = 0.0
    global_proyeccion_futura = 0.0
    global_total_estimado = 0.0
    total_modulos_iniciados = 0
    total_modulos_no_iniciados = 0

    # F-FIX-CXC-N1 (2026-08-16): ya vienen precargados arriba en una sola query
    pagos_por_inscripcion: dict = {}
    if enrollments:
        todos_los_pagos = await Payment.find(
            {
                "inscripcion_id": {"$in": [e.id for e in enrollments]},
                "estado_pago": EstadoPago.APROBADO.value,
            }
        ).to_list()
        for p in todos_los_pagos:
            pagos_por_inscripcion.setdefault(p.inscripcion_id, []).append(p)

    # Acumuladores por curso
    curso_acc: dict = {}

    for e in enrollments:
        s = estudiante_map.get(e.estudiante_id)
        c = curso_map.get(e.curso_id)
        curso_nombre = c.nombre_programa if c else "Curso desconocido"
        curso_codigo = c.codigo if c else None

        # 1. Recaudación Efectiva (Pagos Aprobados)
        pagos_aprobados = pagos_por_inscripcion.get(e.id, [])
        recaudacion_efectiva = sum(p.cantidad_pago for p in pagos_aprobados)

        # 2. Total Devengado (Matrícula + Módulos Iniciados)
        costo_matricula = float(getattr(e, "matricula_monto", 0) or 0)
        costo_modulos_iniciados = sum(
            float(getattr(m, "costo", 0) or 0)
            for m in e.modulos
            if _modulo_cuenta_cxc(m)
        )
        total_devengado = costo_matricula + costo_modulos_iniciados

        # 3. CxC Devengada (Exigible Real en Mora por servicio iniciado/en curso)
        cxc_devengada = max(0.0, total_devengado - recaudacion_efectiva)

        # 4. Proyección Futura No Devengada (Módulos no iniciados)
        proyeccion_futura = sum(
            float(getattr(m, "costo", 0) or 0)
            for m in e.modulos
            if not _modulo_cuenta_cxc(m)
        )

        # 5. Saldo Estimado Total del Contrato
        saldo_estimado = max(0.0, e.total_a_pagar - recaudacion_efectiva)
        saldo_a_la_fecha = cxc_devengada  # Mantiene retrocompatibilidad

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
                "recaudacion_efectiva": 0.0,
                "total_devengado": 0.0,
                "cxc_devengada": 0.0,
                "proyeccion_futura": 0.0,
                "total_estimado": 0.0,
                "total_a_la_fecha": 0.0,
            }
        acc = curso_acc[e.curso_id]
        acc["cantidad_estudiantes"] += 1
        acc["recaudacion_efectiva"] += recaudacion_efectiva
        acc["total_devengado"] += total_devengado
        acc["cxc_devengada"] += cxc_devengada
        acc["proyeccion_futura"] += proyeccion_futura
        acc["total_estimado"] += saldo_estimado
        acc["total_a_la_fecha"] += cxc_devengada

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
            estudiante_nombre=_nombre_estudiante(s),
            estudiante_registro=s.registro if s else None,
            curso_id=str(e.curso_id),
            curso_nombre=curso_nombre,
            estado=e.estado.value if hasattr(e.estado, "value") else str(e.estado),
            total_a_pagar=e.total_a_pagar,
            total_pagado=recaudacion_efectiva,
            recaudacion_efectiva=recaudacion_efectiva,
            total_devengado=total_devengado,
            cxc_devengada=cxc_devengada,
            proyeccion_futura=proyeccion_futura,
            saldo_estimado=saldo_estimado,
            saldo_a_la_fecha=saldo_a_la_fecha,
            modulos=modulos_detalle,
        ))

        global_recaudacion_efectiva += recaudacion_efectiva
        global_total_devengado += total_devengado
        global_cxc_devengada += cxc_devengada
        global_proyeccion_futura += proyeccion_futura
        global_total_estimado += saldo_estimado

    por_curso = [CxCResumenCurso(**acc) for acc in curso_acc.values()]

    return CxCResumen(
        recaudacion_efectiva=round(global_recaudacion_efectiva, 2),
        total_devengado=round(global_total_devengado, 2),
        cxc_devengada=round(global_cxc_devengada, 2),
        proyeccion_futura=round(global_proyeccion_futura, 2),
        total_estimado=round(global_total_estimado, 2),
        total_a_la_fecha=round(global_cxc_devengada, 2),
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
