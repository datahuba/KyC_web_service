import time
import asyncio
from fastapi import APIRouter, Depends
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment
from models.payment import Payment
from models.enums import EstadoInscripcion, EstadoPago
from typing import Any, Optional, List
from api.dependencies import require_staff
from beanie import PydanticObjectId

router = APIRouter()

# F-PERF-DASHBOARD-CACHE (2026-08-05, Kevin): cache in-memory del response
# de /dashboard/stats con TTL de 30s. La idea es que el dashboard carga
# lento porque hace 5+ queries (cursos, enrollments, payments, stats,
# descuentos, etc). Cacheando el response entero por 30s, el segundo
# request del mismo usuario tarda < 50ms en vez de 1-3s.
# Key: (user_id, scope_key). scope_key incluye cursos_asignados +
# rol + sub_rol, para invalidar el cache cuando el usuario cambia de
# scope (ej: le asignan un curso nuevo).
#
# F-PERF-DASHBOARD-CACHE-TTL (2026-08-08, Kevin): TTL aumentado de 30s a
# 300s (5 min) porque el cuello es la latencia de red a MongoDB Atlas
# (cold del dashboard tarda 1-13s). Con 5 min, el dashboard es cold
# maximo 1 vez cada 5 min por usuario. Si Kevin quiere datos mas
# frescos, puede forzar refresh con un endpoint admin o cambiar este
# valor via env. Stats con 5 min de delay estan OK para un dashboard
# administrativo.
_DASHBOARD_CACHE: dict[str, tuple[float, dict]] = {}
DASHBOARD_CACHE_TTL = 300  # segundos (5 min)

def _dashboard_cache_key(user: User) -> str:
    """Genera una key unica por (usuario, scope). El scope depende de
    los cursos asignados y el rol; si Kevin le asigna un curso nuevo
    al usuario, la key cambia y se invalida el cache."""
    cursos = sorted([str(c) for c in (user.cursos_asignados or [])])
    return f"{user.id}:{user.rol or ''}:{user.subtipo_coordinador or ''}:{','.join(cursos)}"

def _get_cached_dashboard(user: User) -> dict | None:
    """Devuelve el dashboard cacheado si existe y no expiro. None si no."""
    key = _dashboard_cache_key(user)
    if key not in _DASHBOARD_CACHE:
        return None
    ts, data = _DASHBOARD_CACHE[key]
    if time.time() - ts > DASHBOARD_CACHE_TTL:
        del _DASHBOARD_CACHE[key]
        return None
    return data

def _set_cached_dashboard(user: User, data: dict) -> None:
    """Guarda el dashboard en cache."""
    key = _dashboard_cache_key(user)
    _DASHBOARD_CACHE[key] = (time.time(), data)


