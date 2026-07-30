"""
Servicio de Pagos (Payments)
============================

Lógica de negocio para pagos, incluyendo soporte de métodos en Caja,
Auditoría y Algoritmo de Prorrateo.
"""

from typing import List, Optional
from collections import defaultdict
import asyncio
from datetime import datetime, timedelta
from models.payment import Payment
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.discount import Discount
from models.enums import EstadoPago, EstadoInscripcion
from schemas.payment import PaymentCreate
from beanie import PydanticObjectId
from beanie.operators import In, Or
from beanie.exceptions import RevisionIdWasChanged
from services import enrollment_service
from core.timezone_utils import utcnow_naive, to_bolivia_time

# ISSUE-P-REVERSION: ventana en la que el banco puede revertir una transferencia ya aprobada
VENTANA_REVERSION_HORAS = 48


def _calcular_en_ventana_reversion(payment: Payment) -> bool:
    """
    True si el pago fue aprobado por transferencia y todavía está dentro de las
    48h en que el banco podría revertir la operación. Es un valor calculado en
    tiempo de respuesta (depende de "ahora"), nunca se persiste en base de datos.
    """
    if payment.estado_pago != EstadoPago.APROBADO:
        return False
    if "transferencia" not in (payment.metodo_pago or "").lower():
        return False
    if not payment.fecha_verificacion:
        return False
    limite = payment.fecha_verificacion + timedelta(hours=VENTANA_REVERSION_HORAS)
    return utcnow_naive() < limite

# ========================================================================
# MOTOR DE AUDITORÍA FINANCIERA
# ========================================================================
async def _registrar_auditoria_financiera(
    accion: str,
    payment_id: PydanticObjectId,
    estudiante_id: PydanticObjectId,
    monto: float,
    admin_username: str,
    detalles: str
):
    """
    Función auxiliar para registrar los movimientos financieros en un log inmutable.
    """
    try:
        print(
            f"[AUDIT TRAIL] [{utcnow_naive()}] ACCIÓN: {accion} | "
            f"ADMIN: {admin_username} | PAGO_ID: {payment_id} | "
            f"ESTUDIANTE_ID: {estudiante_id} | MONTO: Bs. {monto} | "
            f"DETALLE: {detalles}"
        )
    except Exception as e:
        print(f"Error guardando auditoría: {str(e)}")


async def enrich_payment_with_details(payment: Payment) -> dict:
    payment_dict = payment.model_dump(by_alias=True)

    student = await Student.get(payment.estudiante_id)
    nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"

    fecha = to_bolivia_time(payment.fecha_subida)
    created_at_bolivia = to_bolivia_time(payment.created_at)
    updated_at_bolivia = to_bolivia_time(payment.updated_at)
    
    total_cuotas = 0
    try:
        enrollment = await enrollment_service.get_enrollment(payment.inscripcion_id)
        if enrollment:
            total_cuotas = enrollment.cantidad_cuotas
    except:
        total_cuotas = 0
    
    payment_dict.update({
        "nombre_estudiante": nombre_estudiante,
        "fecha": fecha,
        "moneda": "Bs",
        "monto": payment.cantidad_pago,
        "estado": payment.estado_pago.value if payment.estado_pago else "",
        "total_cuotas": total_cuotas,
        "created_at": created_at_bolivia,
        "updated_at": updated_at_bolivia,
        "en_ventana_reversion": _calcular_en_ventana_reversion(payment)  # ISSUE-P-REVERSION
    })
    
    return payment_dict


