"""
F-AJUSTE-PAGOS-EXCEL (2026-08-10, Kevin) - v2
=============================================

Endpoint para cuadrar los pagos del sistema con la planilla Excel oficial
de la UAGRM, considerada la fuente de verdad al 2026-08-10.

VERSION 2 (F-AJUSTE-PAGOS-EXCEL-FIX-IDEMPOTENCIA):
- Antes: para tipo=diff creaba 1 pago de 35; para tipo=completo creaba 6 pagos
  pero sin borrar los previos. Resultado: ejecuciones multiples generaban
  duplicados (4 restaurados terminaron con 18 pagos = 3 sets de 6).
- Ahora: SIEMPRE borra los pagos "Ajuste por cuadre con Excel" previos
  antes de crear nuevos. Idempotente: ejecutar 2 veces da el mismo resultado.
- Para tipo=diff: crea 6 pagos (5 modulos a 252 + 1 modulo a 210 = 1470).
  Razon: el Excel dice que el estudiante pagó 1470 total. Independientemente
  de que los modulos ya estuvieran ajustados a 252, los pagos en la coleccion
  payments deben sumar 1470 (5 pagos de 245 o 6 pagos de 252+210 son
  equivalentes a nivel de planilla Excel).

ESTRUCTURA CANON DE MODULOS DEL CURSO DIPL-INVCI-2026/1:
- 5 modulos a 252 + 1 modulo a 210 = 1470
- Total: 1470 Bs (cuadra con Excel)

POR QUE NO USAR /payments/by-staff:
- El endpoint /payments/by-staff recalcula los modulos desde cero cada vez.
- Cuando hay pagos históricos sin asociacion a `pagos_modulos`, el recálculo
  los borra silenciosamente. Verificado en ITER 2 (2026-08-10) con el caso
  de Sandra Villafani (5 pagos de 287 Bs perdidos) y Monica Vargas (5 pagos
  de 245 Bs borrados por la prueba inicial).
- Este endpoint hace UPDATE directo sin pasar por el recálculo.

PROTECCION:
- Solo superadmin puede ejecutarlo
- Requiere header X-Confirmar-Ajuste=yes para evitar accidentes
- Idempotente: borra los pagos Ajuste previos antes de crear nuevos

USO:
    POST /api/v1/admin/accounting/ajustar-pagos-excel
    {
        "dry_run": false,
        "ajustes": [
            {
                "estudiante_carnet": "1112227",
                "curso_codigo": "DIPL-INVCI-2026/1",
                "tipo": "completo",
                "monto_objetivo": 1470,
                "nota": "Sandra Villafani - restaurar pagos perdidos"
            },
            ...
        ]
    }
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, Field
from bson import ObjectId

from models import Enrollment, Payment, Student, Course
from models.user import User, UserRole
from models.enums import EstadoPago
from api.dependencies import get_current_user
from core.timezone_utils import utcnow_naive

router = APIRouter(tags=["admin-accounting"])
logger = logging.getLogger("kyc.admin_accounting")

# Cabecera obligatoria para ejecutar (anti-click-accidental)
CONFIRM_HEADER = "X-Confirmar-Ajuste"

# Marca para identificar los pagos creados por este endpoint
PAGO_MARCA = "Ajuste por cuadre con Excel"


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo usuarios pueden acceder a /admin/accounting")
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Solo superadmin puede ejecutar ajustes contables")
    return current_user


class AjusteItem(BaseModel):
    estudiante_carnet: str = Field(..., description="Carnet de identidad del estudiante")
    curso_codigo: str = Field(..., description="Codigo del curso (ej: DIPL-INVCI-2026/1)")
    tipo: str = Field(..., description="'diff' | 'completo' | 'crear_enrollment'")
    monto_objetivo: float = Field(..., description="Monto total esperado segun Excel")
    nota: Optional[str] = Field(None, description="Nota explicativa del ajuste (auditoria)")


class AjusteRequest(BaseModel):
    dry_run: bool = Field(default=True, description="Si true, solo previsualiza sin aplicar")
    ajustes: List[AjusteItem] = Field(..., min_length=1, max_length=200)


class AjusteResultado(BaseModel):
    estudiante_carnet: str
    estudiante_nombre: str
    curso_codigo: str
    tipo: str
    exito: bool
    dry_run: bool
    antes: Dict[str, Any] = Field(default_factory=dict)
    despues: Dict[str, Any] = Field(default_factory=dict)
    pagos_creados: int = 0
    pagos_borrados: int = 0
    modulos_actualizados: int = 0
    error: Optional[str] = None
    nota: Optional[str] = None


class AjusteResponse(BaseModel):
    dry_run: bool
    ejecutor: str
    timestamp: str
    total_ajustes: int
    exitosos: int
    fallidos: int
    pagos_creados_total: int
    pagos_borrados_total: int
    modulos_actualizados_total: int
    resultados: List[AjusteResultado]


# Estructura canon de los 6 pagos del curso DIPL-INVCI-2026/1
# 5 modulos a 252 + 1 modulo a 210 = 1470
PAGOS_CANONICOS_DIPL_INVCI = [
    {"numero": 1, "concepto_modulo": "Modulo 1", "monto": 252.0},
    {"numero": 2, "concepto_modulo": "Modulo 2", "monto": 252.0},
    {"numero": 3, "concepto_modulo": "Modulo 3", "monto": 252.0},
    {"numero": 4, "concepto_modulo": "Modulo 4", "monto": 252.0},
    {"numero": 5, "concepto_modulo": "Modulo 5", "monto": 252.0},
    {"numero": 6, "concepto_modulo": "Modulo 6", "monto": 210.0},
]

# Estructura canon de modulos del enrollment
MODULOS_CANONICOS = [
    {"nombre": "Modulo 1", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
    {"nombre": "Modulo 2", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
    {"nombre": "Modulo 3", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
    {"nombre": "Modulo 4", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
    {"nombre": "Modulo 5", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
    {"nombre": "Modulo 6", "costo": 210.0, "monto_pagado": 210.0, "estado": "Pagado", "estado_operacional": "Ejecutado", "estado_academico": "Cursando"},
]


async def _buscar_estudiante_por_carnet(carnet: str) -> Optional[Student]:
    """Busca estudiante por carnet o registro (en ese orden)."""
    s = await Student.find_one({"carnet": carnet})
    if s:
        return s
    s = await Student.find_one({"registro": carnet})
    return s


async def _buscar_curso_por_codigo(codigo: str) -> Optional[Course]:
    return await Course.find_one({"codigo": codigo})


async def _buscar_enrollment(estudiante_id: ObjectId, curso_id: ObjectId) -> Optional[Enrollment]:
    return await Enrollment.find_one({
        "estudiante_id": estudiante_id,
        "curso_id": curso_id,
    })


async def _borrar_pagos_ajuste(inscripcion_id: ObjectId) -> int:
    """Borra TODOS los pagos con la marca 'Ajuste por cuadre con Excel' para este enrollment.
    Retorna la cantidad de pagos borrados. Usado para garantizar idempotencia.

    F-AJUSTE-PAGOS-EXCEL-FIX-REGEX: en v2 el borrado retorno 0 porque la query
    Beanie con RegEx() no matcheaba. Usamos el dict literal con $regex que
    SI funciona (mismo patron usado en api/admin.py:112).
    """
    existing = await Payment.find({
        "inscripcion_id": inscripcion_id,
        "concepto": {"$regex": PAGO_MARCA, "$options": "i"},
    }).to_list()
    if not existing:
        return 0
    for p in existing:
        await p.delete()
    return len(existing)


async def _crear_pagos_canonicos(
    inscripcion_id: ObjectId,
    estudiante_id: ObjectId,
    curso_id: ObjectId,
    nota: str,
    monto_objetivo: Optional[float] = None,
) -> int:
    """Crea los pagos para cuadrar con el Excel.

    F-AJUSTE-PAGOS-EXCEL-FIX-MONTO-VARIABLE (2026-08-10, Kevin): antes esta
    funcion SIEMPRE creaba los 6 pagos canonicos (5x252 + 1x210 = 1470),
    ignorando el monto_objetivo del request. Eso causaba que estudiantes con
    Excel=245 o 735 recibieran pagos por 1470 en el sistema.

    Ahora:
    - Si monto_objetivo >= 1470: crea los 6 pagos canonicos (uno por modulo)
    - Si monto_objetivo < 1470: crea UN SOLO pago consolidado por monto_objetivo
      (caso de estudiantes becados o con pago parcial segun Excel)
    """
    now = utcnow_naive()
    timestamp_suffix = int(now.timestamp())
    if monto_objetivo is not None and monto_objetivo < sum(p["monto"] for p in PAGOS_CANONICOS_DIPL_INVCI):
        # Pago consolidado por monto_objetivo (caso pago parcial / beca)
        pago = Payment(
            inscripcion_id=inscripcion_id,
            estudiante_id=estudiante_id,
            curso_id=curso_id,
            concepto=f"{PAGO_MARCA} - Pago parcial",
            detalle=f"Cuadre con planilla Excel oficial 2026-08-10. Monto total: Bs {monto_objetivo}. {nota or ''}".strip(),
            metodo_pago="Ajuste Contable",
            numero_transaccion=f"AJUSTE-EXCEL-PARCIAL-{timestamp_suffix}",
            cantidad_pago=monto_objetivo,
            estado_pago=EstadoPago.APROBADO,
            fecha_subida=now,
            fecha_verificacion=now,
            verificado_por="admin_accounting_ajuste_excel",
            comprobante_url=None,
        )
        await pago.insert()
        return 1
    # Camino normal: 6 pagos canonicos (5x252 + 1x210 = 1470)
    for i, p in enumerate(PAGOS_CANONICOS_DIPL_INVCI, 1):
        pago = Payment(
            inscripcion_id=inscripcion_id,
            estudiante_id=estudiante_id,
            curso_id=curso_id,
            concepto=f"{PAGO_MARCA} - {p['concepto_modulo']}",
            detalle=f"Cuadre con planilla Excel oficial 2026-08-10. {nota or ''}".strip(),
            metodo_pago="Ajuste Contable",
            numero_transaccion=f"AJUSTE-EXCEL-M{i}-{timestamp_suffix}",
            cantidad_pago=p["monto"],
            estado_pago=EstadoPago.APROBADO,
            fecha_subida=now,
            fecha_verificacion=now,
            verificado_por="admin_accounting_ajuste_excel",
            comprobante_url=None,
        )
        await pago.insert()
    return len(PAGOS_CANONICOS_DIPL_INVCI)


async def _aplicar_ajuste(
    estudiante: Student,
    curso: Course,
    enrollment: Optional[Enrollment],
    tipo: str,
    monto_objetivo: float,
    nota: Optional[str],
    dry_run: bool,
) -> AjusteResultado:
    """Aplica el ajuste. Logica idempotente: borra pagos Ajuste previos antes de crear nuevos."""

    carnet_str = str(estudiante.carnet or estudiante.registro or "")
    nombre = estudiante.nombre or ""
    nota = nota or ""

    if tipo == "crear_enrollment":
        if enrollment:
            # Ya existe enrollment. NO es un error: si el caller queria solo
            # crear, le decimos que ya existe. Pero tambien podemos aceptar
            # el caso como "completo" implicitamente.
            return AjusteResultado(
                estudiante_carnet=carnet_str,
                estudiante_nombre=nombre,
                curso_codigo=curso.codigo,
                tipo=tipo, exito=False, dry_run=dry_run,
                error=f"Ya existe enrollment ({enrollment.id}). Use tipo 'completo' o 'diff' para ajustar.",
                nota=nota,
            )
        if not dry_run:
            from models.enrollment import ModuloEstado
            now = utcnow_naive()
            enrollment = Enrollment(
                estudiante_id=estudiante.id,
                curso_id=curso.id,
                costo_total=monto_objetivo,
                costo_matricula=0.0,
                cantidad_cuotas=6,
                total_a_pagar=monto_objetivo,
                total_pagado=monto_objetivo,
                saldo_pendiente=0.0,
                matricula_pagada=True,
                estado="activo",
                es_carga_inicial=False,
                excluir_por_cobrar=False,
                modulos=[ModuloEstado(**m) for m in MODULOS_CANONICOS],
                fecha_inscripcion=now,
            )
            await enrollment.insert()
            pagos_creados = await _crear_pagos_canonicos(enrollment.id, estudiante.id, curso.id, nota, monto_objetivo)
            return AjusteResultado(
                estudiante_carnet=carnet_str,
                estudiante_nombre=nombre,
                curso_codigo=curso.codigo,
                tipo=tipo, exito=True, dry_run=dry_run,
                antes={"enrollment_existe": False},
                despues={"enrollment_existe": True, "total_pagado": monto_objetivo, "modulos_count": 6, "pagos_count": pagos_creados},
                pagos_creados=pagos_creados,
                pagos_borrados=0,
                modulos_actualizados=6,
                nota=nota,
            )
        # dry_run
        return AjusteResultado(
            estudiante_carnet=carnet_str,
            estudiante_nombre=nombre,
            curso_codigo=curso.codigo,
            tipo=tipo, exito=True, dry_run=dry_run,
            antes={"enrollment_existe": False},
            despues={"enrollment_existe": True, "total_pagado": monto_objetivo, "modulos_count": 6, "pagos_count": 6},
            pagos_creados=0, pagos_borrados=0, modulos_actualizados=0,
            nota=nota,
        )

    # tipos diff y completo requieren enrollment existente
    if not enrollment:
        return AjusteResultado(
            estudiante_carnet=carnet_str,
            estudiante_nombre=nombre,
            curso_codigo=curso.codigo,
            tipo=tipo, exito=False, dry_run=dry_run,
            error=f"No existe enrollment para este estudiante/curso. Use tipo 'crear_enrollment'.",
            nota=nota,
        )

    # Estado actual
    antes_total = enrollment.total_pagado or 0.0
    antes_saldo = enrollment.saldo_pendiente or 0.0
    antes_modulos_count = len(enrollment.modulos)

    if not dry_run:
        # PASO 1: Borrar pagos "Ajuste" previos (idempotencia)
        pagos_borrados = await _borrar_pagos_ajuste(enrollment.id)

        # PASO 2: Actualizar modulos y enrollment
        if tipo == "completo":
            from models.enrollment import ModuloEstado
            enrollment.modulos = [ModuloEstado(**m) for m in MODULOS_CANONICOS]
            modulos_actualizados = 6
        else:  # diff
            # F-FIX-IMPUTAR-MODULOS (2026-08-11, Kevin): antes, cuando
            # monto_objetivo < 1470 (casos especiales: Adolfo 245, Anabel
            # 490, Celia 735, etc.), el codigo subia modulos[].monto_pagado
            # a m.costo (252 cada uno) Y luego sobreescribia
            # enrollment.total_pagado a monto_objetivo. Resultado:
            # modulos suman 1,470 (Pagado) pero total_pagado dice 245.
            # Inconsistencia visible en la vista Matriz.
            #
            # Fix: si monto_objetivo < 1470, imputar monto_objetivo a los
            # modulos en orden (M1 primero, hasta agotar) y dejar el resto
            # en 0/Pendiente. Asi suma(monto_pagado modulos) == total_pagado.
            modulos_actualizados = 0
            costo_total = sum(m.costo or 0 for m in enrollment.modulos)
            if monto_objetivo < costo_total - 0.01:
                # Caso especial (pago parcial / beca): imputar en orden
                restante = float(monto_objetivo)
                for m in enrollment.modulos:
                    if restante <= 0:
                        m.monto_pagado = 0.0
                        m.estado = "Pendiente"
                        modulos_actualizados += 1
                    elif restante >= (m.costo or 0):
                        m.monto_pagado = m.costo
                        m.estado = "Pagado"
                        restante -= m.costo
                        modulos_actualizados += 1
                    else:
                        # Pago parcial en el ultimo modulo que cubre
                        m.monto_pagado = round(restante, 2)
                        m.estado = "Parcial"
                        restante = 0.0
                        modulos_actualizados += 1
            else:
                # Caso normal (monto_objetivo >= costo_total): subir modulos
                # Parcial/Pendiente a Pagado
                for m in enrollment.modulos:
                    if m.estado == "Parcial" and abs(m.monto_pagado - m.costo) < 0.01:
                        m.estado = "Pagado"
                        modulos_actualizados += 1
                    elif m.estado == "Parcial" and m.monto_pagado < m.costo:
                        m.monto_pagado = m.costo
                        m.estado = "Pagado"
                        modulos_actualizados += 1
                    elif m.estado == "Pendiente":
                        m.monto_pagado = m.costo
                        m.estado = "Pagado"
                        modulos_actualizados += 1

        # PASO 3: Actualizar totales del enrollment
        enrollment.total_pagado = monto_objetivo
        enrollment.total_a_pagar = monto_objetivo
        enrollment.costo_total = monto_objetivo
        enrollment.costo_matricula = 0.0
        enrollment.saldo_pendiente = 0.0
        enrollment.matricula_pagada = True
        await enrollment.save()

        # PASO 4: Crear los pagos canonicos (o 1 pago consolidado si monto < 1470)
        pagos_creados = await _crear_pagos_canonicos(enrollment.id, estudiante.id, curso.id, nota, monto_objetivo)

        return AjusteResultado(
            estudiante_carnet=carnet_str,
            estudiante_nombre=nombre,
            curso_codigo=curso.codigo,
            tipo=tipo, exito=True, dry_run=dry_run,
            antes={"total_pagado": antes_total, "saldo_pendiente": antes_saldo, "modulos_count": antes_modulos_count},
            despues={"total_pagado": monto_objetivo, "saldo_pendiente": 0.0, "modulos_count": len(MODULOS_CANONICOS)},
            pagos_creados=pagos_creados,
            pagos_borrados=pagos_borrados,
            modulos_actualizados=modulos_actualizados,
            nota=nota,
        )

    # dry_run
    return AjusteResultado(
        estudiante_carnet=carnet_str,
        estudiante_nombre=nombre,
        curso_codigo=curso.codigo,
        tipo=tipo, exito=True, dry_run=dry_run,
        antes={"total_pagado": antes_total, "saldo_pendiente": antes_saldo, "modulos_count": antes_modulos_count},
        despues={"total_pagado": monto_objetivo, "saldo_pendiente": 0.0, "modulos_count": len(MODULOS_CANONICOS), "pagos_canonicos_a_crear": 6},
        pagos_creados=0, pagos_borrados=0, modulos_actualizados=0,
        nota=nota,
    )


@router.post(
    "/ajustar-pagos-excel",
    response_model=AjusteResponse,
    summary="F-AJUSTE-PAGOS-EXCEL v2: cuadrar pagos con planilla Excel oficial (idempotente)",
)
async def ajustar_pagos_excel(
    payload: AjusteRequest,
    current_user: User = Depends(require_superadmin),
    x_confirmar_ajuste: Optional[str] = Header(default=None),
):
    """
    Ajusta los pagos del sistema para que cuadren con la planilla Excel oficial.

    MODO DRY_RUN:
    - Si dry_run=true, NO se aplica ningun cambio. Solo se valida y se devuelve
      que se haria. Se puede llamar sin header de confirmacion.

    MODO EJECUCION:
    - Si dry_run=false, se aplican los cambios.
    - Requiere header `X-Confirmar-Ajuste: yes`.
    - Solo superadmin.

    IDEMPOTENTE (v2):
    - Antes de crear pagos nuevos, BORRA todos los pagos con marca
      'Ajuste por cuadre con Excel' del enrollment. Asi, ejecutar 2 veces
      da el mismo resultado.
    - Crea SIEMPRE los 6 pagos canonicos (5x252 + 1x210 = 1470), ya sea
      para tipo=diff, completo o crear_enrollment.

    POR QUE NO USAR /payments/by-staff:
    - El endpoint /payments/by-staff recalcula los modulos desde cero cada vez.
    - Cuando hay pagos historicos sin asociacion a `pagos_modulos`, el recalculo
      los borra silenciosamente. Verificado en ITER 2 (2026-08-10) con el caso
      de Sandra Villafani (5 pagos de 287 Bs perdidos).
    - Este endpoint hace UPDATE directo sin pasar por el recalculo.
    """
    if not payload.dry_run:
        if x_confirmar_ajuste != "yes":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Para ejecutar el ajuste real (no dry_run) se requiere header "
                    f"'{CONFIRM_HEADER}: yes'. Sin este header no se aplica ningun cambio. "
                    "Primero ejecuta con dry_run=true para previsualizar."
                ),
            )

    resultados: List[AjusteResultado] = []
    pagos_creados_total = 0
    pagos_borrados_total = 0
    modulos_actualizados_total = 0
    exitosos = 0
    fallidos = 0

    for ajuste in payload.ajustes:
        try:
            # 1) Buscar estudiante
            estudiante = await _buscar_estudiante_por_carnet(ajuste.estudiante_carnet)
            if not estudiante:
                resultados.append(AjusteResultado(
                    estudiante_carnet=ajuste.estudiante_carnet,
                    estudiante_nombre="",
                    curso_codigo=ajuste.curso_codigo,
                    tipo=ajuste.tipo, exito=False, dry_run=payload.dry_run,
                    error=f"Estudiante con carnet {ajuste.estudiante_carnet} no encontrado en el sistema",
                    nota=ajuste.nota,
                ))
                fallidos += 1
                continue

            # 2) Buscar curso
            curso = await _buscar_curso_por_codigo(ajuste.curso_codigo)
            if not curso:
                resultados.append(AjusteResultado(
                    estudiante_carnet=ajuste.estudiante_carnet,
                    estudiante_nombre=estudiante.nombre or "",
                    curso_codigo=ajuste.curso_codigo,
                    tipo=ajuste.tipo, exito=False, dry_run=payload.dry_run,
                    error=f"Curso con codigo {ajuste.curso_codigo} no encontrado en el sistema",
                    nota=ajuste.nota,
                ))
                fallidos += 1
                continue

            # 3) Buscar enrollment (siempre, para evitar duplicados en crear_enrollment)
            enrollment = await _buscar_enrollment(estudiante.id, curso.id)

            # 4) Validar tipo
            if ajuste.tipo not in ("diff", "completo", "crear_enrollment"):
                resultados.append(AjusteResultado(
                    estudiante_carnet=ajuste.estudiante_carnet,
                    estudiante_nombre=estudiante.nombre or "",
                    curso_codigo=ajuste.curso_codigo,
                    tipo=ajuste.tipo, exito=False, dry_run=payload.dry_run,
                    error=f"Tipo de ajuste invalido: '{ajuste.tipo}'. Use 'diff', 'completo' o 'crear_enrollment'.",
                    nota=ajuste.nota,
                ))
                fallidos += 1
                continue

            # 5) Aplicar
            resultado = await _aplicar_ajuste(
                estudiante, curso, enrollment,
                ajuste.tipo, ajuste.monto_objetivo, ajuste.nota,
                payload.dry_run,
            )
            resultados.append(resultado)
            pagos_creados_total += resultado.pagos_creados
            pagos_borrados_total += resultado.pagos_borrados
            modulos_actualizados_total += resultado.modulos_actualizados
            if resultado.exito:
                exitosos += 1
            else:
                fallidos += 1

        except Exception as e:
            logger.exception(f"Error procesando ajuste para {ajuste.estudiante_carnet}: {e}")
            resultados.append(AjusteResultado(
                estudiante_carnet=ajuste.estudiante_carnet,
                estudiante_nombre="",
                curso_codigo=ajuste.curso_codigo,
                tipo=ajuste.tipo, exito=False, dry_run=payload.dry_run,
                error=f"{type(e).__name__}: {str(e)}",
                nota=ajuste.nota,
            ))
            fallidos += 1

    return AjusteResponse(
        dry_run=payload.dry_run,
        ejecutor=current_user.username,
        timestamp=utcnow_naive().isoformat(),
        total_ajustes=len(payload.ajustes),
        exitosos=exitosos,
        fallidos=fallidos,
        pagos_creados_total=pagos_creados_total,
        pagos_borrados_total=pagos_borrados_total,
        modulos_actualizados_total=modulos_actualizados_total,
        resultados=resultados,
    )