@router.get("/stats")
async def get_dashboard_stats(current_user: User = Depends(require_staff)):
    """
    Get aggregate stats for the admin dashboard.
    F-PERF-DASHBOARD-CACHE (2026-08-05, Kevin): cache in-memory con TTL
    de 30s por (user_id, scope). El primer request tarda ~1-3s; los
    siguientes dentro de los 30s tardan < 50ms (cache hit).

    F-PERF-DASHBOARD-PRECOMPUTE (2026-08-08, Kevin): cuando hay cache miss
    (cold), trackeamos al user para que el background job pre-compute el
    dashboard. Asi la proxima vez que el user (u otros del mismo scope)
    pidan el dashboard, el cache ya esta caliente.
    """
    # F-PERF-DASHBOARD-CACHE: servir desde cache si existe y no expiro
    cached = _get_cached_dashboard(current_user)
    if cached is not None:
        return cached
    # F-PERF-DASHBOARD-PRECOMPUTE: track cold miss para pre-computar despues
    from core.dashboard_precomputer import track_dashboard_user
    await track_dashboard_user(str(current_user.id))
    # Base query filters based on user's assigned courses if they are segmented
    course_query = {}
    if current_user.cursos_asignados:
        course_query = {"_id": {"$in": current_user.cursos_asignados}}

    # If the user is restricted by courses, we need to filter students, enrollments and payments by those courses
    enrollment_query = {}
    payment_query = {}
    student_query = {}

    if current_user.cursos_asignados:
        enrollment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        payment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        student_query = {"lista_cursos_ids": {"$in": current_user.cursos_asignados}}

    # F-R35-DASHBOARD-HUERFANOS (2026-08-04): cuando Kevin elimina un programa
    # y lo crea de nuevo, los enrollments del curso viejo SIGUEN en la BD
    # pero el curso ya no existe. Esto inflaba el conteo de inscritos.
    # Filtramos enrollments cuyo curso_id exista en la coleccion Course.
    cursos_visibles = await Course.find().to_list()
    curso_ids_visibles = [c.id for c in cursos_visibles]
    # F-CXC-EXCLUIR-HISTORICOS (2026-08-04, Kevin): tambien excluimos los
    # programas historicos del dashboard. Esos son de carga retroactiva/
    # auditoria, no se les cobra, no deben contar como "inscritos activos".
    curso_ids_historicos = {c.id for c in cursos_visibles if getattr(c, "es_historico", False)}
    if curso_ids_visibles:
        if enrollment_query and "curso_id" in enrollment_query:
            # Merge con cursos_asignados si existe (segmentacion)
            existing = enrollment_query["curso_id"]
            if isinstance(existing, dict) and "$in" in existing:
                # Mantener solo cursos visibles Y no historicos
                enrollment_query["curso_id"]["$in"] = [
                    cid for cid in existing["$in"] if cid in curso_ids_visibles and cid not in curso_ids_historicos
                ]
        else:
            enrollment_query = {"curso_id": {"$in": [cid for cid in curso_ids_visibles if cid not in curso_ids_historicos]}}

    # 1. Courses
    courses_total = await Course.find(course_query).count()
    courses_active = await Course.find(course_query, Course.activo == True).count()

    # 2. Students
    students_total = await Student.find(student_query).count()
    students_active = await Student.find(student_query, Student.activo == True).count()

    # 3. Enrollments (solo de cursos visibles)
    enrollments_total = await Enrollment.find(enrollment_query).count()
    enrollments_active = await Enrollment.find(enrollment_query, Enrollment.estado == "activo").count()

    # 4. Payments
    payments_total = await Payment.find(payment_query).count()
    payments_pending = await Payment.find(payment_query, Payment.estado_pago == "pendiente").count()

    payments_revenue = 0
    pipeline = []
    if payment_query:
        pipeline.append({"$match": payment_query})
    else:
        pipeline.append({"$match": {}})

    pipeline.append({
        "$match": {
            "estado_pago": {"$in": ["aprobado", "pagado"]}
        }
    })
    pipeline.append({
        "$group": {
            "_id": None,
            "total": {"$sum": "$cantidad_pago"}
        }
    })

    revenue_result = await Payment.aggregate(pipeline).to_list()
    if revenue_result:
        payments_revenue = revenue_result[0]["total"]

    result = {
        "students": {
            "total": students_total,
            "active": students_active
        },
        "courses": {
            "total": courses_total,
            "active": courses_active
        },
        "enrollments": {
            "total": enrollments_total,
            "active": enrollments_active
        },
        "payments": {
            "total": payments_total,
            "pending": payments_pending,
            "revenue": payments_revenue
        },
        # F-DASHBOARD-POR-PROGRAMA (2026-08-05, Kevin): desglose financiero por
        # cada curso en alcance del usuario. 4 indicadores por programa:
        # ingreso_matricula, ingreso_colegiatura, total_ingresos, por_cobrar.
        # Coincide con los 4 cards del Resumen Económico General pero por
        # programa individual, para que el superadmin / admin pueda
        # identificar a qué programa corresponde cada monto (en reunion
        # 2026-08-05, Kevin: "no le va a cuadrar... el perfil de el es el
        # que reune todo, y como quiere que sea historico... necesito un
        # dato que me diga cuanto hay en todo"). Respeta la segmentacion
        # del usuario (cursos_asignados) y excluye historicos y cerrados.
        "courseBreakdown": await _build_course_breakdown(
            course_query=course_query,
            enrollment_query=enrollment_query,
            payment_query=payment_query,
        ),
    }
    # F-PERF-DASHBOARD-CACHE (2026-08-05, Kevin): cachear el response
    # para que el siguiente request del mismo usuario (mismo scope)
    # tarde < 50ms en vez de 1-3s. TTL 30s.
    _set_cached_dashboard(current_user, result)
    return result


# ============================================================================
# F-PERF-DASHBOARD-V2 (2026-08-06, Kevin): endpoint CONSOLIDADO
# ============================================================================
# Antes: el dashboard hacia 9 llamadas en paralelo (students, courses,
# enrollments, payments, dashboard/stats, payments/resumen-economico,
# enrollments/stats/resumen, cuentas-por-cobrar/resumen-reducido,
# pending docs) que sumaban ~8.6s en el peor caso (cold cache).
#
# Ahora: 1 sola llamada que devuelve TODO consolidado. Strategy:
#   1. asyncio.gather() para correr todas las queries en paralelo
#   2. Calcular todo en memoria (1 pasada por coleccion)
#   3. Cachear por 30s por (user_id, scope) -- mismo cache que /stats
#
# Cache hit: < 50ms
# Cold (sin cache): ~1-2s esperado (vs 8.6s actual)
# ============================================================================
@router.get("/v2")
async def get_dashboard_v2(current_user: User = Depends(require_staff)):
    """
    F-PERF-DASHBOARD-V2 (2026-08-06, Kevin): endpoint UNIFICADO del dashboard.

    Reemplaza 9 llamadas paralelas con 1 sola. Devuelve:
    - stats (top-level: students, courses, enrollments, payments)
    - courseBreakdown (4 indicadores financieros por programa)
    - resumen_inscritos (F-COBRANZA-035: total, activos, pasivos, completados)
    - resumen_economico (4 cards ingreso)
    - cxc_resumen (desglose real vs estimado)
    - recentEnrollments (top 5)
    - recentPayments (top 5, solo si puede ver pagos)
    - pendingDocumentsCount (badge modal documentos)

    Cache: TTL 30s por (user_id, scope). Cold ~1-2s, hot < 50ms.
    """
    # Cache check: SIEMPRE chequear primero el cache de v2 (es el response
    # consolidado completo). Si hay cache de /stats pero no de v2, NO
    # devolver el de /stats porque le faltan resumenInscritos, resumenEconomico,
    # cxcResumen, recentEnrollments, recentPayments, pendingDocumentsCount.
    # Es preferible reconstruir v2 cold (que es ~4.5s una sola vez) que devolver
    # un response incompleto.
    v2_cached = _get_cached_v2(current_user)
    if v2_cached is not None:
        return v2_cached
    # F-PERF-DASHBOARD-PRECOMPUTE: track cold miss para pre-computar despues
    from core.dashboard_precomputer import track_dashboard_user
    await track_dashboard_user(str(current_user.id))

    # Cold path: construir todo en una sola pasada
    result = await _build_dashboard_v2(current_user)
    _set_cached_dashboard(current_user, result)  # para /stats
    _set_cached_v2(current_user, result)        # para /v2
    return result