async def enrich_payments_with_details_bulk(payments: List[Payment]) -> List[dict]:
    """
    Enriquece una lista de pagos con informacion del estudiante y enrollment.

    F-COBRANZA-031 (2026-07-22): acepta tanto objetos Payment como dicts
    (algunos endpoints como /reportes/caja convierten a dict antes de llamar).
    Antes solo aceptaba objetos, lo que causaba 500 en /reportes/caja
    cuando le pasaba dicts.
    """
    if not payments:
        return []

    # F-COBRANZA-031: detectar si vienen dicts u objetos
    def _get(p, key, default=None):
        if isinstance(p, dict):
            return p.get(key, default)
        return getattr(p, key, default)

    def _set_estado_value(estado):
        if hasattr(estado, "value"):
            return estado.value
        return estado or ""

    student_ids = list({_get(p, "estudiante_id") for p in payments if _get(p, "estudiante_id")})
    enrollment_ids = list({_get(p, "inscripcion_id") for p in payments if _get(p, "inscripcion_id")})

    students_task = Student.find(In(Student.id, student_ids)).to_list()
    enrollments_task = Enrollment.find(In(Enrollment.id, enrollment_ids)).to_list()

    students, enrollments = await asyncio.gather(students_task, enrollments_task)

    students_map = {s.id: s for s in students}
    enrollments_map = {e.id: e for e in enrollments}

    enriched_list = []
    for payment in payments:
        # Si ya es dict, usarlo; sino, volcarlo a dict
        if isinstance(payment, dict):
            p_dict = dict(payment)
        else:
            p_dict = payment.model_dump(by_alias=True)

        # F-075-FIX-7 (2026-07-23): convertir PydanticObjectId a string para
        # que se pueda serializar a JSON. Sin esto, FastAPI lanza 500 porque
        # no sabe serializar PydanticObjectId.
        from beanie import PydanticObjectId
        for key, val in list(p_dict.items()):
            if isinstance(val, PydanticObjectId):
                p_dict[key] = str(val)

        estudiante_id = _get(payment, "estudiante_id")
        inscripcion_id = _get(payment, "inscripcion_id")

        student = students_map.get(estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"
        # F-COBRANZA-036 (2026-07-22): incluir C.I. y registro del estudiante.
        # Pedido Lic. Sandra Zabala: "Adicionar la columna con los datos de los
        # C.I. de los estudiantes" en el reporte de caja. C.I. = carnet_identidad.
        # Si no tiene C.I., caemos al registro universitario.
        carnet_identidad = (student.carnet_identidad if student and getattr(student, "carnet_identidad", None) else None) or \
                           (student.registro if student and getattr(student, "registro", None) else None) or ""

        enrollment = enrollments_map.get(inscripcion_id)
        total_cuotas = enrollment.cantidad_cuotas if enrollment else 0

        p_dict.update({
            "nombre_estudiante": nombre_estudiante,
            "fecha": to_bolivia_time(_get(payment, "fecha_subida")),
            "moneda": "Bs",
            "monto": _get(payment, "cantidad_pago"),
            "estado": _set_estado_value(_get(payment, "estado_pago")),
            "total_cuotas": total_cuotas,
            "created_at": to_bolivia_time(_get(payment, "created_at")),
            "updated_at": to_bolivia_time(_get(payment, "updated_at")),
            "en_ventana_reversion": _calcular_en_ventana_reversion(payment) if not isinstance(payment, dict) else False,
            # F-COBRANZA-020: incluir el detalle en el dict enriquecido
            "detalle": _get(payment, "detalle", None),
            # F-COBRANZA-036: CI/registro del estudiante (Sandra - reporte caja)
            "estudiante_ci": carnet_identidad,
            # F-COBRANZA-037 (2026-07-22): columnas Débitos/Créditos + tipo
            # movimiento en el reporte de caja. Sandra Zabala pidio ver
            # claramente la diferencia entre PAGO (credito) y ANULACION/
            # RECHAZO (debito), sin que los anulados se sumen al total.
            "tipo_movimiento": (
                "ANULACION" if _set_estado_value(_get(payment, "estado_pago")) == "anulado" else
                "RECHAZO"  if _set_estado_value(_get(payment, "estado_pago")) == "rechazado" else
                "PAGO"
            ),
            "debito": abs(_get(payment, "cantidad_pago", 0)) if _set_estado_value(_get(payment, "estado_pago")) in ("anulado", "rechazado") else 0.0,
            "credito": abs(_get(payment, "cantidad_pago", 0)) if _set_estado_value(_get(payment, "estado_pago")) == "aprobado" else 0.0,
        })
        enriched_list.append(p_dict)

    return enriched_list


async def get_next_pending_payment(enrollment_id: PydanticObjectId) -> dict:
    enrollment = await enrollment_service.get_enrollment(enrollment_id)
    if not enrollment:
        raise ValueError("Inscripción no encontrada")

    pagos_activos = await Payment.find(
        Payment.inscripcion_id == enrollment_id,
        Or(
            Payment.estado_pago == EstadoPago.PENDIENTE,
            Payment.estado_pago == EstadoPago.APROBADO
        )
    ).to_list()

    conceptos_cubiertos = {
        (p.concepto, p.numero_cuota) for p in pagos_activos
    }

    if enrollment.costo_matricula > 0:
        if ("Matrícula", None) not in conceptos_cubiertos:
            return {
                "concepto": "Matrícula",
                "numero_cuota": None,
                "monto_sugerido": enrollment.costo_matricula
            }

    if enrollment.cantidad_cuotas > 0:
        monto_cuota = enrollment.calcular_monto_cuota()
        for i in range(1, enrollment.cantidad_cuotas + 1):
            if (f"Cuota {i}", i) not in conceptos_cubiertos:
                return {
                    "concepto": f"Cuota {i}",
                    "numero_cuota": i,
                    "monto_sugerido": monto_cuota
                }

    return None


# ========================================================================
# F-COBRANZA-015 (2026-07-21): Glosa detallada por módulo(s) específico(s)
# ========================================================================
# Joel: "los pagos deben ser detallados, tipo 'Pago Módulo 1' o 'Módulo 1, 2, 3'".
# Antes, el `concepto` decía "Cuota 5" (genérico). Ahora previsualiza el cascading
# del pago actual y construye una glosa que nombra los módulos específicos:
#   - Solo matrícula              -> "Matrícula"
#   - Solo un módulo completo     -> "Pago Módulo 1"
#   - Varios módulos completos    -> "Pago Módulos 1, 2, 3"
#   - Matrícula + módulos         -> "Matrícula + Pago Módulos 1, 2"
#   - Un módulo parcial           -> "Pago Módulo 3 (parcial, Bs X de Bs Y)"
#   - Pago excesivo sobre saldo   -> "Pago completo: Matrícula + Módulos 1, 2, 3 (sobrante Bs Z)"


# Set de conceptos GENÉRICOS que el frontend puede mandar como placeholder
# antes de que el usuario los edite. Si el `concepto` entrante es uno de estos
# (o vacío), lo sobrescribimos con la glosa detallada calculada. Si es algo
# específico (caso operador de Caja, o un texto custom), lo respetamos.
#
# Bug detectado en producción 2026-07-22: el PaymentForm.svelte siempre manda
# `concepto = 'Módulo'` o `concepto = 'Matrícula'` como placeholders
# autocompletados al seleccionar el curso. El backend respetaba ese valor y
# todos los pagos quedaban con glosa "Módulo" genérica, sin detalle de qué
# módulo se pagaba. Kevin lo detectó: "tu correecion de el monto ya lo
# subiste porque no lo veo".
_CONCEPTOS_GENERICOS_PLACEHOLDER = frozenset({
    "", "matrícula", "matricula", "módulo", "modulo",
})


def _es_concepto_generico_placeholder(concepto: str | None) -> bool:
    """True si el concepto entrante es un placeholder genérico que el
    frontend autocompletó y debe ser reemplazado por la glosa detallada."""
    if not concepto:
        return True
    return concepto.strip().lower() in _CONCEPTOS_GENERICOS_PLACEHOLDER


def _generar_glosa_detalle(
    enrollment,
    monto_pago: float,
    pagos_aprobados_existentes: list,
) -> tuple:
    """
    Previsualiza el cascading del pago en memoria y construye la glosa detallada.

    F-COBRANZA-018 (2026-07-22): la decisión de si este pago cubre la
    matrícula o va a módulos NO se basa en `enrollment.matricula_pagada`
    (que puede estar desincronizado por migraciones o por datos históricos).
    Se basa en el HISTORIAL de pagos aprobados: si la suma NO alcanza el
    costo de la matrícula, este pago es para la matrícula. Robusto contra
    datos desincronizados y permite re-migración retroactiva correcta.

    Returns:
        tuple (concepto, numero_cuota) listo para asignar al Payment.
    """
    # 1. Calcular dinero aprobado histórico (lo que ya se acreditó).
    # F-COBRANZA-018: la decisión de si este pago cubre la matrícula o va
    # a módulos se basa en DOS señales concordantes:
    #   (a) `enrollment.matricula_pagada` (estado oficial del enrollment)
    #   (b) suma de pagos_aprobados_existentes >= costo_matricula
    # Si CUALQUIERA de las dos señales dice "ya pagada", el pago va a
    # módulos. Si AMBAS dicen "no pagada", va a matrícula. Esto es robusto
    # contra datos históricos desincronizados en una sola señal.
    dinero_antes = sum(p.cantidad_pago for p in pagos_aprobados_existentes)
    matricula_ya_cubierta_por_pagos_previos = dinero_antes >= (enrollment.costo_matricula or 0)
    matricula_ya_pagada_segun_enrollment = bool(getattr(enrollment, "matricula_pagada", False))
    matricula_ya_cubierta = matricula_ya_cubierta_por_pagos_previos or matricula_ya_pagada_segun_enrollment

    # F-COBRANZA-018 fix (2026-07-22): para la cascada de módulos, el dinero
    # que importa es el que ya fue a MÓDULOS, NO la matrícula. Si la
    # matrícula ya está cubierta, restamos su costo del dinero_antes para
    # no contaminar el tanque con dinero que ya se asignó a matrícula.
    # Antes: dinero_antes incluía la matrícula → el segundo pago de 300
    # Bs (módulo 1 cuesta 294) erróneamente se marcaba como cubriendo
    # módulos 1, 2 y 3 parcial. Después: solo cubre módulo 1.
    if matricula_ya_cubierta:
        dinero_aplicado_a_modulos_antes = max(0, dinero_antes - (enrollment.costo_matricula or 0))
    else:
        dinero_aplicado_a_modulos_antes = 0

    tanque = round(dinero_aplicado_a_modulos_antes + monto_pago, 2)
    matricula_cubierta_por_este_pago = False
    modulos_cubiertos: list = []  # cada item: (numero_o_nombre, tipo='completo'|'parcial', monto_pagado, costo_total)
    sobrante = 0.0

    if not matricula_ya_cubierta:
        if (dinero_antes + monto_pago) >= (enrollment.costo_matricula or 0):
            # El tanque solo se reduce por el costo de matrícula DESPUÉS de
            # gastar lo que ya se tenía. Si el dinero_antes + monto_pago
            # alcanza, cubrimos matrícula completa y sobrante va a módulos.
            tanque = round((dinero_antes + monto_pago) - (enrollment.costo_matricula or 0), 2)
            matricula_cubierta_por_este_pago = True
        else:
            # No alcanza para matrícula → no se computa
            # F-COBRANZA-020: retornamos (concepto, detalle, numero_cuota)
            return ("Matrícula (pago parcial)", f"Faltan {((enrollment.costo_matricula or 0) - tanque):.0f} Bs para completar la matrícula", None)

    # 2. Cascada sobre los módulos
    for idx, mod in enumerate(enrollment.modulos, start=1):
        if tanque <= 0.01:
            break
        costo_modulo = round(mod.costo, 2)
        if tanque >= costo_modulo:
            modulos_cubiertos.append((idx, "completo", costo_modulo, costo_modulo))
            tanque = round(tanque - costo_modulo, 2)
        else:
            # Pago parcial: se vierte el remanente en este módulo
            modulos_cubiertos.append((idx, "parcial", tanque, costo_modulo))
            tanque = 0.0

    # 3. Si queda dinero después de todo, es sobrante (no debería pasar, pero por si acaso)
    if tanque > 0.01:
        sobrante = tanque

    # 4. Construir la glosa
    partes = []
    numero_cuota_final = None

    # F-COBRANZA-020 (2026-07-22): ahora retornamos TRES campos:
    #   - concepto: resumen CONTABLE (para agrupación/reportes)
    #   - detalle:  desglose para justificación/auditoría
    #   - numero_cuota: el primer módulo cubierto completo
    #
    # Ejemplo: pago de 300 Bs que cubre módulo 1 (294) + parcial módulo 2 (6):
    #   concepto: "Pago Módulos 1, 2"      ← para Excel/reporte contable
    #   detalle:  "Módulo 1: 294 Bs (completo); Módulo 2: 6 Bs (parcial de 294 Bs)"  ← justificación
    #
    # Kevin: "se podria poner como un total que junte a los dos por temas contables
    # y que este desglose sea ya un detalle de justificacion tipo"
    concepto_partes = []
    detalle_partes = []

    if matricula_cubierta_por_este_pago:
        concepto_partes.append("Matrícula")
        # Si también cubre módulos, lo indicamos en el detalle
        if modulos_cubiertos:
            detalle_partes.append("Matrícula completa")

    if modulos_cubiertos:
        indices_completos = [m[0] for m in modulos_cubiertos if m[1] == "completo"]
        indices_parciales = [m for m in modulos_cubiertos if m[1] == "parcial"]

        # --- Construir CONCEPTO (resumen contable) ---
        if indices_completos and not indices_parciales:
            if len(indices_completos) == 1:
                concepto_partes.append(f"Pago Módulo {indices_completos[0]}")
            else:
                concepto_partes.append(
                    f"Pago Módulos {', '.join(str(i) for i in indices_completos)}"
                )
        elif indices_parciales and not indices_completos:
            # Solo parcial(es): el módulo parcialmente cubierto aparece en concepto
            if len(indices_parciales) == 1:
                idx = indices_parciales[0][0]
                concepto_partes.append(f"Pago Módulo {idx} (parcial)")
            else:
                concepto_partes.append(
                    f"Pago parcial Módulos {', '.join(str(m[0]) for m in indices_parciales)}"
                )
        else:
            # Mixto: completos + parciales (caso matricula + modulos)
            # Para el concepto, juntamos todos los índices cubiertos.
            todos = sorted(indices_completos + [m[0] for m in indices_parciales])
            if len(todos) == 1:
                concepto_partes.append(f"Pago Módulo {todos[0]}")
            else:
                concepto_partes.append(f"Pago Módulos {', '.join(str(i) for i in todos)}")

        # --- Construir DETALLE (desglose con montos) ---
        for m in modulos_cubiertos:
            idx, tipo, monto_p, costo = m
            if tipo == "completo":
                detalle_partes.append(
                    f"Módulo {idx}: {monto_p:.0f} Bs (completo)"
                )
            else:  # parcial
                detalle_partes.append(
                    f"Módulo {idx}: {monto_p:.0f} Bs (parcial de {costo:.0f} Bs)"
                )

    # numero_cuota: el primer módulo cubierto completo (si hay), si no None
    if modulos_cubiertos:
        completos = [m[0] for m in modulos_cubiertos if m[1] == "completo"]
        if completos:
            numero_cuota_final = completos[0]
    elif matricula_cubierta_por_este_pago and not modulos_cubiertos:
        numero_cuota_final = None  # solo matrícula

    # Si hay sobrante, agregarlo al detalle
    if sobrante > 0.01:
        detalle_partes.append(f"Sobrante: {sobrante:.0f} Bs")

    concepto = " + ".join(concepto_partes) if concepto_partes else "Pago sin detalle"
    detalle = "; ".join(detalle_partes) if detalle_partes else None

    return (concepto, detalle, numero_cuota_final)


async def create_payment(
    payment_in: PaymentCreate,
    student_id: PydanticObjectId,
    auto_approve: bool = True,
    approved_by: Optional[str] = None,
    skip_ownership_check: bool = False,
    subido_por: Optional[str] = None
) -> Payment:
    """
    Crear un nuevo pago. Soporta pagos digitales o pagos físicos en CAJA (sin voucher).

    Args:
        payment_in: datos del pago (validated schema).
        student_id: ObjectId del estudiante dueño de la inscripción.
        auto_approve: si True (default), el pago nace APROBADO. Esto es F-COBRANZA-004
            (auto-aprobación al subir comprobante). El coord. financiero puede RECHAZAR
            después si el comprobante es inválido.
        approved_by: si se provee (caso staff via by-staff endpoint), se usa como
            `verificado_por` en lugar del genérico "SISTEMA (auto-aprobación)".
            Útil para auditoría: deja claro quién aprobó el pago.
        skip_ownership_check: si True, NO valida que la inscripción pertenezca al
            estudiante. Solo debe pasarse True cuando el caller es STAFF autorizado
            (cobranza/admin/superadmin) que registra un pago en nombre de un
            estudiante. F-COBRANZA-034 (2026-07-22): bug encontrado por Lic. Sandra
            Zabala — el check enrollment.estudiante_id != student_id fallaba siempre
            en el endpoint /payments/by-staff porque estudiante_id llegaba como
            string del Form, mientras enrollment.estudiante_id es PydanticObjectId.
            La comparación siempre era True, bloqueando a cobranza para registrar
            pagos en nombre de cualquier estudiante.
        subido_por: F-087 (2026-07-28). Indica quién subió el comprobante:
            "estudiante" (cuando el propio estudiante usa /payments/),
            "encargado" (cuando cobranza/admin usa /payments/{id}/upload-by-encargado),
            o None (pagos antiguos previos al feature, la UI muestra "—").

    Raises:
        ValueError: si la inscripción no existe, o si skip_ownership_check=False
            y la inscripción no pertenece al estudiante.
    """
    enrollment = await Enrollment.get(payment_in.inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {payment_in.inscripcion_id} no encontrada")

    if not skip_ownership_check and enrollment.estudiante_id != student_id:
        raise ValueError(
            "No puedes crear un pago para una inscripción que no te pertenece"
        )

    if payment_in.metodo_pago != "Caja" and payment_in.numero_transaccion:
        # F-PAGO-RESUB-ANULADO (2026-07-30): permitir re-subir el comprobante si
        # el pago anterior está ANULADO o RECHAZADO. El índice único parcial
        # uniq_numero_transaccion_activo (en models/payment.py) ya excluye
        # estos estados, así que la BD acepta el insert.
        #
        # Caso real (2026-07-30): Luis Fernando Lopez Zenteno — comprobante
        # 5603099807 ANULADO. Necesita re-subir el pago. Antes este código
        # bloqueaba con "comprobantes duplicados" incluso para comprobantes
        # anulados, lo cual no tiene sentido: si el pago se anuló, el número
        # de transacción quedó liberado.
        existing_transaction = await Payment.find_one(
            Payment.numero_transaccion == payment_in.numero_transaccion,
            Payment.estado_pago.in_([EstadoPago.APROBADO, EstadoPago.PENDIENTE])
        )

        if existing_transaction:
            raise ValueError(
                f"El número de transacción bancaria '{payment_in.numero_transaccion}' ya "
                f"ha sido registrado en el sistema y se encuentra '{existing_transaction.estado_pago}'. "
                "No se permiten comprobantes duplicados."
            )
    
    next_payment = await get_next_pending_payment(payment_in.inscripcion_id)
    if not next_payment:
         raise ValueError("Esta inscripción ya tiene todos los pagos en proceso o aprobados.")

    monto_real = payment_in.monto_comprobante if payment_in.monto_comprobante else payment_in.cantidad_pago

    # F-COBRANZA-015 (2026-07-21): generar glosa DETALLADA por módulo(s) en vez
    # de "Cuota N" genérico. Joel: "los pagos deben ser detallados, tipo
    # 'Pago Módulo 1' o 'Módulo 1, 2, 3'". Previsualizamos el cascading para
    # saber qué módulos cubre este pago.
    #
    # Si el frontend manda un concepto GENÉRICO (los placeholders por defecto
    # del PaymentForm.svelte: "Matrícula" o "Módulo"), lo sobrescribimos con
    # la glosa detallada calculada. Si el usuario forzó un concepto específico
    # (caso de "Caja" o un valor distinto a los genéricos), lo respetamos.
    if payment_in.concepto and not _es_concepto_generico_placeholder(payment_in.concepto):
        # El usuario forzó un concepto específico (caso "Caja", carga manual)
        concepto_final = payment_in.concepto
        detalle_final = None  # F-COBRANZA-034 (2026-07-22): inicializar para que no explote
                              # abajo si el caller pasa concepto especifico. Bug destapado
                              # al fixear F-034: el check 'no te pertenece' fallaba antes
                              # y nunca llegabamos aca con concepto especifico.
        cuota_final = payment_in.numero_cuota if payment_in.numero_cuota else next_payment["numero_cuota"]
    else:
        # Generar glosa automática (placeholder genérico o vacío)
        pagos_aprobados_pre = await Payment.find(
            Payment.inscripcion_id == payment_in.inscripcion_id,
            Payment.estado_pago == EstadoPago.APROBADO
        ).to_list()
        # F-COBRANZA-020: ahora retorna (concepto, detalle, numero_cuota)
        concepto_final, detalle_final, cuota_final = _generar_glosa_detalle(
            enrollment, monto_real, pagos_aprobados_pre
        )

    # AUDITORÍA (ALTO #4): sin este control, un pago (aún PENDIENTE, antes de
    # que cobranza lo apruebe) podía exceder por completo el saldo pendiente
    # real de la inscripción. actualizar_saldo_enrollment clampa
    # saldo_pendiente a 0 al aprobar, pero total_pagado sigue creciendo sin
    # límite -- "Pagado > Total" quedaba permanente sin ningún mecanismo de
    # crédito/devolución. Se permite un pequeño margen (1 Bs) para redondeos
    # legítimos del estudiante.
    if monto_real > enrollment.saldo_pendiente + 1.0:
        raise ValueError(
            f"El monto reportado (Bs. {monto_real}) supera el saldo pendiente de la inscripción "
            f"(Bs. {enrollment.saldo_pendiente}). Verifica el monto antes de registrar el pago."
        )

    payment = Payment(
        inscripcion_id=payment_in.inscripcion_id,
        estudiante_id=enrollment.estudiante_id,
        curso_id=enrollment.curso_id,

        metodo_pago=payment_in.metodo_pago,
        concepto=concepto_final,
        detalle=detalle_final,  # F-COBRANZA-020: desglose separado del concepto
        cantidad_pago=monto_real,
        numero_cuota=cuota_final,

        numero_transaccion=payment_in.numero_transaccion,
        comprobante_url=payment_in.comprobante_url,
        remitente=payment_in.remitente,
        banco=payment_in.banco,
        monto_comprobante=monto_real,
        fecha_comprobante=payment_in.fecha_comprobante,
        cuenta_destino=payment_in.cuenta_destino,

        # F-COBRANZA-004 (2026-07-21): aprobación automática al subir comprobante.
        # Ya no hay estado "pendiente" en el flujo principal. El coord. financiero
        # puede RECHAZAR después si el comprobante es inválido (con reversión de
        # saldo). Esto reduce la fricción operativa: en producción las 48h de
        # espera generaban desconfianza en los estudiantes y retrasaban la
        # conciliación con el extracto bancario.
        estado_pago=EstadoPago.APROBADO if auto_approve else EstadoPago.PENDIENTE,
        verificado_por=None,  # se setea más abajo

        # F-087 (2026-07-28): quién subió el comprobante. None para pagos
        # antiguos; "estudiante" o "encargado" para nuevos. Usado por la
        # nueva vista "Por Pago" en /app/payments.
        subido_por=subido_por,
    )
    # Setear fecha_verificacion y verificado_por manualmente porque aprobar_pago()
    # es un método de instancia que asume que ya está insertado.
    from core.timezone_utils import utcnow_naive
    payment.fecha_verificacion = utcnow_naive() if auto_approve else None
    if approved_by:
        # F-COBRANZA-017: si el pago lo registra un usuario staff, dejar
        # claro en la auditoría quién fue. Formato: "STAFF:<username>" para
        # distinguir de la auto-aprobación del estudiante.
        payment.verificado_por = f"STAFF:{approved_by}"
    elif auto_approve:
        payment.verificado_por = "SISTEMA (auto-aprobación)"
    else:
        payment.verificado_por = None

    await payment.insert()

    if not auto_approve:
        # Si NO se auto-aprueba, notificar a los revisores (Cobranza, CPD, Admin, Superadmin, Encargados)
        # para que revisen y aprueben el comprobante. Los efectos colaterales (saldo, auditoría)
        # se ejecutarán cuando staff apruebe el pago explícitamente.
        try:
            from services.notification_service import create_notification
            from beanie.operators import Or as _Or
            from models.user import User, UserRole
            from models.student import Student

            _est = await Student.get(payment.estudiante_id)
            nombre_est = (_est.nombre or _est.registro) if _est else "Un estudiante"

            revisores = await User.find(
                User.activo == True,
                _Or(
                    User.rol == UserRole.COBRANZA,
                    User.rol == UserRole.CPD,
                    User.rol == UserRole.ADMIN,
                    User.rol == UserRole.SUPERADMIN,
                    User.rol == UserRole.ENCARGADO_CURSO
                )
            ).to_list()

            for revisor in revisores:
                if revisor.rol == UserRole.ENCARGADO_CURSO and payment.curso_id not in revisor.cursos_asignados:
                    continue
                await create_notification(
                    destinatario_id=revisor.id,
                    tipo_destinatario="user",
                    titulo="Nuevo Pago Pendiente de Revisión",
                    mensaje=f"{nombre_est} subió un comprobante de pago por Bs. {payment.cantidad_pago} ('{payment.concepto}') y espera tu aprobación.",
                    tipo_alerta="info",
                    ruta="/app/payments",
                    referencia_tipo="payment",
                    referencia_id=payment.id
                )
        except Exception as e:
            print(f"Error notificando nuevo pago pendiente: {str(e)}")

        return payment

    # ========================================================================
    # F-COBRANZA-004: Efectos colaterales de la aprobación automática
    # (los mismos que tendría aprobar_pago manualmente)
    # ========================================================================

    # 1) Actualizar saldo de la inscripción
    # F-074-FIX-5 (2026-07-23): agregar retry para evitar desincronización
    # entre `total_pagado` del enrollment y los pagos aprobados. Si la
    # operación falla por RevisionIdWasChanged (otro proceso modificó el
    # enrollment entre la lectura y el guardado), reintentamos UNA vez.
    # Caso detectado (origen: Alfredo Elias Tito Mendoza Villarroel 2026-07-23):
    # 7 estudiantes de DIPL-IA-2026 quedaron con `total_pagado` desactualizado
    # (300 = solo matrícula) aunque tenían pagos aprobados por Bs 588-2.940.
    # La libreta del estudiante mostraba "Pagado: Bs 0.00" para todos los
    # módulos aunque el pago SÍ estaba en Gestión de Pagos con comprobante.
    #
    # F-082 (2026-07-28): además del log WARNING, notificar al equipo económico
    # (cobranza/admin/superadmin) con un notification in-app para que vean el
    # desbalance y puedan ejecutar el fix manualmente. Caso real: Medardo
    # Balvino Rojas (CI 2720765) + Jerry Fletcher quedaron con saldo fantasma
    # por Bs 588 cada uno sin que nadie se enterara hasta que Sandra lo reportó
    # manualmente desde Excel.
    try:
        await enrollment_service.actualizar_saldo_enrollment(
            enrollment_id=payment.inscripcion_id,
            monto_pago_aprobado=payment.cantidad_pago
        )
    except Exception as first_error:
        # Retry: 1 intento más por si fue race condition
        try:
            await enrollment_service.actualizar_saldo_enrollment(
                enrollment_id=payment.inscripcion_id,
                monto_pago_aprobado=payment.cantidad_pago
            )
        except Exception as retry_error:
            # F-074-FIX-5: loguear como WARNING (no print) para que sea
            # visible en监控系统. Si esto pasa, ejecutar el script
            # evidence/reuniones/2026-07-23/fix-prorrateo-masivo-v2.py
            # --apply para corregir las desincronizaciones.
            import logging
            logger = logging.getLogger("kyc.payment")
            logger.warning(
                f"F-074-FIX-5: pago {payment.id} aprobado pero prorrateo "
                f"falló tras 2 intentos. enrollment={payment.inscripcion_id} "
                f"monto={payment.cantidad_pago}. "
                f"Error1: {str(first_error)[:200]}. "
                f"Error2: {str(retry_error)[:200]}. "
                f"Ejecutar fix-prorrateo-masivo-v2.py --apply para corregir."
            )

            # F-082 (2026-07-28): notificar al equipo económico via in-app
            # notification. Si la notification falla, no bloqueamos el flujo
            # (el log WARNING ya queda).
            try:
                from services.notification_service import create_notification
                from models.user import User
                from models.enums import UserRole
                from beanie import PydanticObjectId
                from beanie.operators import In as BIn

                # Notificar a cobranza + admin + superadmin del MISMO curso
                destinatarios = await User.find(
                    User.activo == True,
                    BIn(User.rol, [UserRole.COBRANZA, UserRole.ADMIN, UserRole.SUPERADMIN, UserRole.MAE])
                ).to_list()

                # Limitar a 10 destinatarios para no spamear
                for dest in destinatarios[:10]:
                    try:
                        await create_notification(
                            destinatario_id=dest.id,
                            tipo_destinatario="user",
                            titulo="⚠️ Desbalance de saldo detectado",
                            mensaje=(
                                f"El pago {payment.id} (Bs {payment.cantidad_pago}) fue aprobado pero "
                                f"el prorrateo al enrollment {payment.inscripcion_id} falló tras 2 intentos. "
                                f"Ejecutar evidence/reuniones/2026-07-28/fix-enrollments-desincronizados.py "
                                f"--enrollment-id {payment.inscripcion_id} --apply para corregir."
                            ),
                            tipo_alerta="error",
                            ruta="/app/enrollments",
                            referencia_tipo="enrollment",
                            referencia_id=payment.inscripcion_id
                        )
                    except Exception as notif_err:
                        logger.warning(f"F-082: no se pudo notificar a {dest.username}: {notif_err}")
            except Exception as notify_setup_err:
                # Si el import o el find falla, no rompemos el flujo principal
                logger.warning(f"F-082: setup de notification fallo: {notify_setup_err}")

    # 2) Auditoría financiera (inmutable, obligatoria para todo movimiento)
    await _registrar_auditoria_financiera(
        accion="APROBACION AUTOMATICA",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username="SISTEMA",
        detalles=f"Pago auto-aprobado al subir comprobante. Concepto: {payment.concepto}, método: {payment.metodo_pago}"
    )

    # 3) Notificación al estudiante (pago aprobado)
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Aprobado",
            mensaje=f"Tu pago de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}' ha sido conciliado y aprobado de forma exitosa.",
            tipo_alerta="success",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago aprobado: {str(e)}")

    # 4) Email real al estudiante (no bloqueante)
    try:
        from models.student import Student as _Student
        from core.email_utils import send_email, build_pago_aprobado_email
        from core.config import settings

        _est = await _Student.get(payment.estudiante_id)
        if _est and _est.email:
            portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/payments"
            html = build_pago_aprobado_email(
                nombre=_est.nombre or _est.registro,
                concepto=payment.concepto,
                monto=payment.cantidad_pago,
                portal_link=portal_link
            )
            await send_email(_est.email, "Pago Aprobado · Posgrado UAGRM", html)
    except Exception as e:
        print(f"Error al enviar correo de pago aprobado: {str(e)}")

    # 5) [NOTIFICACIONES - ISSUE-U-BUZON]
    # Antes: "Nuevo Pago Pendiente" → ahora: "Nuevo Pago Registrado" (INFO, sin
    # acción requerida). El coord. financiero puede RECHAZAR si detecta
    # inconsistencia, pero la conciliación se hizo al subir el comprobante.
    try:
        from models.user import User
        from models.enums import UserRole
        from services.notification_service import create_notification

        student_obj = await Student.get(student_id)
        student_name = student_obj.nombre if student_obj and student_obj.nombre else "Estudiante registrado"

        from beanie.operators import Or
        observadores = await User.find(
            User.activo == True,
            Or(
                User.rol == UserRole.COBRANZA,
                User.rol == UserRole.CPD,
                # Admin/Superadmin ven todo
                User.rol == UserRole.ADMIN,
                User.rol == UserRole.SUPERADMIN
            )
        ).to_list()

        for obs in observadores:
            await create_notification(
                destinatario_id=obs.id,
                tipo_destinatario="user",
                titulo="Nuevo Pago Registrado",
                mensaje=f"El estudiante {student_name} ({student_obj.registro if student_obj else ''}) registró un pago de Bs. {monto_real} por el concepto '{concepto_final}'. Ya fue conciliado automáticamente.",
                tipo_alerta="info",
                ruta="/app/payments",
                referencia_tipo="payment",
                referencia_id=payment.id
            )
    except Exception as e:
        print(f"Error al enviar notificación de nuevo pago: {str(e)}")

    return payment


async def get_payment(id: PydanticObjectId) -> Optional[Payment]:
    return await Payment.get(id)


async def get_payments_by_student(student_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.estudiante_id == student_id).sort("-fecha_subida").to_list()


async def get_payments_by_enrollment(enrollment_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.inscripcion_id == enrollment_id).sort("-fecha_subida").to_list()


async def get_payments_by_course(course_id: PydanticObjectId) -> List[Payment]:
    return await Payment.find(Payment.curso_id == course_id).sort("-fecha_subida").to_list()


async def get_all_payments(
    page: int = 1,
    per_page: int = 10,
    q: Optional[str] = None,
    estado: Optional[str] = None,
    curso_id: Optional[PydanticObjectId] = None,
    estudiante_id: Optional[PydanticObjectId] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    tipo_concepto: Optional[str] = None
) -> tuple[List[Payment], int]:
    """
    cursos_permitidos (ISSUE-P-SEGMENTACION): si se provee (no None), restringe
    los resultados únicamente a pagos de esos cursos. Reutiliza el mismo patrón
    de segmentación que ENCARGADO_CURSO en enrollment_service.get_all_enrollments.
    """
    query_dict = {}
    
    if estado and estado != "Todos los estados":
        query_dict["estado_pago"] = estado

    if estudiante_id:
        query_dict["estudiante_id"] = estudiante_id

    if curso_id:
        enrollments = await Enrollment.find(Enrollment.curso_id == curso_id).to_list()
        enrollment_ids = [e.id for e in enrollments]
        query_dict["inscripcion_id"] = {"$in": enrollment_ids}

    if cursos_permitidos is not None:
        query_dict["curso_id"] = {"$in": cursos_permitidos}
        
    if tipo_concepto:
        if tipo_concepto == "matricula":
            query_dict["concepto"] = {"$regex": "matricula|matrícula", "$options": "i"}
        elif tipo_concepto == "colegiatura":
            query_dict["concepto"] = {"$not": {"$regex": "matricula|matrícula", "$options": "i"}}
            
    if q:
        # BUG 8 FIX: el Or de Beanie con `==` comparaba un dict de regex contra
        # un string, por lo que NUNCA encontraba estudiantes (solo coincidía si
        # el nombre era literalmente el dict, lo cual es imposible). Se reemplaza
        # por RegEx de Beanie, que arma correctamente la consulta Mongo
        # `{$regex: q, $options: "i"}` para los 4 campos del estudiante.
        from beanie.operators import RegEx
        regex_q = q.strip()
        if not regex_q:
            # cadena vacía tras trim: no aplicar filtro de búsqueda libre
            pass
        else:
            matching_students = await Student.find(
                Or(
                    RegEx(Student.nombre, regex_q, "i"),
                    RegEx(Student.registro, regex_q, "i"),
                    RegEx(Student.carnet, regex_q, "i"),
                    RegEx(Student.email, regex_q, "i"),
                )
            ).to_list()

            matching_student_ids = [s.id for s in matching_students]

            # $or ya no puede vivir en el mismo nivel si hay otros filtros
            # restrictivos; Mongo lo rechaza con "already has $or" si se mete
            # en query_dict después de haber establecido $and/u otras claves
            # iguales. La forma correcta es $and a nivel raíz.
            or_filters = [
                {"numero_transaccion": {"$regex": regex_q, "$options": "i"}},
                {"concepto": {"$regex": regex_q, "$options": "i"}},
                {"remitente": {"$regex": regex_q, "$options": "i"}},
                {"banco": {"$regex": regex_q, "$options": "i"}},
                {"estudiante_id": {"$in": matching_student_ids}},
            ]
            # Combinar con cualquier $and previo (cursos_permitidos, etc.)
            if "$and" in query_dict:
                query_dict["$and"].append({"$or": or_filters})
            elif any(k in query_dict for k in ("estado_pago", "estudiante_id", "inscripcion_id", "curso_id", "concepto")):
                # Hay otros filtros: hay que envolverlos en $and para que convivan con $or
                other_filters = {k: v for k, v in query_dict.items() if k != "$or"}
                query_dict.clear()
                query_dict["$and"] = [
                    other_filters,
                    {"$or": or_filters},
                ]
            else:
                query_dict["$or"] = or_filters
    
    total_count = await Payment.find(query_dict).count()
    skip = (page - 1) * per_page
    payments = await Payment.find(query_dict).sort("-fecha_subida").skip(skip).limit(per_page).to_list()
    
    return payments, total_count


async def get_payments_pendientes(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
) -> List[Payment]:
    """cursos_permitidos (ISSUE-P-SEGMENTACION): ver nota en get_all_payments."""
    if cursos_permitidos is not None:
        return await Payment.find(
            Payment.estado_pago == EstadoPago.PENDIENTE,
            In(Payment.curso_id, cursos_permitidos)
        ).to_list()
    return await Payment.find(Payment.estado_pago == EstadoPago.PENDIENTE).to_list()


async def aprobar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> Payment:
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.PENDIENTE:
        raise ValueError(
            f"No se puede aprobar un pago que está en estado {payment.estado_pago}"
        )
    
    payment.aprobar_pago(admin_username)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): otra request (aprobar/rechazar) ya modificó
        # este pago entre la lectura y este guardado. Se rechaza limpio en
        # vez de sobrescribir a ciegas (evita duplicar/inflar el saldo).
        raise ValueError(
            "Este pago ya fue modificado por otra acción (posible aprobación/rechazo simultáneo). "
            "Actualiza la página e intenta de nuevo."
        )
    
    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=payment.inscripcion_id,
        monto_pago_aprobado=payment.cantidad_pago
    )

    await _registrar_auditoria_financiera(
        accion="APROBAR PAGO",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Aprobado el {payment.concepto}"
    )

    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que su pago ha sido aprobado de manera exitosa
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Aprobado",
            mensaje=f"Tu pago de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}' ha sido conciliado y aprobado de forma exitosa.",
            tipo_alerta="success",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago aprobado: {str(e)}")

    # Correo real al estudiante confirmando la aprobación (no bloqueante: si
    # falla el envío o el estudiante no tiene email, el pago ya quedó aprobado).
    try:
        from models.student import Student as _Student
        from core.email_utils import send_email, build_pago_aprobado_email
        from core.config import settings

        _est = await _Student.get(payment.estudiante_id)
        if _est and _est.email:
            portal_link = f"{settings.FRONTEND_URL.rstrip('/')}/app/payments"
            html = build_pago_aprobado_email(
                nombre=_est.nombre or _est.registro,
                concepto=payment.concepto,
                monto=payment.cantidad_pago,
                portal_link=portal_link
            )
            await send_email(_est.email, "Pago Aprobado · Posgrado UAGRM", html)
    except Exception as e:
        print(f"Error al enviar correo de pago aprobado: {str(e)}")

    return payment


