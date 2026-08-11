"""
F-AJUSTE-PAGOS-EXCEL (2026-08-10, Kevin)
=========================================

Endpoint para cuadrar los pagos del sistema con la planilla Excel oficial
de la UAGRM, considerada la fuente de verdad al 2026-08-10.

CONTEXTO:
- En la auditoría ITER 2 (2026-08-10) descubrimos que los pagos del curso
  DIPL-INVCI-2026/1 (Investigación Científica) están desfasados:
  * 50 estudiantes tienen sistema=1435 pero Excel=1470 (diferencia 35)
  * 3 estudiantes (Yolanda, Virginia, Zelma, Yovana) fueron restaurados
    con _id nuevos y ahora tienen total_pagado=0 cuando deberían tener 1470
  * Sandra Villafani (1112227) perdió sus 5 pagos originales durante una
    prueba con /payments/by-staff
  * Victor Hugo Verastegui (3067892) no tiene enrollment en el sistema

SOLUCIÓN:
- Endpoint que ajusta la base de datos directamente via Beanie/Motor,
  evitando el auto-recálculo de modulos que rompe el endpoint
  /payments/by-staff cuando se usa para ajustes retroactivos.
- Modos:
  * dry_run=true: solo muestra qué se haría, sin aplicar cambios
  * dry_run=false: aplica los cambios (UPDATE directo en enrollment +
    INSERT directo en payments collection)
- Tipos de ajuste por estudiante:
  * "diff": crear 1 pago por el diff, subir modulos[].monto_pagado
  * "completo": restaurar modulos Pagado + crear 6 pagos de los costos
  * "crear_enrollment": crear enrollment + 6 modulos Pagado + 6 pagos
- Idempotente: si se ejecuta 2 veces, no duplica pagos (verifica antes).

PROTECCIÓN:
- Solo superadmin puede ejecutarlo
- Requiere header X-Confirmar-Ajuste=yes para evitar accidentes

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


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo usuarios pueden acceder a /admin/accounting")
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Solo superadmin puede ejecutar ajustes contables")
    return current_user


class AjusteItem(BaseModel):
    estudiante_carnet: str = Field(..., description="Carnet de identidad del estudiante")
    curso_codigo: str = Field(..., description="Código del curso (ej: DIPL-INVCI-2026/1)")
    tipo: str = Field(..., description="'diff' | 'completo' | 'crear_enrollment'")
    monto_objetivo: float = Field(..., description="Monto total esperado según Excel")
    nota: Optional[str] = Field(None, description="Nota explicativa del ajuste (auditoría)")


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
    modulos_actualizados_total: int
    resultados: List[AjusteResultado]


# Estructura canon de modulos del curso DIPL-INVCI-2026/1 (fija al 2026-08-10)
# 5 modulos a 252 + 1 modulo a 210 = 1470
MODULOS_DIPL_INVCI_2026_1 = [
    {"nombre": "Módulo 1", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
    {"nombre": "Módulo 2", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
    {"nombre": "Módulo 3", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
    {"nombre": "Módulo 4", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
    {"nombre": "Módulo 5", "costo": 252.0, "monto_pagado": 252.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
    {"nombre": "Módulo 6", "costo": 210.0, "monto_pagado": 210.0, "estado": "Pagado", "estado_operacional": "Ejecutado"},
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


async def _contar_pagos_ajuste_excel(inscripcion_id: ObjectId) -> int:
    """Cuenta pagos que ya tienen el motivo 'Ajuste por cuadre con Excel' para no duplicar."""
    from beanie.operators import RegEx
    return await Payment.find({
        "inscripcion_id": inscripcion_id,
        "concepto": RegEx("Ajuste por cuadre con Excel", "i"),
    }).count()


async def _aplicar_ajuste_diff(
    estudiante: Student,
    curso: Course,
    enrollment: Enrollment,
    monto_objetivo: float,
    nota: str,
    dry_run: bool,
) -> AjusteResultado:
    """Caso: estudiante con modulos Parcial. Crear 1 pago por el diff y subir modulos."""
    inscripcion_id = enrollment.id
    antes_total = enrollment.total_pagado or 0.0
    diff = round(monto_objetivo - antes_total, 2)

    if diff <= 0:
        return AjusteResultado(
            estudiante_carnet=str(estudiante.carnet or estudiante.registro or ""),
            estudiante_nombre=estudiante.nombre or "",
            curso_codigo=curso.codigo,
            tipo="diff",
            exito=True,
            dry_run=dry_run,
            antes={"total_pagado": antes_total, "saldo_pendiente": enrollment.saldo_pendiente},
            despues={"total_pagado": antes_total, "saldo_pendiente": enrollment.saldo_pendiente},
            nota=f"Sin cambios: total_pagado={antes_total} ya alcanza monto_objetivo={monto_objetivo}",
        )

    # Verificar idempotencia: si ya existe un pago de Ajuste con este monto para este inscripcion, skip
    ajustes_previos = await _contar_pagos_ajuste_excel(inscripcion_id)
    if ajustes_previos > 0:
        return AjusteResultado(
            estudiante_carnet=str(estudiante.carnet or estudiante.registro or ""),
            estudiante_nombre=estudiante.nombre or "",
            curso_codigo=curso.codigo,
            tipo="diff",
            exito=True,
            dry_run=dry_run,
            antes={"total_pagado": antes_total, "saldo_pendiente": enrollment.saldo_pendiente},
            despues={"total_pagado": antes_total, "saldo_pendiente": enrollment.saldo_pendiente},
            nota=f"Ya existe {ajustes_previos} pago(s) 'Ajuste por cuadre con Excel' previo. Idempotente: skip.",
        )

    antes_modulos = [
        {"nombre": m.nombre, "costo": m.costo, "monto_pagado": m.monto_pagado, "estado": m.estado}
        for m in enrollment.modulos
    ]

    if not dry_run:
        # 1) Crear el pago (directo a la colección via Beanie)
        now = utcnow_naive()
        pago = Payment(
            inscripcion_id=inscripcion_id,
            estudiante_id=estudiante.id,
            curso_id=curso.id,
            concepto=f"Ajuste por cuadre con Excel - {curso.codigo}",
            detalle=f"Diferencia aplicada al enrollment {inscripcion_id}. {nota or ''}".strip(),
            metodo_pago="Ajuste Contable",
            numero_transaccion=f"AJUSTE-EXCEL-{int(now.timestamp())}",
            cantidad_pago=diff,
            estado_pago=EstadoPago.APROBADO,
            fecha_subida=now,
            fecha_verificacion=now,
            verificado_por="admin_accounting_ajuste_excel",
            comprobante_url=None,
        )
        await pago.insert()

        # 2) Subir el monto_pagado de los modulos que estén Parcial/Pendiente
        #    Distribuir el diff de forma que el último modulo Parcial suba de 245 a 252
        modulos_actualizados = 0
        restante = diff
        for m in enrollment.modulos:
            if restante <= 0.005:
                break
            # Si está Parcial y el monto_pagado < costo, subir hasta el costo
            if m.estado == "Parcial" and m.monto_pagado < m.costo:
                subir = min(m.costo - m.monto_pagado, restante)
                m.monto_pagado = round(m.monto_pagado + subir, 2)
                if abs(m.monto_pagado - m.costo) < 0.01:
                    m.estado = "Pagado"
                restante = round(restante - subir, 2)
                modulos_actualizados += 1
            elif m.estado == "Pendiente" and m.monto_pagado == 0 and restante >= m.costo:
                # Si hay un modulo Pendiente y alcanza para pagarlo completo
                m.monto_pagado = m.costo
                m.estado = "Pagado"
                restante = round(restante - m.costo, 2)
                modulos_actualizados += 1

        # 3) Actualizar totales del enrollment
        enrollment.total_pagado = round(antes_total + diff, 2)
        enrollment.saldo_pendiente = max(0.0, round((enrollment.total_a_pagar or 0.0) - enrollment.total_pagado, 2))
        await enrollment.save()

    despues_total = round(antes_total + diff, 2) if not dry_run else antes_total
    despues_saldo = max(0.0, round((enrollment.total_a_pagar or 0.0) - despues_total, 2)) if not dry_run else enrollment.saldo_pendiente

    return AjusteResultado(
        estudiante_carnet=str(estudiante.carnet or estudiante.registro or ""),
        estudiante_nombre=estudiante.nombre or "",
        curso_codigo=curso.codigo,
        tipo="diff",
        exito=True,
        dry_run=dry_run,
        antes={"total_pagado": antes_total, "saldo_pendiente": enrollment.saldo_pendiente, "modulos": antes_modulos},
        despues={"total_pagado": despues_total, "saldo_pendiente": despues_saldo},
        pagos_creados=0 if dry_run else 1,
        modulos_actualizados=0 if dry_run else modulos_actualizados,
        nota=nota,
    )


async def _aplicar_ajuste_completo(
    estudiante: Student,
    curso: Course,
    enrollment: Enrollment,
    monto_objetivo: float,
    nota: str,
    dry_run: bool,
) -> AjusteResultado:
    """Caso: estudiante con modulos Pendiente o modulos=[]. Restaurar modulos Pagado y crear pagos."""
    inscripcion_id = enrollment.id
    antes_total = enrollment.total_pagado or 0.0
    antes_saldo = enrollment.saldo_pendiente or 0.0
    antes_modulos_count = len(enrollment.modulos)

    # Determinar qué modulos restaurar
    modulos_a_crear = []
    for m_def in MODULOS_DIPL_INVCI_2026_1:
        modulos_a_crear.append({
            "nombre": m_def["nombre"],
            "costo": m_def["costo"],
            "monto_pagado": m_def["monto_pagado"],
            "estado": m_def["estado"],
            "estado_operacional": m_def["estado_operacional"],
            "estado_academico": "Cursando",
        })

    # Verificar idempotencia
    ajustes_previos = await _contar_pagos_ajuste_excel(inscripcion_id)
    pagos_a_crear_count = 0
    if ajustes_previos == 0 and not dry_run:
        pagos_a_crear_count = 6  # 6 pagos, 1 por modulo

    if not dry_run:
        # 1) Reemplazar la lista de modulos
        from models.enrollment import ModuloEstado
        enrollment.modulos = [ModuloEstado(**m) for m in modulos_a_crear]

        # 2) Actualizar totales
        enrollment.total_pagado = monto_objetivo
        enrollment.total_a_pagar = monto_objetivo
        enrollment.costo_total = monto_objetivo
        enrollment.costo_matricula = 0.0
        enrollment.saldo_pendiente = 0.0
        enrollment.matricula_pagada = True
        await enrollment.save()

        # 3) Crear 6 pagos (1 por modulo) si no se han creado ya
        if ajustes_previos == 0:
            now = utcnow_naive()
            for i, m in enumerate(modulos_a_crear, 1):
                pago = Payment(
                    inscripcion_id=inscripcion_id,
                    estudiante_id=estudiante.id,
                    curso_id=curso.id,
                    concepto=f"Ajuste por cuadre con Excel - {curso.codigo} - {m['nombre']}",
                    detalle=f"Restauración de pago del {m['nombre']} (costo Bs {m['costo']}). {nota or ''}".strip(),
                    metodo_pago="Ajuste Contable",
                    numero_transaccion=f"AJUSTE-EXCEL-M{i}-{int(now.timestamp())}",
                    cantidad_pago=m["costo"],
                    estado_pago=EstadoPago.APROBADO,
                    fecha_subida=now,
                    fecha_verificacion=now,
                    verificado_por="admin_accounting_ajuste_excel",
                    comprobante_url=None,
                )
                await pago.insert()

    return AjusteResultado(
        estudiante_carnet=str(estudiante.carnet or estudiante.registro or ""),
        estudiante_nombre=estudiante.nombre or "",
        curso_codigo=curso.codigo,
        tipo="completo",
        exito=True,
        dry_run=dry_run,
        antes={"total_pagado": antes_total, "saldo_pendiente": antes_saldo, "modulos_count": antes_modulos_count},
        despues={"total_pagado": monto_objetivo, "saldo_pendiente": 0.0, "modulos_count": 6},
        pagos_creados=0 if dry_run else pagos_a_crear_count,
        modulos_actualizados=0 if dry_run else 6,
        nota=nota,
    )


async def _aplicar_crear_enrollment(
    estudiante: Student,
    curso: Course,
    monto_objetivo: float,
    nota: str,
    dry_run: bool,
) -> AjusteResultado:
    """Caso: estudiante sin enrollment. Crear enrollment + modulos + pagos."""
    carnet = str(estudiante.carnet or estudiante.registro or "")

    if not dry_run:
        # 1) Crear enrollment con los 6 modulos Pagado
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
            estado="activo",  # EstadoInscripcion.ACTIVO
            es_carga_inicial=False,
            excluir_por_cobrar=False,
            modulos=[ModuloEstado(**m) for m in MODULOS_DIPL_INVCI_2026_1],
            fecha_inscripcion=now,
        )
        await enrollment.insert()
        inscripcion_id = enrollment.id

        # 2) Crear 6 pagos
        for i, m in enumerate(MODULOS_DIPL_INVCI_2026_1, 1):
            pago = Payment(
                inscripcion_id=inscripcion_id,
                estudiante_id=estudiante.id,
                curso_id=curso.id,
                concepto=f"Ajuste por cuadre con Excel - {curso.codigo} - {m['nombre']}",
                detalle=f"Creación de enrollment y pago del {m['nombre']} (costo Bs {m['costo']}). {nota or ''}".strip(),
                metodo_pago="Ajuste Contable",
                numero_transaccion=f"AJUSTE-EXCEL-M{i}-{int(now.timestamp())}",
                cantidad_pago=m["costo"],
                estado_pago=EstadoPago.APROBADO,
                fecha_subida=now,
                fecha_verificacion=now,
                verificado_por="admin_accounting_ajuste_excel",
                comprobante_url=None,
            )
            await pago.insert()

    return AjusteResultado(
        estudiante_carnet=carnet,
        estudiante_nombre=estudiante.nombre or "",
        curso_codigo=curso.codigo,
        tipo="crear_enrollment",
        exito=True,
        dry_run=dry_run,
        antes={"enrollment_existe": False},
        despues={"enrollment_existe": True, "total_pagado": monto_objetivo, "modulos_count": 6, "pagos_count": 6},
        pagos_creados=0 if dry_run else 6,
        modulos_actualizados=0 if dry_run else 6,
        nota=nota,
    )


@router.post(
    "/ajustar-pagos-excel",
    response_model=AjusteResponse,
    summary="F-AJUSTE-PAGOS-EXCEL: cuadrar pagos con planilla Excel oficial (solo superadmin)",
)
async def ajustar_pagos_excel(
    payload: AjusteRequest,
    current_user: User = Depends(require_superadmin),
    x_confirmar_ajuste: Optional[str] = Header(default=None),
):
    """
    Ajusta los pagos del sistema para que cuadren con la planilla Excel oficial.

    MODO DRY_RUN:
    - Si dry_run=true, NO se aplica ningún cambio. Solo se valida y se devuelve
      qué se haría. Se puede llamar sin header de confirmación.

    MODO EJECUCIÓN:
    - Si dry_run=false, se aplican los cambios.
    - Requiere header `X-Confirmar-Ajuste: yes`.
    - Solo superadmin.

    POR QUÉ NO USAR /payments/by-staff:
    - El endpoint /payments/by-staff recalcula los modulos desde cero cada vez.
    - Cuando hay pagos históricos sin asociacion a `pagos_modulos`, el recálculo
      los borra silenciosamente. Verificado en ITER 2 (2026-08-10) con el caso
      de Sandra Villafani (5 pagos de 287 Bs perdidos).
    - Este endpoint hace UPDATE directo sin pasar por el recálculo.
    """
    # Si NO es dry_run, exigir header de confirmación
    if not payload.dry_run:
        if x_confirmar_ajuste != "yes":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Para ejecutar el ajuste real (no dry_run) se requiere header "
                    f"'{CONFIRM_HEADER}: yes'. Sin este header no se aplica ningún cambio. "
                    "Primero ejecuta con dry_run=true para previsualizar."
                ),
            )

    resultados: List[AjusteResultado] = []
    pagos_creados_total = 0
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
                    tipo=ajuste.tipo,
                    exito=False,
                    dry_run=payload.dry_run,
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
                    tipo=ajuste.tipo,
                    exito=False,
                    dry_run=payload.dry_run,
                    error=f"Curso con código {ajuste.curso_codigo} no encontrado en el sistema",
                    nota=ajuste.nota,
                ))
                fallidos += 1
                continue

            # 3) Buscar enrollment
            enrollment = await _buscar_enrollment(estudiante.id, curso.id)

            # 4) Aplicar el tipo de ajuste correspondiente
            if ajuste.tipo == "crear_enrollment":
                if enrollment:
                    resultados.append(AjusteResultado(
                        estudiante_carnet=ajuste.estudiante_carnet,
                        estudiante_nombre=estudiante.nombre or "",
                        curso_codigo=ajuste.curso_codigo,
                        tipo=ajuste.tipo,
                        exito=False,
                        dry_run=payload.dry_run,
                        error=f"Ya existe un enrollment para este estudiante/curso (id={enrollment.id}). No se puede crear.",
                        nota=ajuste.nota,
                    ))
                    fallidos += 1
                    continue
                resultado = await _aplicar_crear_enrollment(estudiante, curso, ajuste.monto_objetivo, ajuste.nota, payload.dry_run)
            elif ajuste.tipo in ("diff", "completo"):
                if not enrollment:
                    resultados.append(AjusteResultado(
                        estudiante_carnet=ajuste.estudiante_carnet,
                        estudiante_nombre=estudiante.nombre or "",
                        curso_codigo=ajuste.curso_codigo,
                        tipo=ajuste.tipo,
                        exito=False,
                        dry_run=payload.dry_run,
                        error=f"No existe enrollment para este estudiante/curso. Use tipo 'crear_enrollment'.",
                        nota=ajuste.nota,
                    ))
                    fallidos += 1
                    continue

                if ajuste.tipo == "diff":
                    resultado = await _aplicar_ajuste_diff(estudiante, curso, enrollment, ajuste.monto_objetivo, ajuste.nota, payload.dry_run)
                else:  # completo
                    resultado = await _aplicar_ajuste_completo(estudiante, curso, enrollment, ajuste.monto_objetivo, ajuste.nota, payload.dry_run)
            else:
                resultados.append(AjusteResultado(
                    estudiante_carnet=ajuste.estudiante_carnet,
                    estudiante_nombre=estudiante.nombre or "",
                    curso_codigo=ajuste.curso_codigo,
                    tipo=ajuste.tipo,
                    exito=False,
                    dry_run=payload.dry_run,
                    error=f"Tipo de ajuste inválido: '{ajuste.tipo}'. Use 'diff', 'completo' o 'crear_enrollment'.",
                    nota=ajuste.nota,
                ))
                fallidos += 1
                continue

            resultados.append(resultado)
            pagos_creados_total += resultado.pagos_creados
            modulos_actualizados_total += resultado.modulos_actualizados
            exitosos += 1

        except Exception as e:
            logger.exception(f"Error procesando ajuste para {ajuste.estudiante_carnet}: {e}")
            resultados.append(AjusteResultado(
                estudiante_carnet=ajuste.estudiante_carnet,
                estudiante_nombre="",
                curso_codigo=ajuste.curso_codigo,
                tipo=ajuste.tipo,
                exito=False,
                dry_run=payload.dry_run,
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
        modulos_actualizados_total=modulos_actualizados_total,
        resultados=resultados,
    )