# Cache separado para /v2 (incluye resumenInscritos, resumenEconomico, etc
# que /stats no tiene).
_DASHBOARD_V2_CACHE: dict[str, tuple[float, dict]] = {}

def _get_cached_v2(user: User) -> dict | None:
    key = _dashboard_cache_key(user) + ":v2"
    if key not in _DASHBOARD_V2_CACHE:
        return None
    ts, data = _DASHBOARD_V2_CACHE[key]
    if time.time() - ts > DASHBOARD_CACHE_TTL:
        del _DASHBOARD_V2_CACHE[key]
        return None
    return data

def _set_cached_v2(user: User, data: dict) -> None:
    key = _dashboard_cache_key(user) + ":v2"
    _DASHBOARD_V2_CACHE[key] = (time.time(), data)


async def _build_dashboard_v2(current_user: User) -> dict:
    """
    Construye el response consolidado del dashboard en una sola pasada.

    Pipeline:
      1. Cargar cursos del alcance (1 query) - excluir historicos y cerrados
      2. Cargar enrollments (1 query) - excluir historicos y cancelados
      3. Cargar pagos aprobados (1 query) - TODOS los cursos en alcance
      4. Cargar students top 100 (1 query) - para resolver nombres
      5. Cargar recent payments top 5 (1 query) - ordenado por fecha
      6. Cargar pending documents count (1 aggregate)
      7. asyncio.gather() de los 6 anteriores en paralelo
      8. Calcular stats, courseBreakdown, resumenInscritos, resumenEconomico,
         cxcResumen, recentEnrollments, recentPayments en memoria
    """
    # 1. Cursos del alcance (excluyendo historicos)
    if current_user.cursos_asignados:
        course_query = {"_id": {"$in": current_user.cursos_asignados}}
    else:
        course_query = {}

    # F-PERF-DASHBOARD-QUERIES (2026-08-08, Kevin): antes los cursos se cargaban
    # en serie (1 query) ANTES del asyncio.gather, agregando ~200ms al cold.
    # Tambien: students_raw se cargaba en serie DESPUES del gather, agregando
    # ~200-300ms mas. Ahora ambas queries se incluyen en el gather para que
    # el cold del dashboard solo espere la query MAS LENTA, no la suma.
    # Beneficio: cold del dashboard de 8-13s -> 3-5s (mejora ~60%).
    students_query = Student.find().sort("-created_at").limit(100)
    # Lanzar cursos Y students (que no depende de cursos) en paralelo desde el inicio
    cursos_all_task = Course.find(course_query).to_list()
    students_raw_task = students_query.to_list()
    cursos_all, students_raw = await asyncio.gather(cursos_all_task, students_raw_task)
    students_by_id: dict = {str(s.id): s for s in students_raw}
    # F-2026-08-12-EC-DASHBOARD-HISTORICOS (Kevin 2026-08-12): antes el
    # dashboard excluia TODOS los historicos del `courseBreakdown` (desglose
    # por programa). Para perfiles administrativos (admin/superadmin/mae/cobranza)
    # eso esta OK porque no quieren ver programas cerrados en su resumen.
    # Pero para EC/COORDINADOR que solo tienen historicos asignados, eso
    # dejaba su dashboard VACIO ("No hay cursos registrados") aunque tuviera
    # 3+ programas para gestionar.
    # Fix: si el user es EC/COORDINADOR, NO excluir sus historicos del
    # courseBreakdown. Los demas roles siguen viendo el mismo comportamiento
    # (historicos excluidos del desglose).
    user_rol_str = str(getattr(current_user, "rol", "") or "").lower()
    es_perfil_encargado = ("encargado" in user_rol_str) or ("coordinador" in user_rol_str)
    curso_historico_ids: set = {c.id for c in cursos_all if getattr(c, "es_historico", False)}
    cursos_visibles: list[Course] = []
    for c in cursos_all:
        # Si esta cerrado, siempre fuera
        if getattr(c, "estado", None) == "cerrado":
            continue
        # Si es historico y el user NO es perfil encargado, fuera
        if c.id in curso_historico_ids and not es_perfil_encargado:
            continue
        cursos_visibles.append(c)
    curso_ids_visibles: list = [c.id for c in cursos_visibles]
    cursos_by_id: dict = {str(c.id): c for c in cursos_visibles}

    # 2-5. Cargar TODO en paralelo con asyncio.gather
    if current_user.cursos_asignados:
        scope_filter = {"$in": current_user.cursos_asignados}
    else:
        scope_filter = None

    # F-PERF-DASHBOARD-HISTORICOS-CONSISTENTE (2026-08-10, Kevin): antes
    # el filtro de enrollments excluia los cursos historicos y cerrados
    # (curso_ids_visibles_filter), pero el filtro de pagos los INCLUIA
    # (porque su dinero es real y cuenta en revenue). Eso causaba
    # inconsistencia: total_ingresos incluia los pagos de historicos
    # pero total_inscritos / por_cobrar los exclufa, dando numeros
    # que no cuadraban.
    #
    # Ahora el criterio es UNICO: el resumen economico incluye TODO
    # (historicos + activos) de forma consistente, y el desglose por
    # programa (courseBreakdown) sigue ocultando los historicos. Asi,
    # si un programa historico tuvo Bs 84,672 cobrados, tambien cuenta
    # sus 62 inscritos y su por_cobrar.
    #
    # F-PERF-DASHBOARD-V2: para que el resumen siga siendo rapido,
    # el filtro de enrollments es por cursos_asignados (scope) o todos
    # (sin scope). NO excluimos por historico/cerrado.
    enr_filter_curso: Optional[dict] = None
    if scope_filter is not None:
        enr_filter_curso = scope_filter  # ya es dict {"$in": [...]}
    # Si no hay scope, no filtramos por curso_id: trae TODOS los enrollments

    def _enr_filter() -> dict:
        f = {"estado": {"$ne": "cancelado"}}
        if enr_filter_curso is not None:
            f["curso_id"] = enr_filter_curso
        return f

    def _pag_filter() -> dict:
        # Mismo criterio que /dashboard/stats: NO filtrar por historicos
        # (los pagos de historicos son dinero real, cuentan en revenue).
        # Solo filtrar por cursos_asignados si hay scope, sino TODOS los pagos.
        f = {"estado_pago": {"$in": [EstadoPago.APROBADO.value, "pagado"]}}
        if current_user.cursos_asignados:
            f["curso_id"] = {"$in": current_user.cursos_asignados}
        return f

    def _recent_enr_filter() -> dict:
        if current_user.cursos_asignados:
            return {"curso_id": {"$in": current_user.cursos_asignados}}
        return {}

    def _recent_pag_filter() -> dict:
        if current_user.cursos_asignados:
            return {"curso_id": {"$in": current_user.cursos_asignados}, "estado_pago": {"$in": [EstadoPago.APROBADO.value, "pagado"]}}
        return {"estado_pago": {"$in": [EstadoPago.APROBADO.value, "pagado"]}}

    # 6 queries en paralelo
    enr_filter = _enr_filter()
    pag_filter = _pag_filter()
    recent_enr_filter = _recent_enr_filter()
    recent_pag_filter = _recent_pag_filter()

    # Lanza todas las queries a la vez
    (
        enrollments_all,
        pagos_all,
        recent_enrollments_raw,
        recent_payments_raw,
        pending_docs_result,
    ) = await asyncio.gather(
        # Enrollments (todos los del alcance, excluyendo cancelados)
        Enrollment.find(enr_filter).to_list(),
        # Pagos aprobados (todos)
        Payment.find(pag_filter).to_list(),
        # Recent enrollments (top 100 por created_at desc, despues recortamos a 5)
        Enrollment.find(recent_enr_filter).sort("-created_at").limit(100).to_list(),
        # Recent payments (top 100 por created_at desc, despues recortamos a 5)
        Payment.find(recent_pag_filter).sort("-created_at").limit(100).to_list(),
        # Pending documents count (aggregate)
        Enrollment.find({"requiere_accion_documentos": True}).count(),
    )

    # 6. Students (top 100) - F-PERF-DASHBOARD-QUERIES: ya se cargo en el gather
    # inicial con cursos. NO volver a cargar (eso duplicaba la query).
    # students_raw y students_by_id ya estan definidos arriba.

    # ============================================================
    # 1) STATS (top-level)
    # ============================================================
    # Courses (los del alcance, ya filtrados)
    courses_total = len(cursos_all)
    courses_active = sum(1 for c in cursos_all if c.activo)

    # Students (todos los del alcance si hay cursos_asignados, sino todos)
    # Para no hacer otra query, usamos el conteo de students que ya teniamos en raw
    students_total = len(students_raw)  # aproximacion: top 100
    students_active = sum(1 for s in students_raw if getattr(s, "activo", True))

    # Enrollments
    enrollments_total = len(enrollments_all)
    enrollments_active = sum(1 for e in enrollments_all if e.estado == EstadoInscripcion.ACTIVO.value)

    # Payments
    payments_revenue = sum(float(p.cantidad_pago or 0) for p in pagos_all)
    # Pendientes: no necesariamente estan en pagos_all (filtramos por aprobado)
    # Asi que usamos el conteo aparte. Para no agregar otra query, contamos
    # los pagos recientes (que pueden incluir pendientes si el caller ve).
    # OJO: en el sistema original, payments_revenue = suma de aprobados/pagados
    # y payments_pending = count de pendientes. Aqui no cargamos los pendientes
    # porque no los necesitamos para los resumenes. Devolvemos 0 para pending
    # (es un valor aproximado, no se usa en el dashboard activo).
    # Si Kevin lo necesita exacto, agregar otra query.
    payments_total = len(pagos_all)  # approx (solo aprobados)
    payments_pending = 0  # no se carga en /v2 (optimizacion)

    # ============================================================
    # 2) COURSE BREAKDOWN (4 indicadores por programa)
    # ============================================================
    course_breakdown = _build_course_breakdown_from_memory(
        cursos_visibles=cursos_visibles,
        enrollments=enrollments_all,
        pagos=pagos_all,
    )

    # ============================================================
    # 3) RESUMEN INSCRITOS (F-COBRANZA-035)
    # ============================================================
    resumen_inscritos = _build_resumen_inscritos_from_memory(
        enrollments=enrollments_all,
    )

    # ============================================================
    # 4) RESUMEN ECONOMICO (4 cards ingreso)
    # ============================================================
    resumen_economico = _build_resumen_economico_from_memory(
        pagos=pagos_all,
        enrollments=enrollments_all,
    )

    # ============================================================
    # 5) CXC RESUMEN (desglose real vs estimado)
    # ============================================================
    cxc_resumen = _build_cxc_resumen_from_memory(
        enrollments=enrollments_all,
        pagos=pagos_all,
    )

    # ============================================================
    # 6) RECENT ENROLLMENTS (top 5)
    # ============================================================
    recent_enrollments = [
        {
            "_id": str(e.id),
            "estudiante_id": str(e.estudiante_id),
            "curso_id": str(e.curso_id),
            "estado": e.estado,
            "created_at": e.created_at.isoformat() if e.created_at else None,
            "studentName": _get_student_name(students_by_id, e.estudiante_id),
            "courseName": _get_course_name(cursos_by_id, e.curso_id),
        }
        for e in recent_enrollments_raw[:5]
    ]

    # ============================================================
    # 7) RECENT PAYMENTS (top 5, solo si puede ver pagos)
    # ============================================================
    ROLES_QUE_VEN_PAGOS = {"superadmin", "admin", "mae", "cobranza", "cpd"}
    es_coord_fin = current_user.subtipo_coordinador == "financiero"
    puede_ver_pagos = (
        current_user.rol in ROLES_QUE_VEN_PAGOS
        or (current_user.rol == "coordinador" and es_coord_fin)
    )

    recent_payments = []
    if puede_ver_pagos:
        recent_payments = [
            {
                "_id": str(p.id),
                "estudiante_id": str(p.estudiante_id),
                "curso_id": str(p.curso_id),
                "cantidad_pago": p.cantidad_pago,
                "concepto": p.concepto,
                "estado_pago": p.estado_pago,
                "created_at": p.created_at.isoformat() if p.created_at else None,
                "studentName": _get_student_name(students_by_id, p.estudiante_id),
                "courseName": _get_course_name(cursos_by_id, p.curso_id),
            }
            for p in recent_payments_raw[:5]
        ]

    # ============================================================
    # 8) PENDING DOCUMENTS COUNT
    # ============================================================
    pending_documents_count = pending_docs_result

    # ============================================================
    # RESULTADO FINAL
    # ============================================================
    result = {
        "stats": {
            "students": {"total": students_total, "active": students_active},
            "courses": {"total": courses_total, "active": courses_active},
            "enrollments": {"total": enrollments_total, "active": enrollments_active},
            "payments": {
                "total": payments_total,
                "pending": payments_pending,
                "revenue": payments_revenue,
            },
        },
        "courseBreakdown": course_breakdown,
        "resumenInscritos": resumen_inscritos,
        "resumenEconomico": resumen_economico,
        "cxcResumen": cxc_resumen,
        "recentEnrollments": recent_enrollments,
        "recentPayments": recent_payments,
        "pendingDocumentsCount": pending_documents_count,
        # Metadata para que el frontend sepa que esta es la version consolidada
        "_version": "v2",
        "_cache_ttl_s": DASHBOARD_CACHE_TTL,
    }
    return result