async def rechazar_pago(
    payment_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> Payment:
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")

    # F-COBRANZA-004 (2026-07-21): desde la aprobación automática, los pagos
    # nacen en APROBADO. Por lo tanto el rechazo puede operar sobre APROBADO
    # (caso normal) o PENDIENTE (legacy, datos anteriores al deploy). En ambos
    # casos se rechaza con motivo, pero solo se reversa el saldo si estaba
    # APROBADO (porque solo entonces se había acreditado al enrollment).
    if payment.estado_pago not in (EstadoPago.APROBADO, EstadoPago.PENDIENTE):
        raise ValueError(
            f"No se puede rechazar un pago que está en estado {payment.estado_pago}. "
            "Solo se rechazan pagos APROBADOS o PENDIENTES (legacy)."
        )

    # Si estaba APROBADO, recordar para reversar el saldo después.
    estaba_aprobado = payment.estado_pago == EstadoPago.APROBADO

    payment.rechazar_pago(admin_username, motivo)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): ver nota equivalente en aprobar_pago.
        raise ValueError(
            "Este pago ya fue modificado por otra acción (posible aprobación/rechazo simultáneo). "
            "Actualiza la página e intenta de nuevo."
        )

    # F-COBRANZA-004: si el pago estaba APROBADO, reversar el saldo del
    # enrollment para mantener la consistencia contable.
    if estaba_aprobado:
        try:
            await enrollment_service.actualizar_saldo_enrollment(
                enrollment_id=payment.inscripcion_id,
                monto_pago_aprobado=0.0  # el método recalcula desde cero
            )
        except Exception as e:
            print(f"Error al reversar saldo tras rechazo de pago aprobado: {str(e)}")

    await _registrar_auditoria_financiera(
        accion="RECHAZAR PAGO",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Rechazado. Motivo: {motivo}. {'(Pago estaba APROBADO — saldo reversado)' if estaba_aprobado else '(Pago estaba PENDIENTE — sin reversión de saldo)'}"
    )
    
    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que su pago fue rechazado indicándole el motivo del cajero
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Rechazado",
            mensaje=f"Tu comprobante de pago por Bs. {payment.cantidad_pago} para '{payment.concepto}' ha sido rechazado. Motivo: {motivo}",
            tipo_alerta="error",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago rechazado: {str(e)}")

    return payment


