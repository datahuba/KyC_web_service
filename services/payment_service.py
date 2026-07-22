"""
Servicio de Pagos (Payments)
============================

Lógica de negocio para pagos, incluyendo soporte de métodos en Caja,
Auditoría y Algoritmo de Prorrateo.
"""

from typing import List, Optional
import asyncio
from datetime import datetime, timedelta
from models.payment import Payment
from models.enrollment import Enrollment
from models.student import Student
from models.course import Course
from models.enums import EstadoPago
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

        estudiante_id = _get(payment, "estudiante_id")
        inscripcion_id = _get(payment, "inscripcion_id")

        student = students_map.get(estudiante_id)
        nombre_estudiante = student.nombre if student and student.nombre else "Sin nombre"

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
    skip_ownership_check: bool = False
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
        existing_transaction = await Payment.find_one(
            Payment.numero_transaccion == payment_in.numero_transaccion,
            Payment.estado_pago != EstadoPago.RECHAZADO
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
        # Si NO se auto-aprueba, retornamos ya — los efectos colaterales
        # (actualizar saldo, auditoría APROBACION) se ejecutan cuando
        # el coord. financiero apruebe el pago explícitamente.
        return payment

    # ========================================================================
    # F-COBRANZA-004: Efectos colaterales de la aprobación automática
    # (los mismos que tendría aprobar_pago manualmente)
    # ========================================================================

    # 1) Actualizar saldo de la inscripción
    try:
        await enrollment_service.actualizar_saldo_enrollment(
            enrollment_id=payment.inscripcion_id,
            monto_pago_aprobado=payment.cantidad_pago
        )
    except Exception as e:
        print(f"Error al actualizar saldo del enrollment tras auto-aprobación: {str(e)}")

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

    total_esperado = 0.0
    por_cobrar = 0.0
    cobros_pendientes = 0
    for e in enrollments:
        total_esperado += e.total_a_pagar or 0.0
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


async def get_reporte_caja(
    fecha_desde_dt: datetime,
    fecha_hasta_dt: datetime,
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

    total_count = await Payment.find(criteria).count()
    skip = (page - 1) * per_page
    payments_raw = await Payment.find(criteria).sort("-fecha_comprobante").skip(skip).limit(per_page).to_list()

    # Totales agregados sobre TODO el rango filtrado (no solo la página actual)
    todos_los_pagos_del_rango = await Payment.find(criteria).to_list()
    total_aprobado = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.APROBADO)
    total_pendiente = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.PENDIENTE)
    total_anulado = sum(p.cantidad_pago for p in todos_los_pagos_del_rango if p.estado_pago == EstadoPago.ANULADO)

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
    for p in payments_raw:
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