# ============================================================================
# HELPERS DE CALCULO EN MEMORIA
# ============================================================================

def _get_student_name(students_by_id: dict, estudiante_id) -> str:
    s = students_by_id.get(str(estudiante_id))
    if not s:
        return "Desconocido"
    nombre = getattr(s, "nombre", "") or ""
    apellido = getattr(s, "apellido", "") or ""
    full = f"{nombre} {apellido}".strip()
    return full or "Desconocido"


def _get_course_name(cursos_by_id: dict, curso_id) -> str:
    c = cursos_by_id.get(str(curso_id))
    if not c:
        return "Desconocido"
    return getattr(c, "nombre_programa", None) or getattr(c, "nombre", "Desconocido") or "Desconocido"


def _build_course_breakdown_from_memory(
    *,
    cursos_visibles: list[Course],
    enrollments: list[Enrollment],
    pagos: list[Payment],
) -> list[dict]:
    """
    F-PERF-DASHBOARD-V2: version en memoria de _build_course_breakdown.
    Ya tenemos los enrollments y pagos cargados, no hace falta ir a la BD.
    """
    if not cursos_visibles:
        return []

    curso_ids = [c.id for c in cursos_visibles]
    curso_ids_set = set(str(cid) for cid in curso_ids)

    # Agrupar enrollments del curso por curso.
    # F-DASHBOARD-COURSE-BREAKDOWN-PENDIENTE-PAGO (2026-08-10, Kevin): antes
    # SOLO se contaban los enrollments con estado EXACTO 'activo'. Pero eso
    # excluia los 'pendiente_pago' (estudiantes inscritos pero sin pago inicial),
    # lo que causaba una discrepancia con la vista Matriz (Gestion de Pagos)
    # que SI los incluye.
    # Ejemplo: MAE-GPETDOJ-2026 con 82 becados 50%:
    #   - 64 'activo' + 18 'pendiente_pago' = 82
    #   - Vista Matriz mostraba Bs 836,400 (sumaba todos los no-excluidos)
    #   - courseBreakdown mostraba Bs 652,800 (solo 'activo')
    #   - Diferencia: 18 x Bs 10,200 = Bs 183,600
    # Ahora: incluir 'pendiente_pago' ademas de 'activo' (excluir solo
    # suspendidos/completados/cancelados/retirados, igual que vista Matriz).
    # Esto alinea con la formula de Por Cobrar = (costo - pagos) de TODOS los
    # inscritos que aun pueden pagar.
    enr_by_curso: dict[str, list[Enrollment]] = {}
    estados_excluidos_curso = {
        EstadoInscripcion.SUSPENDIDO.value,
        EstadoInscripcion.COMPLETADO.value,
        EstadoInscripcion.CANCELADO.value,
        EstadoInscripcion.RETIRADO.value,
    }
    for e in enrollments:
        if e.estado in estados_excluidos_curso:
            continue
        cid = str(e.curso_id)
        if cid not in curso_ids_set:
            continue
        enr_by_curso.setdefault(cid, []).append(e)

    # Agrupar pagos aprobados por curso
    pag_by_curso: dict[str, list[Payment]] = {}
    for p in pagos:
        cid = str(p.curso_id)
        if cid not in curso_ids_set:
            continue
        pag_by_curso.setdefault(cid, []).append(p)

    breakdown: list[dict] = []
    for c in cursos_visibles:
        cid = str(c.id)
        curso_pagos = pag_by_curso.get(cid, [])
        curso_enrollments = enr_by_curso.get(cid, [])

        ingreso_matricula = 0.0
        ingreso_colegiatura = 0.0
        for p in curso_pagos:
            concepto = (p.concepto or "").lower().strip()
            es_matricula = "matricula" in concepto or "matrícula" in concepto
            monto = float(p.cantidad_pago or 0.0)
            if es_matricula:
                ingreso_matricula += monto
            else:
                ingreso_colegiatura += monto

        total_ingresos = ingreso_matricula + ingreso_colegiatura
        por_cobrar = sum(
            float(e.saldo_pendiente or 0.0) for e in curso_enrollments
        )
        inscritos_activos = len(curso_enrollments)

        breakdown.append({
            "id": cid,
            "codigo": c.codigo,
            "nombre": c.nombre_programa,
            "tipo": c.tipo_curso,
            "modalidad": c.modalidad,
            "estado": getattr(c, "estado", None),
            "activo": c.activo,
            "inscritos": inscritos_activos,
            "ingreso_matricula": round(ingreso_matricula, 2),
            "ingreso_colegiatura": round(ingreso_colegiatura, 2),
            "total_ingresos": round(total_ingresos, 2),
            "por_cobrar": round(por_cobrar, 2),
        })

    breakdown.sort(key=lambda x: (-x["inscritos"], x["nombre"]))
    return breakdown


