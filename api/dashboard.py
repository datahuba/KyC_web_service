import time
from fastapi import APIRouter, Depends
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment
from models.payment import Payment
from api.dependencies import require_staff

router = APIRouter()

# F-PERF-DASHBOARD-CACHE (2026-08-05, Kevin): cache in-memory del response
# de /dashboard/stats con TTL de 30s. La idea es que el dashboard carga
# lento porque hace 5+ queries (cursos, enrollments, payments, stats,
# descuentos, etc). Cacheando el response entero por 30s, el segundo
# request del mismo usuario tarda < 50ms en vez de 1-3s.
# Key: (user_id, scope_key). scope_key incluye cursos_asignados +
# rol + sub_rol, para invalidar el cache cuando el usuario cambia de
# scope (ej: le asignan un curso nuevo).
_DASHBOARD_CACHE: dict[str, tuple[float, dict]] = {}
DASHBOARD_CACHE_TTL = 30  # segundos

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
    """
    # F-PERF-DASHBOARD-CACHE: servir desde cache si existe y no expiro
    cached = _get_cached_dashboard(current_user)
    if cached is not None:
        return cached
    # Base query filters based on user's assigned courses if they are segmented
    course_query = {}
    if current_user.cursos_asignados:
        course_query = {"_id": {"$in": current_user.cursos_asignados}}
    
    # 1. Courses
    courses_total = await Course.find(course_query).count()
    courses_active = await Course.find(course_query, Course.activo == True).count()
    
    # If the user is restricted by courses, we need to filter students, enrollments and payments by those courses
    enrollment_query = {}
    payment_query = {}
    student_query = {}
    
    if current_user.cursos_asignados:
        enrollment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        payment_query = {"curso_id": {"$in": current_user.cursos_asignados}}
        student_query = {"lista_cursos_ids": {"$in": current_user.cursos_asignados}}
    
    # 2. Students
    students_total = await Student.find(student_query).count()
    students_active = await Student.find(student_query, Student.activo == True).count()

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

    # Tambien excluir historicos del conteo de pagos pendientes? NO:
    # los pagos ya cobrados de historicos son dinero real (total_ingresos),
    # deben contar. Solo excluimos los enrollments.

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