async def anular_pago(
    payment_id: PydanticObjectId,
    admin_username: str,
    motivo: str
) -> Payment:
    """
    ISSUE-P-CANALES: Realiza un Rollback Financiero (Anulación de pago ya aprobado).
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")
    
    if payment.estado_pago != EstadoPago.APROBADO:
        raise ValueError(
            f"La anulación solo aplica para pagos APROBADOS. "
            f"Este pago se encuentra en estado '{payment.estado_pago}'."
        )
    
    payment.anular_pago(admin_username, motivo)
    try:
        await payment.save()
    except RevisionIdWasChanged:
        # AUDITORÍA (CRÍTICO #2): ver nota equivalente en aprobar_pago.
        raise ValueError(
            "Este pago ya fue modificado por otra acción simultánea. Actualiza la página e intenta de nuevo."
        )

    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=payment.inscripcion_id,
        monto_pago_aprobado=0.0 
    )

    await _registrar_auditoria_financiera(
        accion="ANULAR PAGO (ROLLBACK)",
        payment_id=payment.id,
        estudiante_id=payment.estudiante_id,
        monto=payment.cantidad_pago,
        admin_username=admin_username,
        detalles=f"Anulación de fondos. Motivo legal: {motivo}"
    )
    
    # [NOTIFICACIONES - ISSUE-U-BUZON]
    # Notificar al estudiante que un pago previamente aprobado ha sido anulado (rollback)
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=payment.estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Anulado (Reversión)",
            mensaje=f"Atención: Tu pago aprobado de Bs. {payment.cantidad_pago} por el concepto '{payment.concepto}' ha sido anulado. Razón: {motivo}",
            tipo_alerta="warning",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al enviar notificación de pago anulado: {str(e)}")

    return payment


async def eliminar_pago(
    payment_id: PydanticObjectId,
    admin_username: str
) -> dict:
    """
    Elimina FÍSICAMENTE un pago de la base de datos (borrado destructivo,
    exclusivo de superadmin). Pensado para limpiar pagos de prueba/erróneos
    que no deben computar en la contabilidad.

    A diferencia de `anular_pago` (que preserva el registro con estado ANULADO),
    esto borra el documento por completo y luego recalcula el saldo/estado de la
    inscripción desde CERO a partir de los pagos APROBADOS restantes en la base
    de datos, sin importar en qué estado estuviera el pago borrado. De esta forma
    los totales económicos quedan consistentes tras la eliminación.
    """
    payment = await Payment.get(payment_id)
    if not payment:
        raise ValueError(f"Pago {payment_id} no encontrado")

    # Capturar datos antes de borrar (para auditoría y recálculo)
    enrollment_id = payment.inscripcion_id
    estudiante_id = payment.estudiante_id
    monto = payment.cantidad_pago
    concepto = payment.concepto
    estado_previo = payment.estado_pago.value if payment.estado_pago else "desconocido"

    await payment.delete()

    # Recalcular saldo de la inscripción desde los pagos aprobados que quedan.
    # actualizar_saldo_enrollment recomputa desde cero (suma los pagos APROBADOS
    # actuales en BD), por lo que basta con invocarlo tras el borrado.
    if enrollment_id:
        try:
            await enrollment_service.actualizar_saldo_enrollment(
                enrollment_id=enrollment_id,
                monto_pago_aprobado=0.0
            )
        except Exception as e:
            print(f"Error al recalcular saldo tras eliminar pago {payment_id}: {str(e)}")

    await _registrar_auditoria_financiera(
        accion="ELIMINAR PAGO (BORRADO DEFINITIVO)",
        payment_id=payment_id,
        estudiante_id=estudiante_id,
        monto=monto,
        admin_username=admin_username,
        detalles=f"Borrado físico de pago (estado previo: {estado_previo}, concepto: {concepto})"
    )

    return {
        "success": True,
        "message": "Pago eliminado correctamente",
        "payment_id": str(payment_id)
    }


async def get_resumen_economico(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None
) -> dict:
    """
    ISSUE-P-DASHBOARD-COBRANZA: resumen económico agregado para el dashboard de
    Cobranza / coordinador financiero.

    A diferencia de la vista de pagos (que a Cobranza le oculta las matrículas),
    este resumen SÍ incluye el ingreso por matrícula como dato contable, porque
    Cobranza genera los informes económicos y necesita ver todo lo recaudado
    (regla confirmada en reunión: "cobranza lo ve porque generamos los informes
    económicos"). Es de solo lectura y agregado; no expone pagos individuales de
    matrícula ni permite operarlos.

    Devuelve:
      - ingreso_matricula: suma de pagos APROBADOS con concepto Matrícula.
      - ingreso_colegiatura: suma de pagos APROBADOS de módulos/cuotas (no matrícula).
      - total_ingresos: ingreso_matricula + ingreso_colegiatura.
      - total_esperado: suma de total_a_pagar de todas las inscripciones del alcance.
      - por_cobrar: suma de saldo_pendiente (lo que falta recaudar).
      - cobros_pendientes: cantidad de PERSONAS/inscripciones con saldo pendiente (> 0).
      - total_inscritos: cantidad de inscripciones en el alcance.

    Respeta la segmentación por curso (Cobranza con cursos_asignados solo ve su
    alcance) vía `cursos_permitidos`.
    """
    match_pagos: dict = {"estado_pago": EstadoPago.APROBADO}
    match_enroll: dict = {}
    if cursos_permitidos is not None:
        match_pagos["curso_id"] = {"$in": cursos_permitidos}
        match_enroll["curso_id"] = {"$in": cursos_permitidos}

    pagos_task = Payment.find(match_pagos).to_list()
    enrollments_task = Enrollment.find(match_enroll).to_list()
    pagos, enrollments = await asyncio.gather(pagos_task, enrollments_task)

    ingreso_matricula = 0.0
    ingreso_colegiatura = 0.0
    for p in pagos:
        concepto = (p.concepto or "").lower().strip()
        es_matricula = "matricula" in concepto or "matrícula" in concepto
        if es_matricula:
            ingreso_matricula += p.cantidad_pago or 0.0
        else:
            ingreso_colegiatura += p.cantidad_pago or 0.0

    total_ingresos = ingreso_matricula + ingreso_colegiatura

    # F-COBRANZA-POR-COBRAR: "Por Cobrar" NO incluye inscripciones suspendidas
    # (congelado, pasivo, abandono), completadas ni canceladas. Sandra Cobranza
    # reportó (2026-07-23) que el sistema le sumaba Bs 13.230 de 3 pasivos al
    # "Por Cobrar", desalineándolo de su Excel. El `total_esperado` se mantiene
    # intacto porque es la suma teórica de lo que TODOS los inscritos deberían
    # pagar (incluye pasivos porque al reactivarse vuelven a deber).
    #
    # F-083 (2026-07-28): se agrega RETIRADO a la lista de excluidos del
    # "Por Cobrar". Distinto de SUSPENDIDO+abandono (que es automático):
    # RETIRADO es VOLUNTARIO y DEFINITIVO, no vuelve nunca. "Esos ya no
    # debería sumar sus pagos para cuentas por cobrar, solo queda lo que
    # pagaron y se cierra" (Lic. Sorich, 2026-07-28). Importante: los
    # RETIRADOS SÍ cuentan en ingreso_colegiatura (lo que ya pagaron es
    # ingreso real), pero NO cuentan en por_cobrar (lo que falta ya no
    # se cobra).
    estados_excluidos_por_cobrar = {
        EstadoInscripcion.SUSPENDIDO,
        EstadoInscripcion.COMPLETADO,
        EstadoInscripcion.CANCELADO,
        EstadoInscripcion.RETIRADO,  # F-083
    }

    total_esperado = 0.0
    por_cobrar = 0.0
    cobros_pendientes = 0
    for e in enrollments:
        total_esperado += e.total_a_pagar or 0.0
        if e.estado in estados_excluidos_por_cobrar:
            continue
        saldo = e.saldo_pendiente or 0.0
        por_cobrar += saldo
        if saldo > 0.01:
            cobros_pendientes += 1

    return {
        "ingreso_matricula": round(ingreso_matricula, 2),
        "ingreso_colegiatura": round(ingreso_colegiatura, 2),
        "total_ingresos": round(total_ingresos, 2),
        "total_esperado": round(total_esperado, 2),
        "por_cobrar": round(por_cobrar, 2),
        "cobros_pendientes": cobros_pendientes,
        "total_inscritos": len(enrollments),
    }


# ============================================================================
# F-074 (2026-07-23): VISTA MATRICIAL DE PAGOS
# ============================================================================
# Estructura visual estilo Excel de Sandra (Cobranza):
#   Filas = estudiantes
#   Columnas = MATRÍCULA | MONTO | MODULO 1 | MODULO 2 | ... | TOTAL INGRESOS | POR COBRAR
# Fuente de datos: `Enrollment.modulos[]` (snapshot por estudiante del curso).
# Cada `ModuloEstado` tiene `costo`, `monto_pagado` y `estado` ('Pendiente'|'Parcial'|'Pagado').
# Para la matrícula usamos `Enrollment.costo_matricula` y `Enrollment.total_pagado`
# (cascada greedy: primero se imputa a matrícula, luego a módulos en orden).


async def get_matriz_pagos(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    modulo_index: Optional[int] = None,
) -> dict:
    """
    F-074: devuelve la matriz estudiante-vs-módulos para vista alternativa de
    Gestión de Pagos (replica el Excel de Sandra).

    Reglas:
    - Excluye enrollments SUSPENDIDO/COMPLETADO/CANCELADO de las columnas
      monetarias (igual que F-073, regla de Kevin/Sandra: "Por Cobrar" no
      incluye congelados/pasivos).
    - `total_ingresos` = suma de pagos APROBADOS del enrollment (cualquier
      estado de enrollment, refleja lo realmente recaudado).
    - `por_cobrar` = saldo_pendiente del enrollment (excluye suspendidos).
    - Si `modulo_index` viene, la respuesta incluye solo ese módulo en
      `estudiantes[].modulos` para que el frontend pueda resaltar la columna
      sin traer todas.

    Estructura:
    {
      "cursos": [{"_id", "nombre", "codigo", "modulos": ["Módulo 1", ...]}],
      "estudiantes": [
        {
          "estudiante_id": str,
          "nombre": str,
          "registro": str,
          "curso_id": str,
          "estado_inscripcion": "activo",
          "matricula_pagada": bool,
          "matricula_monto": float,       # costo_matricula
          "matricula_pagado": float,      # cuánto se imputó a matrícula
          "modulos": [
            {"i": 0, "nombre": "Módulo 1", "costo": float, "monto_pagado": float, "estado": "Pagado", "por_cobrar": float}
          ],
          "total_ingresos": float,
          "por_cobrar": float,
          # F-074-FIX-4: campos de auditoría de descuentos/becas
          "beca_porcentaje": float,        # % total de descuento aplicado (curso + personal)
          "ahorro": float,                 # Bs ahorrados vs costo sin descuento del curso
          "costo_sin_descuento": float,    # Lo que pagaría sin descuento (matrícula + 5 módulos)
          "pago_todo": bool,               # True si pagó matrícula + todos los módulos
        }
      ],
      "totales_por_columna": {
        "matricula": {"costo_total": float, "pagado": float, "pendiente": float, "estudiantes_pagaron": int},
        "modulos": [
          {"i": 0, "nombre": "Módulo 1", "costo_total": float, "pagado": float, "pendiente": float, "estudiantes_pagaron": int, "estudiantes_pendientes": int}
        ],
        "total_ingresos": float,
        "por_cobrar": float,
        "total_inscritos": int,
        # F-074-FIX-4: contadores globales
        "estudiantes_pagaron_todo": int,  # Cuántos pagaron matrícula + todos los módulos
        "estudiantes_con_beca": int,       # Cuántos tienen algún descuento aplicado
        "ahorro_total_por_descuentos": float,  # Suma total de Bs ahorrados
      },
      "filtros_aplicados": {"modulo_index": int|None, "cursos_count": int},
    }
    """
    match_enroll: dict = {}
    if cursos_permitidos is not None:
        match_enroll["curso_id"] = {"$in": cursos_permitidos}

    enrollments_task = Enrollment.find(match_enroll).to_list()
    courses_task = Course.find({}).to_list()
    enrollments, courses = await asyncio.gather(enrollments_task, courses_task)

    courses_map = {c.id: c for c in courses}
    courses_list: list = [
        {
            "_id": str(c.id),
            "nombre": c.nombre_programa,
            "codigo": c.codigo,
            "modulos": [m.nombre for m in (c.modulos or [])],
        }
        for c in courses
    ]

    # Estados que NO cuentan para "Por Cobrar" (regla F-073)
    # F-083 (2026-07-28): se agrega RETIRADO. Los RETIRADOS NO suman a
    # "Por Cobrar" (abandono definitivo, no vuelven). Sí cuentan en
    # total_ingresos porque lo que pagaron es dinero real que entró a caja.
    estados_excluidos = {
        EstadoInscripcion.SUSPENDIDO,
        EstadoInscripcion.COMPLETADO,
        EstadoInscripcion.CANCELADO,
        EstadoInscripcion.RETIRADO,  # F-083
    }

    # Acumuladores de totales por columna
    tot_mat_costo = 0.0
    tot_mat_pagado = 0.0
    tot_mat_pendiente = 0.0
    tot_mat_pagaron = 0
    tot_modulos: dict = {}  # i -> {costo_total, pagado, pendiente, pagaron, pendientes}
    tot_ingresos = 0.0
    tot_por_cobrar = 0.0
    tot_inscritos = 0
    tot_pagaron_todo = 0  # F-074-FIX-4: cuántos tienen matrícula + todos los módulos pagados
    tot_con_beca = 0       # F-074-FIX-4: cuántos tienen algún descuento
    tot_ahorro_total = 0.0  # F-074-FIX-4: ahorro total por descuentos aplicados

    # Carga batch de estudiantes para resolver nombres
    student_ids = list({e.estudiante_id for e in enrollments if e.estudiante_id})
    students = await Student.find({"_id": {"$in": student_ids}}).to_list() if student_ids else []
    students_map = {s.id: s for s in students}

    estudiantes_out: list = []

    for e in enrollments:
        curso = courses_map.get(e.curso_id)
        if not curso:
            continue  # curso borrado, skip defensivo

        student = students_map.get(e.estudiante_id)
        nombre = (student.nombre if student and getattr(student, "nombre", None) else None) or "Sin nombre"
        registro = (student.registro if student and getattr(student, "registro", None) else None) or ""

        # Para ingresos siempre se cuentan pagos APROBADOS (es lo recaudado)
        total_ingresos_e = float(e.total_pagado or 0.0)
        tot_ingresos += total_ingresos_e

        # Por cobrar solo si NO está excluido
        if e.estado in estados_excluidos:
            por_cobrar_e = 0.0
        else:
            por_cobrar_e = float(e.saldo_pendiente or 0.0)
            tot_por_cobrar += por_cobrar_e
            tot_inscritos += 1

        # Matrícula
        costo_mat = float(e.costo_matricula or 0.0)
        # Cuánto se imputó realmente a matrícula: min(total_pagado, costo_matricula)
        mat_pagado = min(total_ingresos_e, costo_mat)
        mat_pendiente = max(0.0, costo_mat - mat_pagado)
        tot_mat_costo += costo_mat
        tot_mat_pagado += mat_pagado
        if e.estado not in estados_excluidos:
            tot_mat_pendiente += mat_pendiente
            if mat_pagado + 0.01 >= costo_mat:
                tot_mat_pagaron += 1

        # Módulos
        modulos_out: list = []
        for i, mod in enumerate(e.modulos or []):
            costo = float(mod.costo or 0.0)
            pagado = float(mod.monto_pagado or 0.0)
            pendiente = max(0.0, costo - pagado)

            # Si la columna específica no está en el filtro, skip
            if modulo_index is not None and modulo_index != i:
                continue

            if i not in tot_modulos:
                tot_modulos[i] = {
                    "i": i,
                    "nombre": mod.nombre,
                    "costo_total": 0.0,
                    "pagado": 0.0,
                    "pendiente": 0.0,
                    "estudiantes_pagaron": 0,
                    "estudiantes_pendientes": 0,
                }
            tot_mod = tot_modulos[i]
            tot_mod["costo_total"] += costo
            tot_mod["pagado"] += pagado
            if e.estado not in estados_excluidos:
                tot_mod["pendiente"] += pendiente
                if pendiente <= 0.01:
                    tot_mod["estudiantes_pagaron"] += 1
                else:
                    tot_mod["estudiantes_pendientes"] += 1

            modulos_out.append({
                "i": i,
                "nombre": mod.nombre,
                "costo": round(costo, 2),
                "monto_pagado": round(pagado, 2),
                "estado": mod.estado,
                "por_cobrar": round(pendiente, 2) if e.estado not in estados_excluidos else 0.0,
            })

        # Si modulo_index es 0, lo representamos como "matrícula" en la columna
        # NOTA: por convención del Excel de Sandra, Módulo 0 visual = MATRÍCULA.
        # Pero los módulos del curso empiezan en 0 = Módulo 1. El frontend debe
        # mostrar la columna "MATRÍCULA" usando matricula_monto/matricula_pagado,
        # y las columnas Módulo 1..N usando modulos[0..N-1].

        # F-074-FIX-4 (2026-07-23): beca y ahorro del estudiante
        # Regla de Kevin (2026-07-23 10:01 GMT-4): "el descuento solamente es
        # para modulos no matriculas eso no se cambia eso es una regla si o si
        # no hagas sonceras". La matrícula NUNCA tiene descuento, solo los
        # módulos. Por lo tanto el `ahorro` se calcula únicamente sobre los
        # módulos, NO sobre la matrícula. El campo `costo_matricula` en BD es
        # el costo ORIGINAL de la matrícula (sin beca), por regla de negocio.
        desc_curso = float(e.descuento_curso_aplicado or 0)
        desc_personal = float(e.descuento_personalizado or 0) if e.descuento_personalizado is not None else 0.0
        # Costo de los módulos DEL CURSO sin descuento (referencia, ya que el
        # costo en `e.modulos[]` está CON descuento aplicado al becado)
        costo_curso_sin_desc = sum((float(m.costo or 0.0)) for m in (curso.modulos or []))
        # Costo de los módulos DEL ESTUDIANTE (con descuento ya aplicado)
        costo_modulos_con_desc_estudiante = sum(
            (float(m.costo or 0.0)) for m in (e.modulos or [])
        )
        # Costo sin descuento del estudiante = matrícula (sin beca, regla Kevin)
        # + módulos del CURSO sin descuento. NO se aplica beca a la matrícula.
        costo_total_sin_desc = float(e.costo_matricula or 0.0) + costo_curso_sin_desc
        total_a_pagar_e = float(e.total_a_pagar or 0.0)
        # El ahorro es la diferencia entre lo que pagaría SIN beca y lo que paga
        # CON beca. Como la beca NUNCA aplica a matrícula, el ahorro viene
        # solamente de los módulos: (costo_curso_sin_desc - costo_modulos_con_desc_estudiante)
        ahorro_modulos = max(0.0, costo_curso_sin_desc - costo_modulos_con_desc_estudiante)
        ahorro_e = ahorro_modulos  # Por regla de Kevin, NUNCA se resta matrícula
        # Beca efectiva del estudiante (puede ser 0% si no tiene descuento)
        beca_porcentaje = desc_curso + (desc_personal or 0.0)
        # Solo se considera "con beca" si el ahorro > 0 (puede haber un descuento
        # que no se aplicó realmente — caso bug histórico)
        tiene_beca = ahorro_e > 0.01 and beca_porcentaje > 0

        # F-074-FIX-4: "no veo el conteo del que pago todo" — calcular si pagó
        # matrícula + todos los módulos
        todos_modulos_pagados = all(
            (m.estado == "Pagado") for m in (e.modulos or [])
        ) if (e.modulos or []) else False
        pago_todo = bool(e.matricula_pagada) and todos_modulos_pagados and bool(e.modulos)

        if pago_todo:
            tot_pagaron_todo += 1
        if tiene_beca:
            tot_con_beca += 1
        tot_ahorro_total += ahorro_e

        estudiantes_out.append({
            "estudiante_id": str(e.estudiante_id) if e.estudiante_id else "",
            "nombre": nombre,
            "registro": registro,
            "curso_id": str(e.curso_id) if e.curso_id else "",
            "curso_nombre": curso.nombre_programa,
            "estado_inscripcion": e.estado.value if hasattr(e.estado, "value") else str(e.estado),
            "matricula_pagada": bool(e.matricula_pagada),
            "matricula_monto": round(costo_mat, 2),
            "matricula_pagado": round(mat_pagado, 2),
            "modulos": modulos_out,
            "total_ingresos": round(total_ingresos_e, 2),
            "por_cobrar": round(por_cobrar_e, 2),
            # F-074-FIX-4: campos de auditoría de descuentos
            "beca_porcentaje": round(beca_porcentaje, 1),
            "ahorro": round(ahorro_e, 2),
            "costo_sin_descuento": round(costo_total_sin_desc, 2),
            "pago_todo": pago_todo,
        })

    # Ordenar estudiantes por nombre
    estudiantes_out.sort(key=lambda x: x["nombre"].lower())

    # Construir totales_por_columna
    # Si modulo_index filtra, ajustamos la respuesta para reflejar solo esa columna
    totales = {
        "matricula": {
            "costo_total": round(tot_mat_costo, 2),
            "pagado": round(tot_mat_pagado, 2),
            "pendiente": round(tot_mat_pendiente, 2),
            "estudiantes_pagaron": tot_mat_pagaron,
        },
        "modulos": [
            {
                "i": idx,
                "nombre": d["nombre"],
                "costo_total": round(d["costo_total"], 2),
                "pagado": round(d["pagado"], 2),
                "pendiente": round(d["pendiente"], 2),
                "estudiantes_pagaron": d["estudiantes_pagaron"],
                "estudiantes_pendientes": d["estudiantes_pendientes"],
            }
            for idx, d in sorted(tot_modulos.items())
        ],
        "total_ingresos": round(tot_ingresos, 2),
        "por_cobrar": round(tot_por_cobrar, 2),
        "total_inscritos": tot_inscritos,
        # F-074-FIX-4: contadores adicionales solicitados por Kevin
        "estudiantes_pagaron_todo": tot_pagaron_todo,
        "estudiantes_con_beca": tot_con_beca,
        "ahorro_total_por_descuentos": round(tot_ahorro_total, 2),
    }

    return {
        "cursos": courses_list,
        "estudiantes": estudiantes_out,
        "totales_por_columna": totales,
        "filtros_aplicados": {
            "modulo_index": modulo_index,
            "cursos_count": len(courses_list),
        },
    }


# =============================================================================
# F-088 (2026-07-29): Vista "Deudores" unificada para Cobranza
# =============================================================================
# Reunión 2026-07-29: Lic. Sandra Zabala pidió una vista a "un solo golpe visual"
# donde pueda ver para cada curso, qué estudiantes deben qué módulos. Hoy tiene
# que descargar módulo por módulo en Excel y filtrar manualmente los que no
# pagaron. Con esta vista, los estudiantes son filas y los módulos son columnas
# (verde = pagado, rojo = debe, gris = no_le_toca). Puede filtrar "solo
# deudores" para enfocarse solo en los que deben algo y exportar a Excel.
#
# Diferencias con get_matriz_pagos (F-074):
# - Solo 1 curso a la vez (más simple, enfocado a cobranza de cohorte).
# - Filtro `solo_deudores` que esconde a los que pagaron todo.
# - Incluye datos de contacto (celular, email) para que cobranza pueda mandar
#   WhatsApp directo.
# - Estado explícito por celda (pagado / parcial / debe / no_le_toca) en vez
#   de solo el monto_pagado.
# - Total por fila (cuánto debe en total) y total por columna.
async def get_matriz_deudores(
    curso_id: PydanticObjectId,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    solo_deudores: bool = True,
) -> dict:
    """
    F-088 (2026-07-29): vista "Deudores" para cobranza.

    Args:
        curso_id: ID del curso (obligatorio).
        cursos_permitidos: si se pasa (cobranza con cursos_asignados), se
            valida que el curso_id esté en la lista. None = superadmin ve todos.
        solo_deudores: si True, solo retorna estudiantes que deben ALGO
            (matrícula pendiente O algún módulo pendiente O saldo_pendiente > 0).
            Si False, retorna todos los estudiantes inscritos.

    Returns:
        {
          "curso": {"_id", "nombre", "codigo", "modulos": ["Módulo 1", ...], "matricula_monto": float},
          "estudiantes": [
            {
              "estudiante_id": str,
              "registro": str,
              "nombre": str,
              "ci": str,         # "1234567" o "1234567-1J"
              "email": str,
              "celular": str,
              "estado_inscripcion": "activo",
              "matricula": {
                "costo": float, "pagado": float, "pendiente": float,
                "estado": "pagado" | "debe" | "no_le_toca"
              },
              "modulos": [
                {
                  "i": 0,  # 0-indexed
                  "nombre": "Módulo 1",
                  "costo": float, "pagado": float, "pendiente": float,
                  "estado": "pagado" | "debe" | "no_le_toca"
                },
                ...
              ],
              "deuda_total": float,  # suma de matrícula pendiente + módulos pendientes
              "modulos_pendientes": [1, 3, 4],  # índices 1-based para UI
            }
          ],
          "resumen": {
            "total_estudiantes": int,
            "total_deudores": int,        # con deuda_total > 0
            "deuda_total_curso": float,   # suma de deudas de todos los deudores
            "por_columna": {              # para header
              "matricula": {"deben": int, "monto_pendiente": float},
              "modulos": [{"i": 0, "deben": int, "monto_pendiente": float}, ...]
            }
          },
          "filtros_aplicados": {"curso_id": str, "solo_deudores": bool}
        }
    """
    # Validar segmentación de cursos
    if cursos_permitidos is not None and curso_id not in cursos_permitidos:
        raise ValueError("No tiene acceso a este curso")

    # 1) Cargar curso
    curso = await Course.get(curso_id)
    if not curso:
        raise ValueError(f"Curso {curso_id} no encontrado")

    # 2) Cargar enrollments del curso
    enrollments = await Enrollment.find(Enrollment.curso_id == curso_id).to_list()
    if not enrollments:
        return {
            "curso": {
                "_id": str(curso.id),
                "nombre": curso.nombre_programa,
                "codigo": curso.codigo,
                "modulos": [m.nombre for m in (curso.modulos or [])],
                "matricula_monto": float(curso.matricula_interno or 0.0),
            },
            "estudiantes": [],
            "resumen": {
                "total_estudiantes": 0,
                "total_deudores": 0,
                "deuda_total_curso": 0.0,
                "por_columna": {"matricula": {"deben": 0, "monto_pendiente": 0.0}, "modulos": []},
            },
            "filtros_aplicados": {"curso_id": str(curso_id), "solo_deudores": solo_deudores},
        }

    # 3) Cargar estudiantes en batch
    student_ids = list({e.estudiante_id for e in enrollments if e.estudiante_id})
    students = await Student.find({"_id": {"$in": student_ids}}).to_list() if student_ids else []
    students_map = {s.id: s for s in students}

    # 4) Estados excluidos (no cuentan como deudores — congelados/retirados)
    estados_excluidos = {
        EstadoInscripcion.SUSPENDIDO,
        EstadoInscripcion.COMPLETADO,
        EstadoInscripcion.CANCELADO,
        EstadoInscripcion.RETIRADO,
    }

    # 5) Construir matriz
    curso_dict = {
        "_id": str(curso.id),
        "nombre": curso.nombre_programa,
        "codigo": curso.codigo,
        "modulos": [m.nombre for m in (curso.modulos or [])],
        "matricula_monto": float(curso.matricula_interno or 0.0),
    }

    estudiantes_out: list = []
    total_deudores = 0
    deuda_total_curso = 0.0

    # Para resumen por columna
    col_mat_deben = 0
    col_mat_monto_pendiente = 0.0
    col_modulos_resumen: dict = {i: {"i": i, "deben": 0, "monto_pendiente": 0.0} for i in range(len(curso.modulos or []))}

    for e in enrollments:
        student = students_map.get(e.estudiante_id)
        if not student:
            continue

        # Calcular estado de la matrícula
        costo_mat = float(e.costo_matricula or 0.0)
        total_pagado_e = float(e.total_pagado or 0.0)
        # Cuánto se imputó realmente a matrícula (cascada greedy)
        mat_pagado = min(total_pagado_e, costo_mat)
        mat_pendiente = max(0.0, costo_mat - mat_pagado)
        # Estado: "debe" si hay pendiente, "pagado" si completó (independiente del descuento)
        if e.estado in estados_excluidos:
            mat_estado = "no_le_toca"
            mat_pendiente = 0.0  # No contar como deuda
        elif mat_pendiente <= 0.01:
            mat_estado = "pagado"
        else:
            mat_estado = "debe"

        # Calcular estado de cada módulo
        modulos_out: list = []
        modulos_pendientes: list = []  # 1-based para UI
        deuda_total_est = 0.0

        for i, mod in enumerate(curso.modulos or []):
            mod_estado_e = e.modulos[i] if i < len(e.modulos or []) else None
            costo = float(mod.costo or 0.0)
            pagado = float(mod_estado_e.monto_pagado) if mod_estado_e else 0.0
            pendiente = max(0.0, costo - pagado)

            if e.estado in estados_excluidos:
                mod_estado = "no_le_toca"
                pendiente = 0.0
            elif pendiente <= 0.01:
                mod_estado = "pagado"
            else:
                mod_estado = "debe"
                deuda_total_est += pendiente
                modulos_pendientes.append(i + 1)  # 1-based
                col_modulos_resumen[i]["deben"] += 1
                col_modulos_resumen[i]["monto_pendiente"] += pendiente

            modulos_out.append({
                "i": i,
                "nombre": mod.nombre,
                "costo": round(costo, 2),
                "pagado": round(pagado, 2),
                "pendiente": round(pendiente, 2),
                "estado": mod_estado,
            })

        # Sumar matrícula a la deuda
        if mat_estado == "debe":
            deuda_total_est += mat_pendiente
            col_mat_deben += 1
            col_mat_monto_pendiente += mat_pendiente

        # Armar CI con complemento
        ci = student.carnet or ""
        if student.complemento_carnet:
            ci = f"{ci}-{student.complemento_carnet}"

        # F-088: si solo_deudores=True, saltar a quien no debe nada
        if solo_deudores and deuda_total_est <= 0.01:
            continue

        if deuda_total_est > 0.01:
            total_deudores += 1
            deuda_total_curso += deuda_total_est

        estudiantes_out.append({
            "estudiante_id": str(e.estudiante_id),
            "registro": student.registro or "",
            "nombre": (student.nombre or "").strip() or "Sin nombre",
            "ci": ci,
            "email": student.email or "",
            "celular": student.celular or "",
            "estado_inscripcion": e.estado.value if hasattr(e.estado, "value") else str(e.estado),
            "matricula": {
                "costo": round(costo_mat, 2),
                "pagado": round(mat_pagado, 2),
                "pendiente": round(mat_pendiente, 2),
                "estado": mat_estado,
            },
            "modulos": modulos_out,
            "deuda_total": round(deuda_total_est, 2),
            "modulos_pendientes": modulos_pendientes,
        })

    # Ordenar por nombre (alfabético, como pidió Sandra)
    estudiantes_out.sort(key=lambda x: x["nombre"].lower())

    # Deudores primero si solo_deudores=False (los que deben van arriba)
    if not solo_deudores:
        estudiantes_out.sort(key=lambda x: (x["deuda_total"] <= 0.01, x["nombre"].lower()))

    # Resumen por columna
    por_columna = {
        "matricula": {
            "deben": col_mat_deben,
            "monto_pendiente": round(col_mat_monto_pendiente, 2),
        },
        "modulos": [col_modulos_resumen[i] for i in sorted(col_modulos_resumen.keys())],
    }

    return {
        "curso": curso_dict,
        "estudiantes": estudiantes_out,
        "resumen": {
            "total_estudiantes": len(estudiantes_out),
            "total_deudores": total_deudores,
            "deuda_total_curso": round(deuda_total_curso, 2),
            "por_columna": por_columna,
        },
        "filtros_aplicados": {"curso_id": str(curso_id), "solo_deudores": solo_deudores},
    }


# F-087 (2026-07-28): Vista "Por Pago" - 1 fila por cada pago individual
# (a diferencia de la matriz que agrupa por estudiante/módulo). El objetivo es
# dar visibilidad a la auditoría: cada pago llega con su comprobante, su
# número de transacción, su fecha, y su responsable de subida.
# Si el concepto cubre varios módulos ("Pago Módulos 1, 2") se generan 2 filas
# en la salida, una por módulo, prorrateando el monto. Esto es SOLO vista;
# en BD sigue siendo 1 documento.

def _parse_modulos_de_concepto(concepto: str) -> list:
    """
    Devuelve la lista de modulo_index mencionados en un concepto.
    - "Matrícula" / "Módulo" (genérico) → [] (no se sabe a qué módulo va)
    - "Pago Módulo 1" → [1]
    - "Pago Módulos 1, 2" → [1, 2]
    - "Pago Módulos 1, 2, 3" → [1, 2, 3]
    - "Pago parcial Módulos 2, 3" → [2, 3]
    """
    import re
    if not concepto:
        return []
    c = concepto.upper()
    if "MATRIC" in c:
        return [0]
    nums = re.findall(r'\d+', c)
    return [int(n) for n in nums if 1 <= int(n) <= 9]


async def get_matriz_por_pago(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    curso_id: Optional[PydanticObjectId] = None,
    modulo_index: Optional[int] = None,
    estado_pago: Optional[str] = None,
    subido_por: Optional[str] = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """
    F-087 (2026-07-28): vista "Por Pago" - 1 fila por cada estudiante, con
    sus pagos individuales listados como items. F-087-FIX2 (2026-07-28):
    reorganizado a formato matriz (estudiantes como filas) para que se vea
    horizontal como la matriz tradicional.

    F-087-FIX11 (2026-07-28): por defecto NO se cuentan pagos anulados ni
    rechazados — esos pagos no representan dinero real (fueron cancelados
    o rechazados por la cobranza) y mostrarlos en la vista Por Pago daba
    datos erróneos al comparar contra el XLSX de Sandra o al hacer
    auditoría. Si el usuario explícitamente filtra por estado_pago
    ('anulado' o 'rechazado'), respetamos ese filtro para que pueda ver
    esos pagos en una vista dedicada.

    Cada estudiante tiene una lista de pagos. La UI renderiza cada pago
    como una columna. Si un estudiante tiene más pagos que el `max_pagos`
    configurado, los extras se devuelven pero la UI los marca como "+N más".

    Reglas:
    - `cursos_permitidos`: si se pasa (cobranza con cursos_asignados), filtra
      a esos cursos. None = todos.
    - `curso_id`: filtro adicional por curso específico.
    - `modulo_index`: filtra por módulo. Si un pago cubre varios módulos
      ("Pago Módulos 1, 2"), el pago aparece SOLO si modulo_index coincide
      con uno de los módulos del concepto.
    - `estado_pago`: filtra por estado. Si None, devuelve SOLO aprobado +
      pendiente (excluye anulado y rechazado por defecto).
    - `subido_por`: filtra por "estudiante" | "encargado" | None.
    - Paginación: page (1-indexed), per_page (max 500). Se aplica a la
      lista de ESTUDIANTES (no de pagos individuales).

    Salida: estructura tipo matriz. La UI la renderiza como una tabla
    con estudiantes como filas y cada pago como una columna horizontal.
    """
    match: dict = {}
    if cursos_permitidos is not None:
        match["curso_id"] = {"$in": cursos_permitidos}
    if curso_id is not None:
        match["curso_id"] = curso_id
    if estado_pago:
        match["estado_pago"] = estado_pago
    else:
        # F-087-FIX11 (2026-07-28): por defecto excluir anulado y rechazado.
        # Esos pagos no representan dinero real y contaminan los totales de la
        # vista Por Pago al compararse contra el XLSX de auditoría.
        match["estado_pago"] = {"$nin": ["anulado", "rechazado"]}
    if subido_por is not None:
        # Permite filtrar por null también (pagos antiguos). Si subido_por
        # es "" o "null" lo interpretamos como None real.
        if subido_por in ("", "null", "None"):
            match["subido_por"] = None
        else:
            match["subido_por"] = subido_por

    # Traemos todos los pagos que matchean (sin paginar todavía). El conteo
    # puede ser alto (cientos por cohorte) pero el filtro por curso reduce.
    from models.payment import Payment
    from models.student import Student
    from models.course import Course
    from models.enrollment import Enrollment

    pagos = await Payment.find(match).sort("+fecha_subida").to_list()

    # Estudiantes y cursos en batch
    est_ids = list({p.estudiante_id for p in pagos})
    estudiantes_list = await Student.find({"_id": {"$in": est_ids}}).to_list() if est_ids else []
    estudiantes_map = {s.id: s for s in estudiantes_list}

    curso_ids = list({p.curso_id for p in pagos})
    cursos_list = await Course.find({"_id": {"$in": curso_ids}}).to_list() if curso_ids else []
    # F-087-FIX12 (2026-07-29): el lookup se hace con string (el item dict
    # serializa curso_id como str). Map dual: str y ObjectId para cubrir
    # cualquier consumidor.
    cursos_map = {str(c.id): c for c in cursos_list}
    cursos_map.update({c.id: c for c in cursos_list})

    # Enrollments para total_a_pagar por estudiante
    enr_list = await Enrollment.find({"estudiante_id": {"$in": est_ids}}).to_list() if est_ids else []
    enr_by_est = {e.estudiante_id: e for e in enr_list}

    # F-087-FIX2: 1 pago = 1 item, sin partir. Agrupamos por estudiante.
    # Cada item contiene los datos del pago más el módulo principal y la
    # lista de módulos cubiertos (modulos_cubiertos).
    pagos_por_est: dict = defaultdict(list)
    for p in pagos:
        modulos_del_pago = _parse_modulos_de_concepto(p.concepto or "")

        # Filtro por modulo_index: si el usuario filtró por un módulo específico
        # y este pago NO incluye ese módulo en su cobertura, lo saltamos.
        if modulo_index is not None:
            if not modulos_del_pago or modulo_index not in modulos_del_pago:
                continue

        # modulo_index primario
        if 0 in modulos_del_pago:
            modulo_index_row = 0
        elif modulos_del_pago:
            modulo_index_row = modulos_del_pago[0]
        else:
            modulo_index_row = None

        item = {
            "payment_id": str(p.id),
            "monto": round(p.monto_comprobante or 0, 2),
            "concepto": p.concepto,
            "modulo_index": modulo_index_row,
            "modulos_cubiertos": modulos_del_pago,
            "estado_pago": p.estado_pago,
            "subido_por": p.subido_por,
            "verificado_por": p.verificado_por,
            "comprobante_url": p.comprobante_url,
            "numero_transaccion": p.numero_transaccion,
            "fecha_subida": p.fecha_subida.isoformat() if p.fecha_subida else None,
            "fecha_comprobante": p.fecha_comprobante.isoformat() if p.fecha_comprobante else None,
            "banco": p.banco,
            "metodo_pago": p.metodo_pago,
            "remitente": p.remitente,
            # F-087-FIX12 (2026-07-29): curso_id del pago individual. Sin esto, el
            # frontend no puede poblar la columna CURSO de la vista Por Pago
            # (queda "—" para todas las filas). Ahora línea 1783 puede resolver
            # el curso desde el primer item del estudiante.
            "curso_id": str(p.curso_id) if p.curso_id else None,
        }
        pagos_por_est[p.estudiante_id].append(item)

    # Construir la respuesta agrupada por estudiante.
    # Ordenar estudiantes por nombre
    estudiantes_ordenados = sorted(
        pagos_por_est.keys(),
        key=lambda eid: (estudiantes_map.get(eid).nombre or "").lower()
        if estudiantes_map.get(eid) else ""
    )

    estudiantes_out = []
    for est_id in estudiantes_ordenados:
        est = estudiantes_map.get(est_id)
        items = pagos_por_est[est_id]
        # F-087-FIX10 (2026-07-28): ordenar pagos del estudiante por fecha_subida ASC.
        # Regla de Kevin: Matrícula primero (siempre, por convención), luego los
        # pagos por módulo en el orden en que llegaron (cronológico ascendente).
        # Antes: fecha_subida DESC → Módulos 1-2 (21-jul) salía como Pago 1 y la
        # Matrícula (09-jul) salía última como Pago 3.
        # Como la Matrícula es típicamente el primer pago que hace un estudiante,
        # ordenar por fecha_subida ASC da naturalmente: Matrícula → Módulo 1 → M2 → ...
        items.sort(key=lambda x: x.get("fecha_subida") or "")

        # Calcular totales del estudiante
        total_aprobado_est = sum(i["monto"] for i in items if i["estado_pago"] == "aprobado")
        total_anulado_est = sum(i["monto"] for i in items if i["estado_pago"] == "anulado")
        total_pendiente_est = sum(i["monto"] for i in items if i["estado_pago"] == "pendiente")
        total_rechazado_est = sum(i["monto"] for i in items if i["estado_pago"] == "rechazado")

        ci = est.carnet if est else None
        registro = est.registro if est else None
        nombre = (est.nombre or "").strip() if est else None
        # F-087-FIX12 (2026-07-29): el curso del estudiante sale del PRIMER item
        # del row. Si el estudiante tiene pagos de VARIOS cursos (sin filtro de
        # curso), se toma el más frecuente (el "principal"). Antes, el item dict
        # no incluía "curso_id" y la columna CURSO del Por Pago quedaba vacía
        # ("—") para todos los estudiantes.
        curso_id = None
        if items:
            # Tomar el curso más frecuente (el principal del estudiante)
            from collections import Counter
            cursos_counter = Counter(
                i.get("curso_id") for i in items if i.get("curso_id")
            )
            if cursos_counter:
                curso_id = cursos_counter.most_common(1)[0][0]
        curso = cursos_map.get(curso_id) if curso_id else None

        enr = enr_by_est.get(est_id)
        total_a_pagar = float(enr.total_a_pagar) if enr and enr.total_a_pagar else None

        estudiantes_out.append({
            "estudiante_id": str(est_id),
            "estudiante_nombre": nombre,
            "estudiante_ci": ci,
            "estudiante_registro": registro,
            "curso_id": str(curso_id) if curso_id else None,
            "curso_codigo": curso.codigo if curso else None,
            "curso_nombre": curso.nombre_programa if curso else None,
            "pagos": items,
            "total_pagado_aprobado": round(total_aprobado_est, 2),
            "total_pagado_anulado": round(total_anulado_est, 2),
            "total_pagado_pendiente": round(total_pendiente_est, 2),
            "total_pagado_rechazado": round(total_rechazado_est, 2),
            "total_a_pagar": total_a_pagar,
            "saldo_pendiente": enr.saldo_pendiente if enr else None,
            "cantidad_pagos": len(items),
        })

    # Paginación (sobre estudiantes)
    total_estudiantes = len(estudiantes_out)
    start = (page - 1) * per_page
    end = start + per_page
    estudiantes_pag = estudiantes_out[start:end]

    # max_pagos entre todos los estudiantes (para saber cuántas columnas dibujar)
    max_pagos = max((e["cantidad_pagos"] for e in estudiantes_out), default=0)

    # Resumen global
    todos_pagos_flat = [i for items in pagos_por_est.values() for i in items]
    total_aprobado = sum(i["monto"] for i in todos_pagos_flat if i["estado_pago"] == "aprobado")
    total_anulado = sum(i["monto"] for i in todos_pagos_flat if i["estado_pago"] == "anulado")
    total_pendiente = sum(i["monto"] for i in todos_pagos_flat if i["estado_pago"] == "pendiente")
    total_rechazado = sum(i["monto"] for i in todos_pagos_flat if i["estado_pago"] == "rechazado")

    return {
        "estudiantes": estudiantes_pag,
        "total": total_estudiantes,
        "page": page,
        "per_page": per_page,
        "total_pages": (total_estudiantes + per_page - 1) // per_page if per_page else 1,
        "max_pagos": max_pagos,
        "resumen": {
            "total_aprobado": round(total_aprobado, 2),
            "total_anulado": round(total_anulado, 2),
            "total_pendiente": round(total_pendiente, 2),
            "total_rechazado": round(total_rechazado, 2),
            "total_pagos": len(todos_pagos_flat),
            "pagos_con_comprobante": sum(1 for i in todos_pagos_flat if i.get("comprobante_url")),
            "total_estudiantes": total_estudiantes,
        },
        "filtros_aplicados": {
            "curso_id": str(curso_id) if curso_id else None,
            "modulo_index": modulo_index,
            "estado_pago": estado_pago,
            "subido_por": subido_por,
        },
    }


def _pago_to_fila(p, estudiante, curso, modulo_index, monto_asignado, concepto, modulo_nombre=None, modulos_cubiertos=None):
    """
    Helper F-087: convierte un documento Payment en una fila para la vista
    Por Pago. Si modulo_index es None, no se imputa a un módulo específico
    (caso de conceptos genéricos o sin módulo identificable).
    """
    from beanie import PydanticObjectId as _POI
    ci = None
    registro = None
    nombre = None
    if estudiante:
        ci = estudiante.carnet
        registro = estudiante.registro
        # F-087: el modelo Student solo tiene `nombre` (sin `apellido` separado).
        # En BD legacy el nombre completo puede estar en `nombre`. La UI
        # muestra este string tal cual.
        nombre = (estudiante.nombre or "").strip() or None

    curso_codigo = curso.codigo if curso else None
    curso_nombre = curso.nombre_programa if curso else None

    return {
        "payment_id": str(p.id),
        "inscripcion_id": str(p.inscripcion_id),
        "estudiante_id": str(p.estudiante_id) if p.estudiante_id else None,
        "estudiante_nombre": nombre,
        "estudiante_ci": ci,
        "estudiante_registro": registro,
        "curso_id": str(p.curso_id) if p.curso_id else None,
        "curso_codigo": curso_codigo,
        "curso_nombre": curso_nombre,
        "modulo_index": modulo_index,
        "modulo_nombre": modulo_nombre,
        "modulos_cubiertos": modulos_cubiertos or [],  # F-087-FIX: lista de todos los módulos que cubre este pago
        "concepto": concepto,
        "monto": round(monto_asignado, 2),
        "estado_pago": p.estado_pago,
        "subido_por": p.subido_por,  # None | "estudiante" | "encargado"
        "metodo_pago": p.metodo_pago,
        "banco": p.banco,
        "remitente": p.remitente,
        "numero_transaccion": p.numero_transaccion,
        "comprobante_url": p.comprobante_url,
        "fecha_subida": p.fecha_subida.isoformat() if p.fecha_subida else None,
        "fecha_comprobante": p.fecha_comprobante.isoformat() if p.fecha_comprobante else None,
        "fecha_verificacion": p.fecha_verificacion.isoformat() if p.fecha_verificacion else None,
        "verificado_por": p.verificado_por,
        "motivo_rechazo": p.motivo_rechazo,
        "motivo_reversion": p.motivo_reversion,
    }


async def get_resumen_modulos(
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
) -> dict:
    """
    F-074: resumen por módulo para KPI cards de la vista Matriz.

    Devuelve la cantidad de pagos, monto total y monto pendiente por módulo,
    excluyendo suspendidos (regla F-073).

    Estructura:
    {
      "modulos": [
        {
          "i": 0,
          "nombre": "Módulo 1",
          "cantidad_pagos": int,        # pagos APROBADOS con numero_cuota == i+1
          "monto_total": float,          # suma pagos APROBADOS
          "monto_pendiente": float,      # costo_total - pagado (solo no-suspendidos)
          "estudiantes_cursando": int,   # inscritos no-suspendidos con este módulo
        }
      ],
      "matricula": {
        "cantidad_pagos": int,
        "monto_total": float,
        "monto_pendiente": float,
        "estudiantes_cursando": int,
      },
    }
    """
    match_enroll: dict = {}
    if cursos_permitidos is not None:
        match_enroll["curso_id"] = {"$in": cursos_permitidos}

    enrollments = await Enrollment.find(match_enroll).to_list()

    estados_excluidos = {
        EstadoInscripcion.SUSPENDIDO,
        EstadoInscripcion.COMPLETADO,
        EstadoInscripcion.CANCELADO,
        EstadoInscripcion.RETIRADO,  # F-083
    }

    # Acumuladores
    mat_cant = 0
    mat_monto = 0.0
    mat_pendiente = 0.0
    mat_cursando = 0
    modulos_acc: dict = {}

    for e in enrollments:
        en_curso = e.estado not in estados_excluidos

        # Matrícula
        costo_mat = float(e.costo_matricula or 0.0)
        pagado_mat = min(float(e.total_pagado or 0.0), costo_mat)
        pendiente_mat = max(0.0, costo_mat - pagado_mat) if en_curso else 0.0
        # Conteo de pagos APROBADOS con concepto 'matrícula'
        # (lo aproximamos: si el estudiante tiene pagos y el total_pagado cubre
        # la matrícula, contamos 1 pago de matrícula; refinado si el sistema
        # tiene `numero_cuota=0` o concepto='Matrícula' lo usamos)
        if e.total_pagado and e.total_pagado > 0 and pagado_mat + 0.01 >= costo_mat:
            mat_cant += 1
        mat_monto += pagado_mat
        if en_curso:
            mat_pendiente += pendiente_mat
            mat_cursando += 1

        # Módulos
        for i, mod in enumerate(e.modulos or []):
            if i not in modulos_acc:
                modulos_acc[i] = {
                    "i": i,
                    "nombre": mod.nombre,
                    "cantidad_pagos": 0,
                    "monto_total": 0.0,
                    "monto_pendiente": 0.0,
                    "estudiantes_cursando": 0,
                }
            d = modulos_acc[i]
            costo = float(mod.costo or 0.0)
            pagado = float(mod.monto_pagado or 0.0)
            pendiente = max(0.0, costo - pagado)
            # Aproximación: si el módulo está Pagado o tiene monto_pagado>0, contamos 1 pago
            if pagado + 0.01 >= costo:
                d["cantidad_pagos"] += 1
            elif pagado > 0.01:
                d["cantidad_pagos"] += 1  # también pagos parciales cuentan
            d["monto_total"] += pagado
            if en_curso:
                d["monto_pendiente"] += pendiente
                d["estudiantes_cursando"] += 1

    return {
        "matricula": {
            "cantidad_pagos": mat_cant,
            "monto_total": round(mat_monto, 2),
            "monto_pendiente": round(mat_pendiente, 2),
            "estudiantes_cursando": mat_cursando,
        },
        "modulos": [
            {
                "i": d["i"],
                "nombre": d["nombre"],
                "cantidad_pagos": d["cantidad_pagos"],
                "monto_total": round(d["monto_total"], 2),
                "monto_pendiente": round(d["monto_pendiente"], 2),
                "estudiantes_cursando": d["estudiantes_cursando"],
            }
            for d in sorted(modulos_acc.values(), key=lambda x: x["i"])
        ],
    }


def _construir_filtro_reporte_caja(
    fecha_desde_dt: datetime,
    fecha_hasta_dt: datetime,
    curso_id: Optional[PydanticObjectId] = None,
    estado: Optional[str] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    estudiante_id: Optional[PydanticObjectId] = None,
) -> dict:
    """
    ISSUE-P-REPORTE: filtro compartido entre la tabla interactiva y el export
    a Excel, para que ambos muestren siempre los mismos datos.

    Filtra por `fecha_comprobante` (fecha REAL de la transacción aportada por
    el usuario) O `fecha_subida` como respaldo si el pago no tiene
    `fecha_comprobante` registrada (defensivo; el flujo real del frontend
    siempre la envía, pero un pago creado por otra vía sin ese campo no debe
    desaparecer silenciosamente del reporte) -- regla de negocio explícita:
    "la contabilidad financiera se rige por la fecha real de la transacción,
    no por la fecha de aprobación/verificación en el panel"
    (steering/structure.md). El endpoint de Excel anterior filtraba solo por
    fecha_subida; se corrige aquí para ambos casos (tabla y export).

    F-COBRANZA-003 (2026-07-21): filtro opcional por estudiante_id.
    Permite ver todos los pagos de un estudiante específico.
    """
    criteria: dict = {
        "$or": [
            {"fecha_comprobante": {"$gte": fecha_desde_dt, "$lte": fecha_hasta_dt}},
            {"fecha_comprobante": None, "fecha_subida": {"$gte": fecha_desde_dt, "$lte": fecha_hasta_dt}},
        ]
    }
    if curso_id:
        criteria["curso_id"] = curso_id
    if estudiante_id:
        criteria["estudiante_id"] = estudiante_id
    if estado and estado != "Todos los estados":
        criteria["estado_pago"] = estado
    if cursos_permitidos is not None:
        # Si ya hay un curso_id específico Y además hay segmentación, deben
        # combinarse (AND), no pisarse uno al otro.
        if "curso_id" in criteria:
            if criteria["curso_id"] not in cursos_permitidos:
                # Curso solicitado fuera de los permitidos: forzar 0 resultados
                # en vez de devolver datos de otro curso.
                criteria["curso_id"] = {"$in": []}
        else:
            criteria["curso_id"] = {"$in": cursos_permitidos}
    return criteria


# =============================================================================
# F-075 (2026-07-23): INFORME ECONOMICO (antes "Lista de Postgraduantes Habilitados")
# F-079 (2026-07-24): Kevin pidio cambiar el titulo del documento a
# "INFORME ECONOMICO" (mas corto y claro). Aplica a JSON, XLSX y PDF.
# =============================================================================
async def generar_lista_habilitados(
    curso_id: PydanticObjectId,
    modulo_index: Optional[int] = None,
) -> dict:
    """
    F-075 (2026-07-23): Genera la "Lista de Postgraduantes Habilitados" para
    un curso, formato papel estilo Sandra para auditoría fiscal / aprobación
    de acta de notas.

    Args:
        curso_id: ID del curso (obligatorio).
        modulo_index:
            - None  = TODOS los módulos + matrícula (un registro por estudiante-módulo)
            - 0     = solo matrícula
            - 1..N  = solo ese módulo

    Returns:
        dict con:
            - curso: info del curso (codigo, nombre_programa, tipo_curso, etc.)
            - encabezado: {titulo, maestria_o_diplomado, modulo_label, periodo}
            - rows: lista de estudiantes con pagos aplicados al módulo(s) pedido(s)
            - total_importe: suma total
            - total_estudiantes: cantidad de filas

    Reglas:
        - Solo se listan estudiantes que TIENEN al menos un pago APROBADO
          aplicado al módulo (o matrícula) pedido.
        - Si el estudiante pagó en varios pagos parciales, se SUMAN en un solo
          registro (un registro por estudiante-módulo).
        - Se incluye la beca/descuento del estudiante (nombre + porcentaje)
          para justificar por qué unos pagan más que otros.
        - El docente se obtiene del módulo correspondiente (campo docente_id
          en Course.modulos[i]).
    """
    # 1) Cargar curso
    curso = await Course.get(curso_id)
    if not curso:
        raise ValueError(f"Curso {curso_id} no encontrado")

    # 2) Construir el label del módulo pedido
    if modulo_index is None:
        modulo_label = "Todos los módulos"
        indices_a_incluir = list(range(len(curso.modulos or [])))
    elif modulo_index == 0:
        modulo_label = "Matrícula"
        indices_a_incluir = []  # se trata aparte (matrícula)
    elif 1 <= modulo_index <= len(curso.modulos or []):
        mod = curso.modulos[modulo_index - 1]
        modulo_label = f"Módulo {modulo_index}: {mod.nombre}"
        indices_a_incluir = [modulo_index]
    else:
        raise ValueError(f"modulo_index {modulo_index} fuera de rango (curso tiene {len(curso.modulos or [])} módulos)")

    # 3) Obtener todos los enrollments del curso (incluyendo no-activos para auditoría)
    enrollments = await Enrollment.find(
        Enrollment.curso_id == curso_id
    ).to_list()

    # 3.5) BATCH LOADING (F-076 2026-07-23): cargar TODOS los estudiantes en 1 query.
    # Antes era 1 query por enrollment (N+1 problem). 54 estudiantes = 54 queries.
    estudiante_ids = list({e.estudiante_id for e in enrollments if e.estudiante_id})
    estudiantes_map = {}
    if estudiante_ids:
        estudiantes = await Student.find(In(Student.id, estudiante_ids)).to_list()
        estudiantes_map = {e.id: e for e in estudiantes}

    # 3.6) BATCH LOADING: cargar TODOS los pagos aprobados de todos los enrollments
    # en 1 sola query. Antes era 1 query por enrollment.
    enrollment_ids = [e.id for e in enrollments]
    pagos_por_enrollment = {}  # inscripcion_id -> lista de pagos
    pagos_por_enrollment_mat = {}  # inscripcion_id -> lista de pagos SOLO de matrícula
    if enrollment_ids:
        todos_los_pagos = await Payment.find(
            In(Payment.inscripcion_id, enrollment_ids),
            Payment.estado_pago == EstadoPago.APROBADO
        ).sort("-fecha_comprobante").to_list()
        for p in todos_los_pagos:
            pagos_por_enrollment.setdefault(p.inscripcion_id, []).append(p)
            if p.concepto and "matrícula" in p.concepto.lower():
                pagos_por_enrollment_mat.setdefault(p.inscripcion_id, []).append(p)

    # 3.7) BATCH LOADING: cargar TODOS los descuentos en 1 query.
    discount_ids_set = set()
    for enr in enrollments:
        if enr.descuento_curso_id:
            discount_ids_set.add(enr.descuento_curso_id)
        if enr.descuento_estudiante_id:
            discount_ids_set.add(enr.descuento_estudiante_id)
    discounts_map = {}
    if discount_ids_set:
        descuentos = await Discount.find(In(Discount.id, list(discount_ids_set))).to_list()
        for d in descuentos:
            discounts_map[d.id] = d

    # 3.8) BATCH LOADING: cargar TODOS los docentes (uno por módulo) en 1 query.
    from models.user import User
    docente_ids_set = set()
    for mod in (curso.modulos or []):
        if mod.docente_id:
            docente_ids_set.add(mod.docente_id)
    docente_nombre_map = {}
    if docente_ids_set:
        docentes = await User.find(In(User.id, list(docente_ids_set))).to_list()
        for d in docentes:
            docente_nombre_map[d.id] = d.nombre_visible or d.username or ""

    # 4) Docente del módulo pedido (lookup en map, sin query)
    docente_nombre = ""
    if modulo_index and 1 <= modulo_index <= len(curso.modulos or []):
        mod = curso.modulos[modulo_index - 1]
        if mod.docente_id:
            docente_nombre = docente_nombre_map.get(mod.docente_id, "")

    # 6) Etiqueta del tipo de programa para el encabezado
    tipo_curso_str = str(curso.tipo_curso.value) if hasattr(curso.tipo_curso, 'value') else str(curso.tipo_curso)
    # Capitalizar bonito
    tipo_label_map = {
        "maestria": "MAESTRÍA",
        "doctorado": "DOCTORADO",
        "diplomado": "DIPLOMADO",
        "curso": "CURSO",
        "taller": "TALLER",
        "otro": "PROGRAMA",
    }
    tipo_label = tipo_label_map.get(tipo_curso_str.lower(), tipo_curso_str.upper())

    # 7) Para cada enrollment, calcular los pagos aplicados al módulo pedido
    # F-075-FIX-8 (2026-07-23): AHORA se incluyen TODOS los estudiantes del curso,
    # no solo los que pagaron. Los que NO pagaron aparecen con estado_pago='PENDIENTE'
    # y los campos económicos (fecha, N° boleta, importe) en null/0.
    # Reglas:
    # - Si pagó completo: estado_pago='PAGADO', importe=monto_pagado, monto_pendiente=0
    # - Si pagó parcial: estado_pago='PARCIAL', importe=monto_pagado, monto_pendiente=restante
    # - Si NO pagó: estado_pago='PENDIENTE', importe=0, monto_pendiente=costo_total
    # Orden: 2 grupos (PAGADOS primero alfabético, luego PENDIENTES alfabético).
    # Beca: siempre incluida (puede ser null si no tiene).
    # F-076 (2026-07-23): refactor N+1 -> batch loading. 600+ queries -> 5 queries.
    # F-077 (2026-07-24): si el estudiante TIENE beca, el "costo del módulo" que
    # se usa para calcular estado_pago y monto_pendiente es el costo CON
    # DESCUENTO (no el costo sin descuento). Ej: Anselmo beca 50%, costo
    # módulo Bs 588, costo con descuento Bs 294. Si paga Bs 294 -> PAGADO
    # (es el total que le corresponde), NO parcial.
    # La beca aplica SOLO a módulos, NUNCA a matrícula (regla F-074-FIX-4).
    rows = []
    total_importe = 0.0
    total_pendiente = 0.0

    def _build_row(
        estudiante, modulo_idx, mod_nombre, mod_label, docente_n,
        monto_pagado, costo_total, fecha, boleta, beca_nombre, beca_pct, beca_tiene, es_matricula=False
    ):
        """Helper para construir un row. Se usa tanto para pagados como pendientes.

        Args:
            costo_total: costo SIN descuento del módulo o matrícula.
            beca_pct: porcentaje de beca (0 si no tiene). SOLO aplica a módulos.
            es_matricula: True si es la fila de matrícula (NUNCA tiene beca).
        """
        monto_pagado = round(monto_pagado, 2)
        costo_sin_desc = round(costo_total, 2)

        # F-077: calcular costo_con_descuento SOLO si tiene beca Y NO es matrícula
        if beca_tiene and beca_pct > 0 and not es_matricula:
            costo_con_desc = round(costo_sin_desc * (1 - beca_pct / 100.0), 2)
        else:
            costo_con_desc = costo_sin_desc

        monto_pendiente = round(max(0, costo_con_desc - monto_pagado), 2)

        if monto_pagado <= 0:
            estado_pago = "PENDIENTE"
        elif monto_pendiente > 0.01:
            estado_pago = "PARCIAL"
        else:
            estado_pago = "PAGADO"

        return {
            "estudiante_id": str(estudiante.id),
            "registro": estudiante.registro,
            "nombre": (estudiante.nombre or "").upper(),
            "ci": f"{estudiante.carnet or ''}{('-' + estudiante.complemento_carnet) if estudiante.complemento_carnet else ''}",
            "modulo_index": modulo_idx,
            "modulo_nombre": mod_nombre,
            "modulo_label": mod_label,
            "docente": docente_n,
            "estado_pago": estado_pago,
            "fecha_pago": fecha.isoformat() if fecha else None,
            "numero_boleta": boleta or ("" if monto_pagado <= 0 else "S/N"),
            "importe": monto_pagado,
            "monto_pendiente": monto_pendiente,
            "costo_total": costo_con_desc,  # F-077: para becados, este es el costo que DEBEN pagar
            "costo_sin_descuento": costo_sin_desc,  # F-077: nuevo, el costo original sin beca
            "beca": beca_nombre,
            "beca_porcentaje": round(beca_pct, 1) if beca_tiene else 0.0,
        }

    def _costo_modulo(i):
        if i == 0:
            return float(curso.matricula_interno or 0)
        return float(curso.modulos[i - 1].costo or 0)

    for enr in enrollments:
        # Datos del estudiante (lookup en map, sin query)
        estudiante = estudiantes_map.get(enr.estudiante_id)
        if not estudiante:
            continue

        # Becas del estudiante (siempre incluir, no condicional)
        beca_pct_total = float(enr.descuento_curso_aplicado or 0) + float(enr.descuento_personalizado or 0)
        beca_nombre = None
        beca_tiene = False
        if enr.descuento_estudiante_id and enr.descuento_estudiante_id in discounts_map:
            beca_nombre = discounts_map[enr.descuento_estudiante_id].nombre
            beca_tiene = True
        elif enr.descuento_curso_id and enr.descuento_curso_id in discounts_map:
            beca_nombre = discounts_map[enr.descuento_curso_id].nombre
            beca_tiene = True

        # Pagos del enrollment (lookup en map, sin query)
        pagos_del_enr = pagos_por_enrollment.get(enr.id, [])
        fecha = None
        boleta = None
        if pagos_del_enr:
            p = pagos_del_enr[0]  # ya está ordenado por -fecha_comprobante
            fecha = p.fecha_comprobante or p.fecha_subida
            boleta = p.numero_transaccion

        # Para "Todos los módulos", generamos UN registro por CADA MÓDULO del
        # estudiante (no solo los pagados).
        if modulo_index is None:
            for i, mod in enumerate(curso.modulos or [], start=1):
                mod_estado = enr.modulos[i - 1] if i - 1 < len(enr.modulos) else None
                monto_pagado_mod = float(mod_estado.monto_pagado) if mod_estado else 0.0
                costo_total = _costo_modulo(i)

                # Docente del módulo (lookup en map, sin query)
                docente_mod_nombre = ""
                if mod.docente_id:
                    docente_mod_nombre = docente_nombre_map.get(mod.docente_id, "")

                # F-077: NUNCA es matrícula en este loop (solo modulos)
                row = _build_row(
                    estudiante, i, mod.nombre, f"Módulo {i}", docente_mod_nombre,
                    monto_pagado_mod, costo_total, fecha, boleta,
                    beca_nombre, beca_pct_total, beca_tiene, es_matricula=False
                )
                rows.append(row)
                total_importe += row["importe"]
                total_pendiente += row["monto_pendiente"]
        else:
            # Módulo específico: 1 solo registro por estudiante (pagado O pendiente)
            if modulo_index == 0:
                # Matrícula: sumar pagos con concepto "Matrícula" (del map)
                pagos_mat = pagos_por_enrollment_mat.get(enr.id, [])
                monto_pagado = sum(p.cantidad_pago for p in pagos_mat)
                costo_total = _costo_modulo(0)
            else:
                mod_estado = enr.modulos[modulo_index - 1] if modulo_index - 1 < len(enr.modulos) else None
                monto_pagado = float(mod_estado.monto_pagado) if mod_estado else 0.0
                costo_total = _costo_modulo(modulo_index)

            mod_nombre = ""
            if modulo_index <= len(curso.modulos or []):
                mod_nombre = curso.modulos[modulo_index - 1].nombre

            # F-077: marcar si es matrícula para no aplicar beca
            row = _build_row(
                estudiante, modulo_index, mod_nombre, modulo_label, docente_nombre,
                monto_pagado, costo_total, fecha, boleta,
                beca_nombre, beca_pct_total, beca_tiene, es_matricula=(modulo_index == 0)
            )
            rows.append(row)
            total_importe += row["importe"]
            total_pendiente += row["monto_pendiente"]

    # F-075-FIX-8: ordenar 2 grupos (PAGADOS primero alfabético, luego PENDIENTES alfabético)
    # Dentro de PAGADO, los PARCIALES van al final del grupo PAGADO.
    def _sort_key(r):
        # Grupo 0 = PAGADO, Grupo 1 = PARCIAL, Grupo 2 = PENDIENTE
        grupo = {"PAGADO": 0, "PARCIAL": 1, "PENDIENTE": 2}.get(r["estado_pago"], 3)
        return (grupo, r["nombre"])
    rows.sort(key=_sort_key)

    # 8) Calcular período (rango de fechas de los pagos del módulo)
    periodo_label = ""
    if rows:
        fechas = [r["fecha_pago"] for r in rows if r["fecha_pago"]]
        if fechas:
            try:
                fechas_dt = [datetime.fromisoformat(f) for f in fechas]
                min_f = min(fechas_dt).strftime("%d/%m/%Y")
                max_f = max(fechas_dt).strftime("%d/%m/%Y")
                periodo_label = f"{min_f} al {max_f}"
            except Exception:
                periodo_label = ""

    return {
        "curso": {
            "id": str(curso.id),
            "codigo": curso.codigo,
            "nombre_programa": curso.nombre_programa,
            "tipo_curso": tipo_curso_str,
            "tipo_label": tipo_label,
        },
        "encabezado": {
            # F-079 (2026-07-24): Kevin pidio cambiar el titulo del documento.
            # Antes era "LISTA DE POSTGRADUANTES HABILITADOS", ahora es
            # "INFORME ECONOMICO" (mas corto, mas claro, aplica a los 3
            # formatos: JSON para el frontend, XLSX y PDF).
            "titulo": "INFORME ECONOMICO",
            "programa_tipo": tipo_label,
            "programa_nombre": curso.nombre_programa,
            "modulo": modulo_label,
            "periodo": periodo_label,
            "docente": docente_nombre,
        },
        "rows": rows,
        "total_importe": round(total_importe, 2),
        "total_pendiente": round(total_pendiente, 2),
        "total_estudiantes": len(rows),
    }


async def get_reporte_caja(
    fecha_desde_dt: datetime,
    fecha_hasta_dt: Optional[datetime] = None,
    page: int = 1,
    per_page: int = 20,
    curso_id: Optional[PydanticObjectId] = None,
    estado: Optional[str] = None,
    concepto_regex: Optional[dict] = None,
    cursos_permitidos: Optional[List[PydanticObjectId]] = None,
    estudiante_id: Optional[PydanticObjectId] = None,
) -> dict:
    """
    ISSUE-P-REPORTE: tabla interactiva de ingresos por rango de fechas (fecha
    real del pago), curso y estado, con totales agregados para el resumen
    visual (no solo la lista paginada).
    """
    criteria = _construir_filtro_reporte_caja(
        fecha_desde_dt, fecha_hasta_dt, curso_id=curso_id, estado=estado, cursos_permitidos=cursos_permitidos, estudiante_id=estudiante_id
    )
    if concepto_regex:
        criteria.update(concepto_regex)

    # F-075-FIX-7 (2026-07-23): el reporte de caja estaba roto desde un refactor
    # anterior (referenciaba variables inexistentes `payments_raw` y
    # `total_count`). Aqui lo reescribo completo con paginación correcta.
    # Totales agregados sobre TODO el rango filtrado (no solo la página actual)
    total_count = await Payment.find(criteria).count()
    skip = (page - 1) * per_page
    pagos_pagina_raw = await Payment.find(criteria).sort("-fecha_comprobante").skip(skip).limit(per_page).to_list()
    todos_los_pagos_del_rango = await Payment.find(criteria).to_list()

    total_aprobado = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.APROBADO)
    total_pendiente = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.PENDIENTE)
    # F-068 (2026-07-22, Kevin): "Total Anulado" debe incluir TANTO anulados
    # como rechazados (regla F-023: Débitos = anulados/rechazados).
    # Antes: solo contaba ANULADO, lo que daba 588 Bs en la UI vs 876 Bs en el PDF.
    total_anulado = sum(
        p.cantidad_pago for p in todos_los_pagos_del_rango
        if p.estado_pago in (EstadoPago.ANULADO, EstadoPago.RECHAZADO)
    )

    # F-COBRANZA-005 (2026-07-21): los pagos ANULADOS ahora se reportan con
    # monto negativo (en la lista) y se restan del total. Esto hace que el
    # reporte cuadre con el extracto bancario sin que el usuario tenga que
    # hacer la resta mentalmente. Auditoría: se mantienen los campos
    # `total_aprobado`, `total_anulado` y el nuevo `total_neto` para que el
    # contable pueda ver el desglose.
    total_neto = round(total_aprobado - total_anulado, 2)

    # En la lista de payments, los anulados se serializan con cantidad_pago
    # en negativo. El frontend los muestra como "-X" automáticamente.
    payments = []
    for p in pagos_pagina_raw:
        # to_dict para no mutar el documento persistido
        p_dict = p.model_dump(by_alias=True)
        if p.estado_pago == EstadoPago.ANULADO and p.cantidad_pago > 0:
            p_dict["cantidad_pago"] = -float(p.cantidad_pago)
        payments.append(p_dict)

    return {
        "payments": payments,
        "total_count": total_count,
        "resumen": {
            "cantidad_pagos": len(todos_los_pagos_del_rango),
            "total_aprobado": round(total_aprobado, 2),
            "total_pendiente": round(total_pendiente, 2),
            "total_anulado": round(total_anulado, 2),
            "total_neto": total_neto,  # F-COBRANZA-005: cuadra con extracto bancario
        }
    }


async def get_resumen_pagos_enrollment(enrollment_id: PydanticObjectId) -> dict:
    payments = await get_payments_by_enrollment(enrollment_id)

    resumen = {
        "total_pagos": len(payments),
        "pendientes": len([p for p in payments if p.estado_pago == EstadoPago.PENDIENTE]),
        "aprobados": len([p for p in payments if p.estado_pago == EstadoPago.APROBADO]),
        "rechazados": len([p for p in payments if p.estado_pago == EstadoPago.RECHAZADO]),
        "anulados": len([p for p in payments if p.estado_pago == EstadoPago.ANULADO]),
        "monto_total_aprobado": sum(
            p.cantidad_pago for p in payments if p.estado_pago == EstadoPago.APROBADO
        ),
    }

    # F-049 (2026-07-22, audio Sandra 9/7): cuando un estudiante paga de más
    # (ej: paga 300 cuando módulo cuesta 294), el sistema le genera un
    # "saldo a favor" que el estudiante VE en su resumen pero cobranza NO.
    # Agregar desglose por módulo + saldo a favor calculado.
    #
    # F-049-FIX (2026-07-28): el campo del modelo ModuloEstado es `costo`, NO
    # `monto`. La version original usaba `m.monto` que no existe y rompia
    # silenciosamente con `AttributeError`, dejando el resumen sin desglose.
    try:
        enrollment = await Enrollment.get(enrollment_id)
        if enrollment:
            modulos_info = []
            for i, m in enumerate(enrollment.modulos or []):
                modulos_info.append({
                    "index": i,
                    "nombre": m.nombre or f"Módulo {i + 1}",
                    "monto": float(m.costo or 0),  # F-049-FIX: `costo` es el campo correcto
                    "monto_pagado": float(m.monto_pagado or 0),
                    "saldo_modulo": round(float(m.costo or 0) - float(m.monto_pagado or 0), 2),
                    "pagado": (m.monto_pagado or 0) >= (m.costo or 0),
                })

            total_a_pagar = float(enrollment.total_a_pagar or 0)
            total_pagado = float(enrollment.total_pagado or 0)
            # F-049: si total_pagado > total_a_pagar, hay saldo a favor
            saldo_a_favor = round(max(0.0, total_pagado - total_a_pagar), 2)
            saldo_pendiente_real = round(max(0.0, total_a_pagar - total_pagado), 2)

            resumen["modulos"] = modulos_info
            resumen["total_a_pagar"] = total_a_pagar
            resumen["total_pagado"] = total_pagado
            resumen["saldo_a_favor"] = saldo_a_favor
            resumen["saldo_pendiente"] = saldo_pendiente_real
    except Exception as e:
        # No romper el endpoint si algo falla al enriquecer
        print(f"[F-049 WARN] No se pudo enriquecer resumen con desglose: {e}")

    return resumen


async def create_caja_directo_payment(
    estudiante_id: PydanticObjectId,
    inscripcion_id: PydanticObjectId,
    cantidad_pago: float,
    admin_username: str,
    concepto: Optional[str] = None,
    numero_cuota: Optional[int] = None,
    remitente: Optional[str] = None,
    cuenta_destino: Optional[str] = None,
    # F-COBRANZA-026 (2026-07-22): Kevin pidio que TODOS los pagos requieran
    # comprobante, incluso los cobros directos en Caja. Si es None, lanzamos
    # ValueError.
    comprobante_url: Optional[str] = None
) -> Payment:
    """
    Registrar un pago físico directo en Caja realizado por cobranzas para un alumno.
    El pago se crea directamente como APROBADO e impacta el saldo del estudiante automáticamente.
    No requiere las credenciales del estudiante para procesar.

    F-COBRANZA-026: comprobante_url es OBLIGATORIO (foto del recibo/factura).
    """
    # F-COBRANZA-026: comprobante obligatorio incluso para cobros en Caja
    if not comprobante_url:
        raise ValueError(
            "El comprobante es obligatorio para registrar un cobro en Caja. "
            "Suba la foto del recibo/factura antes de continuar."
        )
    enrollment = await Enrollment.get(inscripcion_id)
    if not enrollment:
        raise ValueError(f"Inscripción {inscripcion_id} no encontrada")
        
    if enrollment.estudiante_id != estudiante_id:
        raise ValueError("La inscripción seleccionada no coincide con el estudiante")

    next_payment = await get_next_pending_payment(inscripcion_id)
    if not next_payment:
         raise ValueError("Esta inscripción ya tiene todos los pagos en proceso o aprobados.")

    # F-COBRANZA-015 (2026-07-21): glosa detallada por módulo(s) específico(s).
    if concepto:
        concepto_final = concepto
        cuota_final = numero_cuota if numero_cuota else next_payment["numero_cuota"]
    else:
        pagos_aprobados_pre = await Payment.find(
            Payment.inscripcion_id == inscripcion_id,
            Payment.estado_pago == EstadoPago.APROBADO
        ).to_list()
        # F-COBRANZA-020: ahora retorna (concepto, detalle, numero_cuota)
        concepto_final, detalle_final, cuota_final = _generar_glosa_detalle(
            enrollment, cantidad_pago, pagos_aprobados_pre
        )

    # AUDITORÍA (ALTO #4): mismo control de sobrepago que create_payment. El
    # cobro en Caja se crea directamente APROBADO, así que aquí el riesgo es
    # mayor (no hay paso de revisión posterior que lo detecte).
    if cantidad_pago > enrollment.saldo_pendiente + 1.0:
        raise ValueError(
            f"El monto a cobrar (Bs. {cantidad_pago}) supera el saldo pendiente de la inscripción "
            f"(Bs. {enrollment.saldo_pendiente}). Verifica el monto antes de registrar el cobro."
        )

    # Crear pago ya APROBADO naciendo en Caja
    payment = Payment(
        inscripcion_id=inscripcion_id,
        estudiante_id=estudiante_id,
        curso_id=enrollment.curso_id,
        metodo_pago="Caja",
        concepto=concepto_final,
        detalle=detalle_final,  # F-COBRANZA-020
        cantidad_pago=cantidad_pago,
        numero_cuota=cuota_final,
        numero_transaccion="Caja / Directo",
        comprobante_url=comprobante_url,  # F-COBRANZA-026
        remitente=remitente,
        banco="Caja Física",
        monto_comprobante=cantidad_pago,
        fecha_comprobante=utcnow_naive(),
        cuenta_destino=cuenta_destino or f"Caja Física - {admin_username}",
        estado_pago=EstadoPago.APROBADO
    )
    
    # Sellar la verificación automática de caja
    payment.fecha_verificacion = utcnow_naive()
    payment.verificado_por = admin_username
    
    await payment.insert()

    # Reestructuración Financiera (Algoritmo de cascada Waterfall)
    await enrollment_service.actualizar_saldo_enrollment(
        enrollment_id=inscripcion_id,
        monto_pago_aprobado=cantidad_pago
    )

    # Registrar Auditoría inmutable de caja
    await _registrar_auditoria_financiera(
        accion="COBRO DIRECTO EN CAJA",
        payment_id=payment.id,
        estudiante_id=estudiante_id,
        monto=cantidad_pago,
        admin_username=admin_username,
        detalles=f"Cobro directo en caja procesado por {admin_username}. Concepto: {concepto_final}"
    )

    # Notificar al alumno de inmediato en su buzón transaccional
    try:
        from services.notification_service import create_notification
        await create_notification(
            destinatario_id=estudiante_id,
            tipo_destinatario="student",
            titulo="Pago Registrado en Caja",
            mensaje=f"Se ha registrado un pago directo en Caja por Bs. {cantidad_pago} para el concepto '{concepto_final}'. El pago ha sido aprobado automáticamente.",
            tipo_alerta="success",
            ruta="/app/payments",
            referencia_tipo="payment",
            referencia_id=payment.id
        )
    except Exception as e:
        print(f"Error al notificar pago directo en caja: {str(e)}")

    return payment