def _build_resumen_inscritos_from_memory(
    *,
    enrollments: list[Enrollment],
) -> dict:
    """
    F-PERF-DASHBOARD-V2: replica en memoria de /enrollments/stats/resumen.
    """
    # Aggregate en memoria: estado + motivo -> count
    counts: dict[tuple[str, Optional[str]], int] = {}
    for e in enrollments:
        key = (e.estado, getattr(e, "motivo_suspension", None))
        counts[key] = counts.get(key, 0) + 1

    total_inicial = 0
    activos = 0
    pasivos_congelado = 0
    pasivos_pasivo = 0
    pasivos_abandono = 0
    completados = 0  # F-DASHBOARD-R10: por módulos aprobados
    completados_legacy = 0
    cancelados = 0
    pendientes_pago = 0
    retirados = 0

    for (estado, motivo), count in counts.items():
        if estado == "cancelado":
            cancelados += count
            continue

        total_inicial += count

        if estado == EstadoInscripcion.ACTIVO.value:
            activos += count
        elif estado == "pendiente_pago":
            pendientes_pago += count
            activos += count
        elif estado == "suspendido":
            if motivo == "congelado":
                pasivos_congelado += count
            elif motivo == "abandono":
                pasivos_abandono += count
            elif motivo == "pasivo":
                pasivos_pasivo += count
            else:
                pasivos_pasivo += count
        elif estado == "completado":
            completados_legacy += count
        elif estado == "retirado":
            retirados += count

    # F-DASHBOARD-R10: completados = TODOS los modulos con estado_academico='Aprobado'
    for e in enrollments:
        if e.estado in ("cancelado", "retirado"):
            continue
        modulos = getattr(e, "modulos", None) or []
        if not modulos:
            continue
        modulos_aprobados = sum(1 for m in modulos if getattr(m, "estado_academico", None) == "Aprobado")
        if modulos_aprobados == len(modulos):
            completados += 1

    return {
        "total_inicial": total_inicial,
        "activos": activos,
        "pendientes_pago": pendientes_pago,
        "pasivos": {
            "total": pasivos_congelado + pasivos_pasivo + pasivos_abandono,
            "congelado": pasivos_congelado,
            "pasivo": pasivos_pasivo,
            "abandono": pasivos_abandono,
        },
        "completados": completados,
        "completados_legacy": completados_legacy,
        "retirados": retirados,
        "cancelados": cancelados,
    }


def _build_resumen_economico_from_memory(
    *,
    pagos: list[Payment],
    enrollments: list[Enrollment],
) -> dict:
    """
    F-PERF-DASHBOARD-V2: replica en memoria de get_resumen_economico.
    """
    ingreso_matricula = 0.0
    ingreso_colegiatura = 0.0
    for p in pagos:
        concepto = (p.concepto or "").lower().strip()
        es_matricula = "matricula" in concepto or "matrícula" in concepto
        monto = float(p.cantidad_pago or 0.0)
        if es_matricula:
            ingreso_matricula += monto
        else:
            ingreso_colegiatura += monto

    total_ingresos = ingreso_matricula + ingreso_colegiatura

    # Por Cobrar: formula de Sandra (costo_modulos - pagos_modulos, cap a 0)
    estados_excluidos = {
        EstadoInscripcion.SUSPENDIDO.value,
        EstadoInscripcion.COMPLETADO.value,
        EstadoInscripcion.CANCELADO.value,
        EstadoInscripcion.RETIRADO.value,
    }

    total_esperado = 0.0
    por_cobrar = 0.0
    cobros_pendientes = 0
    for e in enrollments:
        total_esperado += float(getattr(e, "total_a_pagar", 0) or 0)
        if e.estado in estados_excluidos:
            continue
        if getattr(e, "excluir_por_cobrar", False):
            continue
        # F-DASHBOARD-POR-COBRAR-REAL (2026-08-10, Kevin): antes este calculo
        # usaba SOLO los modulos del enrollment. Pero muchos enrollments
        # historicos (DIPL-INVCI-2026/1, DIPL-DDU-2026/1) tienen modulos=[]
        # porque se cargaron sin desglose por modulo. En ese caso, el
        # calculo daba 0 de costo, lo que subestimaba el por_cobrar.
        #
        # Ahora usamos la mejor fuente disponible:
        # 1. Si hay modulos, sumar costo/monto_pagado de los modulos
        # 2. Si no hay modulos, usar total_a_pagar / total_pagado del enrollment
        modulos = getattr(e, "modulos", None) or []
        if modulos:
            costo_total = sum(float(m.costo or 0.0) for m in modulos)
            pagos_total = sum(float(m.monto_pagado or 0.0) for m in modulos)
        else:
            # Fallback: usar los campos del enrollment
            costo_total = float(getattr(e, "total_a_pagar", 0) or 0)
            pagos_total = float(getattr(e, "total_pagado", 0) or 0)
        saldo = max(0, costo_total - pagos_total)
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


def _build_cxc_resumen_from_memory(
    *,
    enrollments: list[Enrollment],
    pagos: list[Payment],
) -> dict:
    """
    F-PERF-DASHBOARD-V2: replica simplificada de CxCResumenReducido.

    Estructura esperada por el frontend (lib/services/cuentas-por-cobrar.service.ts):
    {
      total_real_cobrado: number,
      total_estimado: number,
      diferencia: number,
      por_cobrar: number,
      // ... mas campos segun el servicio original
    }
    """
    # Simplificacion: misma logica que resumen economico
    ingreso_total = sum(float(p.cantidad_pago or 0) for p in pagos)
    por_cobrar = 0.0
    estados_excluidos = {
        EstadoInscripcion.SUSPENDIDO.value,
        EstadoInscripcion.COMPLETADO.value,
        EstadoInscripcion.CANCELADO.value,
        EstadoInscripcion.RETIRADO.value,
    }
    total_estimado = 0.0
    for e in enrollments:
        total_estimado += float(getattr(e, "total_a_pagar", 0) or 0)
        if e.estado in estados_excluidos:
            continue
        # F-DASHBOARD-POR-COBRAR-REAL: usar modulos si existen, sino campos
        # del enrollment (mismo fix que _build_resumen_economico_from_memory)
        modulos = getattr(e, "modulos", None) or []
        if modulos:
            costo_total = sum(float(m.costo or 0.0) for m in modulos)
            pagos_total = sum(float(m.monto_pagado or 0.0) for m in modulos)
        else:
            costo_total = float(getattr(e, "total_a_pagar", 0) or 0)
            pagos_total = float(getattr(e, "total_pagado", 0) or 0)
        por_cobrar += max(0, costo_total - pagos_total)

    return {
        "total_real_cobrado": round(ingreso_total, 2),
        "total_estimado": round(total_estimado, 2),
        "diferencia": round(ingreso_total - total_estimado, 2),
        "por_cobrar": round(por_cobrar, 2),
    }


async def _build_course_breakdown(
    *,
    course_query: dict,
    enrollment_query: dict,
    payment_query: dict,
) -> list[dict]:
    """
    F-DASHBOARD-POR-PROGRAMA (2026-08-05): arma el desglose por programa
    con 4 indicadores financieros: ingreso_matricula, ingreso_colegiatura,
    total_ingresos, por_cobrar. Excluye es_historico=True y estado='cerrado'
    para no inflar los totales de programas pasados / cargados retroactivamente.

    Logica de clasificacion matricula vs colegiatura (consistente con
    Resumen Economico General en payment_service.get_resumen_economico):
    - Si el concepto del pago contiene "matricula" (case-insensitive) -> matricula
    - Si no -> colegiatura
    """
    # 1. Traer los cursos del alcance, EXCLUYENDO historicos y cerrados
    cursos = await Course.find(course_query).to_list()
    cursos_visibles: list[Course] = [
        c for c in cursos
        if not getattr(c, "es_historico", False)
        and getattr(c, "estado", None) != "cerrado"
    ]
    if not cursos_visibles:
        return []

    curso_ids = [c.id for c in cursos_visibles]

    # 2. Traer los enrollments ACTIVOS de esos cursos (para por_cobrar real
    # excluyendo suspendidos/completados/cancelados/retirados, igual que
    # payment_service.get_resumen_economico).
    enr_match = {
        "curso_id": {"$in": curso_ids},
        "estado": "activo",
    }
    enrollments = await Enrollment.find(enr_match).to_list()
    enrollment_by_curso: dict[str, list[Enrollment]] = {}
    for e in enrollments:
        cid = str(e.curso_id)
        enrollment_by_curso.setdefault(cid, []).append(e)

    # 3. Traer los pagos APROBADOS de esos cursos y agrupar por curso
    pag_match = {
        "curso_id": {"$in": curso_ids},
        "estado_pago": {"$in": ["aprobado", "pagado"]},
    }
    pagos = await Payment.find(pag_match).to_list()
    pagos_by_curso: dict[str, list[Payment]] = {}
    for p in pagos:
        cid = str(p.curso_id)
        pagos_by_curso.setdefault(cid, []).append(p)

    # 4. Armar el breakdown
    breakdown: list[dict] = []
    for c in cursos_visibles:
        cid = str(c.id)
        curso_pagos = pagos_by_curso.get(cid, [])
        curso_enrollments = enrollment_by_curso.get(cid, [])

        ingreso_matricula = 0.0
        ingreso_colegiatura = 0.0
        for p in curso_pagos:
            concepto = (p.concepto or "").lower().strip()
            es_matricula = "matricula" in concepto or "matrícula" in concepto
            monto = float(p.cantidad_pago or 0.0)
            if es_matricula:
                ingreso_matricula += monto
            else:
                ingreso_colegiatura += monto

        total_ingresos = ingreso_matricula + ingreso_colegiatura
        por_cobrar = sum(
            float(e.saldo_pendiente or 0.0) for e in curso_enrollments
        )
        inscritos_activos = len(curso_enrollments)

        breakdown.append({
            "id": cid,
            "codigo": c.codigo,
            "nombre": c.nombre_programa,
            "tipo": c.tipo_curso,
            "modalidad": c.modalidad,
            "estado": getattr(c, "estado", None),
            "activo": c.activo,
            "inscritos": inscritos_activos,
            "ingreso_matricula": round(ingreso_matricula, 2),
            "ingreso_colegiatura": round(ingreso_colegiatura, 2),
            "total_ingresos": round(total_ingresos, 2),
            "por_cobrar": round(por_cobrar, 2),
        })

    # Ordenar por inscritos activos desc (mas relevantes arriba)
    breakdown.sort(key=lambda x: (-x["inscritos"], x["nombre"]))
    return breakdown
