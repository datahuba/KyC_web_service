"""
F-R35-FASE-3: Reporte consolidado transversal de inconsistencias de datos

Endpoint: GET /api/v1/admin/data-health

Detecta 14 tipos de inconsistencias en los datos del sistema:
1. Documentos en BD que la UI dice que no están subidos
2. Enrollments sin curso/programa asociado (huérfanos)
3. Estudiantes sin enrollment (huérfanos)
4. Módulos con notas fuera de rango
5. Becados con pagos que no cuadran
6. Históricos mal clasificados
7. Pasivos vs congelados vs retiros inconsistentes
8. Pagos duplicados
9. Descuentos fuera de rango
10. Pagos anulados con enrollment activo
11. Costo total vs suma de módulos no cuadra
12. Matrícula pagada pero estado pendiente_pago
13. Resoluciones faltantes en programas activos
14. Encargado inactivo con cursos asignados

Solo superadmin puede ver este reporte (decisión de Kevin 2026-08-07).
Cache 30s para soportar refresh cada 30s del frontend.
Performance: < 1s con 245 enrollments + 100 pagos + 5 cursos.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, Query, HTTPException
from beanie import PydanticObjectId
from collections import Counter

from models import (
    Course, Student, Enrollment, Payment, Discount, User
)
from models.enums import EstadoInscripcion, EstadoPago
from api.auth import get_current_superadmin
from core.timezone_utils import utcnow_naive

router = APIRouter(prefix="/admin", tags=["admin-data-health"])

# Cache simple de 30s (memoria, suficiente para 1 usuario superadmin)
_CACHE = {"timestamp": None, "data": None}
_CACHE_TTL_S = 30


# ============================================================================
# DEFINICION DE LOS 14 CHECKS
# ============================================================================

CHECK_DEFS = [
    {"tipo": "docs_huerfanos", "severidad": "alta", "titulo": "Documentos en BD que la UI dice que no están", "icono": "file"},
    {"tipo": "enrollment_huerfano", "severidad": "alta", "titulo": "Enrollments sin curso/programa asociado", "icono": "link-broken"},
    {"tipo": "student_sin_enrollment", "severidad": "media", "titulo": "Estudiantes sin ningún enrollment", "icono": "user-x"},
    {"tipo": "notas_fuera_rango", "severidad": "media", "titulo": "Módulos con notas fuera de rango", "icono": "alert-triangle"},
    {"tipo": "becados_mal", "severidad": "alta", "titulo": "Becados con pagos que no cuadran", "icono": "badge"},
    {"tipo": "historicos_mal", "severidad": "media", "titulo": "Históricos mal clasificados", "icono": "archive"},
    {"tipo": "pasivos_inconsistentes", "severidad": "media", "titulo": "Pasivos vs congelados vs retiros inconsistentes", "icono": "shuffle"},
    {"tipo": "pagos_duplicados", "severidad": "alta", "titulo": "Pagos duplicados (mismo estudiante+concepto+día)", "icono": "copy"},
    {"tipo": "descuentos_mal", "severidad": "alta", "titulo": "Descuentos fuera de rango", "icono": "percent"},
    {"tipo": "pagos_anulados_activo", "severidad": "alta", "titulo": "Pagos anulados con enrollment activo", "icono": "x-circle"},
    {"tipo": "costo_vs_modulos", "severidad": "media", "titulo": "Costo total vs suma de módulos no cuadra", "icono": "calculator"},
    {"tipo": "matricula_pagada_pendiente", "severidad": "media", "titulo": "Matrícula pagada pero enrollment pendiente_pago", "icono": "alert-circle"},
    {"tipo": "resolucion_faltante", "severidad": "media", "titulo": "Resoluciones faltantes en programas activos", "icono": "file-text"},
    {"tipo": "encargado_inactivo", "severidad": "baja", "titulo": "Encargado de curso inactivo con cursos asignados", "icono": "user-minus"},
]


# ============================================================================
# CHECKS (uno por cada tipo de inconsistencia)
# ============================================================================

async def check_docs_huerfanos(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 1: Documentos en BD que la UI dice que no están"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "requisitos": {"$exists": True, "$ne": []}}
    ).limit(500).to_list()
    for enr in enrollments:
        for req in (enr.requisitos or []):
            # Si el doc tiene archivo_url pero el sistema lo marca como pendiente
            if hasattr(req, 'archivo_url') and req.archivo_url and not req.cumple:
                inconsistencias.append({
                    "tipo": "docs_huerfanos",
                    "severidad": "alta",
                    "entidad_tipo": "enrollment",
                    "entidad_id": str(enr._id),
                    "estudiante_id": str(enr.estudiante_id) if hasattr(enr, 'estudiante_id') else None,
                    "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
                    "programa_id": str(enr.curso_id),
                    "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
                    "descripcion": f"Requisito '{req.nombre if hasattr(req, 'nombre') else "?"}' tiene archivo subido pero marca 'no cumple'",
                    "accion_sugerida": "marcar_cumple",
                    "metadata": {"requisito": req.nombre if hasattr(req, 'nombre') else "?"}
                })
    return inconsistencias


async def check_enrollment_huerfano(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 2: Enrollments sin curso/programa asociado"""
    inconsistencias = []
    # Enrollments con curso_id que NO está en programas_ids (huérfanos)
    orfanos = await Enrollment.find(
        {"$or": [{"curso_id": None}, {"curso_id": {"$nin": programas_ids}}]}
    ).limit(200).to_list()
    for enr in orfanos:
        inconsistencias.append({
            "tipo": "enrollment_huerfano",
            "severidad": "alta",
            "entidad_tipo": "enrollment",
            "entidad_id": str(enr._id),
            "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
            "programa_id": str(enr.curso_id) if enr.curso_id else None,
            "programa_codigo": "ORFANO",
            "descripcion": f"Enrollment huérfano (curso no existe o no está en ejecución)",
            "accion_sugerida": "revisar_y_asignar",
            "metadata": {"estado": str(enr.estado) if hasattr(enr, 'estado') else "?"}
        })
    return inconsistencias


async def check_student_sin_enrollment(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 3: Estudiantes sin ningún enrollment"""
    inconsistencias = []
    # Estudiantes inscritos en programas en ejecución
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}}
    ).limit(500).to_list()
    student_ids_con_enrollment = set(str(e.estudiante_id) for e in enrollments if hasattr(e, 'estudiante_id') and e.estudiante_id)
    # Estudiantes totales
    students = await Student.find().limit(500).to_list()
    for s in students:
        if str(s._id) not in student_ids_con_enrollment:
            inconsistencias.append({
                "tipo": "student_sin_enrollment",
                "severidad": "media",
                "entidad_tipo": "student",
                "entidad_id": str(s._id),
                "estudiante_nombre": f"{s.nombre} {s.apellido_paterno if hasattr(s, 'apellido_paterno') else ''}".strip() or (s.nombre if hasattr(s, 'nombre') else "?"),
                "programa_codigo": "NINGUNO",
                "descripcion": f"Estudiante sin enrollment en programas activos",
                "accion_sugerida": "revisar",
                "metadata": {"carnet": s.carnet if hasattr(s, 'carnet') else None}
            })
    return inconsistencias


async def check_notas_fuera_rango(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 4: Módulos con notas fuera de rango"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "modulos": {"$exists": True, "$ne": []}}
    ).limit(500).to_list()
    for enr in enrollments:
        for m in (enr.modulos or []):
            nota = getattr(m, 'nota', None)
            if nota is not None and (nota < 0 or nota > 100):
                inconsistencias.append({
                    "tipo": "notas_fuera_rango",
                    "severidad": "media",
                    "entidad_tipo": "enrollment",
                    "entidad_id": str(enr._id),
                    "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
                    "programa_id": str(enr.curso_id),
                    "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
                    "descripcion": f"Módulo '{getattr(m, 'nombre', '?')}' tiene nota {nota} (fuera de 0-100)",
                    "accion_sugerida": "revisar_calificacion",
                    "metadata": {"modulo": getattr(m, 'nombre', '?'), "nota": nota}
                })
    return inconsistencias


async def check_becados_mal(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 5: Becados con pagos que no cuadran (PAGADO + costo sin cubrir)"""
    inconsistencias = []
    # Becas al 100% deberían tener costo cubierto
    discounts = await Discount.find({"porcentaje": {"$gte": 99}}).to_list()
    discount_ids_beca = [d._id for d in discounts]
    if discount_ids_beca:
        enrollments = await Enrollment.find(
            {"curso_id": {"$in": programas_ids}, "descuento_id": {"$in": discount_ids_beca}}
        ).limit(300).to_list()
        for enr in enrollments:
            # Verificar que el total_pagado cubra al menos el costo
            # (con beca 100%, no debería haber deuda)
            saldo = getattr(enr, 'saldo_pendiente', 0) or 0
            if saldo and saldo > 0:
                inconsistencias.append({
                    "tipo": "becados_mal",
                    "severidad": "alta",
                    "entidad_tipo": "enrollment",
                    "entidad_id": str(enr._id),
                    "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
                    "programa_id": str(enr.curso_id),
                    "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
                    "descripcion": f"Becado 100% con saldo pendiente de Bs {saldo}",
                    "accion_sugerida": "verificar_pagos_beca",
                    "metadata": {"saldo": saldo}
                })
    return inconsistencias


async def check_historicos_mal(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 6: Históricos mal clasificados (es_historico=True pero estado=en_ejecucion)"""
    inconsistencias = []
    cursos = await Course.find(
        {"es_historico": True, "estado_calculado": "en_ejecucion"}
    ).limit(50).to_list()
    for c in cursos:
        inconsistencias.append({
            "tipo": "historicos_mal",
            "severidad": "media",
            "entidad_tipo": "course",
            "entidad_id": str(c._id),
            "estudiante_nombre": None,
            "programa_id": str(c._id),
            "programa_codigo": c.codigo,
            "descripcion": f"Programa marcado como histórico pero estado_calculado=en_ejecucion. Tiene {(c.inscritos or []).__len__() if c.inscritos else 0} inscritos.",
            "accion_sugerida": "decidir_historico_o_activo",
            "metadata": {"inscritos": len(c.inscritos) if c.inscritos else 0}
        })
    return inconsistencias


async def check_pasivos_inconsistentes(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 7: Pasivos vs congelados vs retiros inconsistentes"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "estado": EstadoInscripcion.SUSPENDIDO}
    ).limit(300).to_list()
    for enr in enrollments:
        motivo = getattr(enr, 'motivo_suspension', None)
        estado = str(enr.estado)
        # SUSPENDIDO sin motivo, o motivo incoherente
        if estado == "SUSPENDIDO" and not motivo:
            inconsistencias.append({
                "tipo": "pasivos_inconsistentes",
                "severidad": "media",
                "entidad_tipo": "enrollment",
                "entidad_id": str(enr._id),
                "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
                "programa_id": str(enr.curso_id),
                "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
                "descripcion": f"SUSPENDIDO sin motivo_suspension definido",
                "accion_sugerida": "reclasificar",
                "metadata": {"motivo": None}
            })
    return inconsistencias


async def check_pagos_duplicados(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 8: Pagos duplicados (mismo estudiante + mismo concepto + mismo día)"""
    inconsistencias = []
    # Aggregate para encontrar duplicados
    pipeline = [
        {"$match": {
            "curso_id": {"$in": [str(p) for p in programas_ids]},
            "estado_pago": "aprobado"
        }},
        {"$group": {
            "_id": {
                "estudiante_id": "$estudiante_id",
                "concepto": "$concepto",
                "dia": {"$dateToString": {"format": "%Y-%m-%d", "date": "$fecha_subida"}}
            },
            "count": {"$sum": 1},
            "ids": {"$push": "$_id"},
            "monto_total": {"$sum": "$cantidad_pago"}
        }},
        {"$match": {"count": {"$gt": 1}}}
    ]
    db = Payment.get_motor_collection()
    cursor = db.aggregate(pipeline)
    dupes = await cursor.to_list(length=100)
    for d in dupes:
        inconsistencias.append({
            "tipo": "pagos_duplicados",
            "severidad": "alta",
            "entidad_tipo": "pago",
            "entidad_id": str(d["_id"]["ids"][0]),
            "estudiante_nombre": str(d["_id"]["estudiante_id"]),
            "programa_codigo": "MULTIPLE",
            "descripcion": f"{d['count']} pagos del mismo concepto en {d['_id']['dia']} (Bs {d['monto_total']:.2f} total)",
            "accion_sugerida": "anular_duplicados",
            "metadata": {"ids": [str(i) for i in d["_id"]["ids"]], "count": d["count"], "monto": d["monto_total"]}
        })
    return inconsistencias


async def check_descuentos_mal(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 9: Descuentos fuera de rango (>100% o negativos)"""
    inconsistencias = []
    descuentos = await Discount.find().to_list()
    for d in descuentos:
        if d.porcentaje < 0 or d.porcentaje > 100:
            inconsistencias.append({
                "tipo": "descuentos_mal",
                "severidad": "alta",
                "entidad_tipo": "discount",
                "entidad_id": str(d._id),
                "estudiante_nombre": None,
                "programa_codigo": d.nombre,
                "descripcion": f"Descuento '{d.nombre}' con porcentaje {d.porcentaje}% (fuera de 0-100)",
                "accion_sugerida": "corregir_porcentaje",
                "metadata": {"porcentaje": d.porcentaje}
            })
    return inconsistencias


async def check_pagos_anulados_activo(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 10: Pagos anulados con enrollment activo"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "estado": {"$in": ["ACTIVO", "PENDIENTE_PAGO", "COMPLETADO"]}}
    ).limit(300).to_list()
    for enr in enrollments:
        # Pagos anulados o rechazados
        pagos_malos = await Payment.find(
            {"inscripcion_id": enr._id, "estado_pago": {"$in": ["anulado", "rechazado"]}}
        ).limit(10).to_list()
        for p in pagos_malos:
            inconsistencias.append({
                "tipo": "pagos_anulados_activo",
                "severidad": "alta",
                "entidad_tipo": "pago",
                "entidad_id": str(p._id),
                "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
                "programa_id": str(enr.curso_id),
                "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
                "descripcion": f"Pago anulado/rechazado (Bs {p.cantidad_pago}) en enrollment {enr.estado}",
                "accion_sugerida": "revisar_consistencia",
                "metadata": {"estado_pago": p.estado_pago, "monto": p.cantidad_pago}
            })
    return inconsistencias


async def check_costo_vs_modulos(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 11: Costo total vs suma de módulos no cuadra"""
    inconsistencias = []
    for cid in programas_ids:
        c = await Course.get(cid)
        if not c: continue
        costo_total = getattr(c, 'costo_total_interno', 0) or 0
        modulos = getattr(c, 'modulos', []) or []
        suma_modulos = sum((m.costo for m in modulos if hasattr(m, 'costo')), 0)
        # Si difieren en más del 5%
        if costo_total > 0 and suma_modulos > 0 and abs(costo_total - suma_modulos) / max(costo_total, 1) > 0.05:
            inconsistencias.append({
                "tipo": "costo_vs_modulos",
                "severidad": "media",
                "entidad_tipo": "course",
                "entidad_id": str(c._id),
                "programa_id": str(c._id),
                "programa_codigo": c.codigo,
                "descripcion": f"Costo total (Bs {costo_total:.0f}) != suma de {len(modulos)} módulos (Bs {suma_modulos:.0f}), dif={abs(costo_total-suma_modulos):.0f}",
                "accion_sugerida": "revisar_costos",
                "metadata": {"costo_total": costo_total, "suma_modulos": suma_modulos}
            })
    return inconsistencias


async def check_matricula_pagada_pendiente(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 12: Matrícula pagada pero enrollment pendiente_pago"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "matricula_pagada": True, "estado": EstadoInscripcion.PENDIENTE_PAGO}
    ).limit(100).to_list()
    for enr in enrollments:
        inconsistencias.append({
            "tipo": "matricula_pagada_pendiente",
            "severidad": "media",
            "entidad_tipo": "enrollment",
            "entidad_id": str(enr._id),
            "estudiante_nombre": enr.estudiante_nombre if hasattr(enr, 'estudiante_nombre') else "?",
            "programa_id": str(enr.curso_id),
            "programa_codigo": enr.curso_codigo if hasattr(enr, 'curso_codigo') else "?",
            "descripcion": f"Matrícula pagada pero estado sigue PENDIENTE_PAGO",
            "accion_sugerida": "cambiar_a_activo",
            "metadata": {"estado_actual": str(enr.estado)}
        })
    return inconsistencias


async def check_resolucion_faltante(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 13: Resoluciones faltantes en programas activos"""
    inconsistencias = []
    for cid in programas_ids:
        c = await Course.get(cid)
        if not c: continue
        resolucion = getattr(c, 'resolucion_pdf_url', None)
        if not resolucion:
            inconsistencias.append({
                "tipo": "resolucion_faltante",
                "severidad": "media",
                "entidad_tipo": "course",
                "entidad_id": str(c._id),
                "programa_id": str(c._id),
                "programa_codigo": c.codigo,
                "descripcion": f"Programa activo sin PDF de resolución",
                "accion_sugerida": "subir_resolucion",
                "metadata": {"estado_calculado": str(c.estado_calculado) if hasattr(c, 'estado_calculado') else "?"}
            })
    return inconsistencias


async def check_encargado_inactivo(programas_ids: List[PydanticObjectId]) -> List[dict]:
    """Check 14: Encargado de curso inactivo con cursos asignados"""
    inconsistencias = []
    # Usuarios inactivos con cursos asignados
    users = await User.find(
        {"cursos_asignados": {"$exists": True, "$ne": []}, "activo": False}
    ).limit(50).to_list()
    for u in users:
        cursos_asig = u.cursos_asignados or []
        for cid in cursos_asig:
            cid_str = str(cid)
            if cid_str in [str(p) for p in programas_ids]:
                inconsistencias.append({
                    "tipo": "encargado_inactivo",
                    "severidad": "baja",
                    "entidad_tipo": "user",
                    "entidad_id": str(u._id),
                    "estudiante_nombre": u.nombre if hasattr(u, 'nombre') else u.username,
                    "programa_id": cid_str,
                    "programa_codigo": "ASIGNADO",
                    "descripcion": f"Usuario '{u.username}' está inactivo pero tiene cursos asignados activos",
                    "accion_sugerida": "reasignar_encargado",
                    "metadata": {"username": u.username}
                })
    return inconsistencias


# ============================================================================
# ENDPOINT PRINCIPAL
# ============================================================================

@router.get("/data-health")
async def get_data_health(
    current_user: User = Depends(get_current_superadmin),
    programa_id: Optional[str] = None,
    tipo: Optional[str] = None,  # comma-separated: "docs_huerfanos,enrollment_huerfano"
    severidad: Optional[str] = None,  # comma-separated: "critica,alta,media,baja"
):
    """
    Reporte consolidado de inconsistencias de datos.

    Cache 30s. Performance: < 1s con volumen actual.
    """
    # Cache check
    now = utcnow_naive()
    if _CACHE["timestamp"] and (now - _CACHE["timestamp"]).total_seconds() < _CACHE_TTL_S:
        data = _CACHE["data"]
        return _apply_filters(data, programa_id, tipo, severidad, current_user)

    # Programas en ejecución (no históricos) - el alcance que Kevin quiere
    cursos = await Course.find(
        {"es_historico": False, "estado_calculado": "en_ejecucion"}
    ).to_list()
    programas_ids = [c._id for c in cursos]

    # Ejecutar los 14 checks en paralelo
    checks = [
        check_docs_huerfanos(programas_ids),
        check_enrollment_huerfano(programas_ids),
        check_student_sin_enrollment(programas_ids),
        check_notas_fuera_rango(programas_ids),
        check_becados_mal(programas_ids),
        check_historicos_mal(programas_ids),
        check_pasivos_inconsistentes(programas_ids),
        check_pagos_duplicados(programas_ids),
        check_descuentos_mal(programas_ids),
        check_pagos_anulados_activo(programas_ids),
        check_costo_vs_modulos(programas_ids),
        check_matricula_pagada_pendiente(programas_ids),
        check_resolucion_faltante(programas_ids),
        check_encargado_inactivo(programas_ids),
    ]
    results = await asyncio.gather(*checks, return_exceptions=True)
    inconsistencias = []
    errores = []
    for r in results:
        if isinstance(r, list):
            inconsistencias.extend(r)
        elif isinstance(r, Exception):
            errores.append(str(r))

    # KPIs
    kpis = {
        "criticas": sum(1 for i in inconsistencias if i["severidad"] == "critica"),
        "altas": sum(1 for i in inconsistencias if i["severidad"] == "alta"),
        "medias": sum(1 for i in inconsistencias if i["severidad"] == "media"),
        "bajas": sum(1 for i in inconsistencias if i["severidad"] == "baja"),
        "total": len(inconsistencias),
    }
    kpis["por_tipo"] = dict(Counter(i["tipo"] for i in inconsistencias))

    # Filtros disponibles
    filtros = {
        "programas": [{"id": str(c._id), "codigo": c.codigo, "nombre": c.nombre_programa, "inscritos": len(c.inscritos) if c.inscritos else 0} for c in cursos],
        "tipos": [{"tipo": d["tipo"], "titulo": d["titulo"], "severidad": d["severidad"], "icono": d["icono"]} for d in CHECK_DEFS],
        "severidades": ["critica", "alta", "media", "baja"],
        "acciones_disponibles": [
            "marcar_cumple", "reclasificar", "cambiar_a_activo", "anular_duplicados",
            "corregir_porcentaje", "reasignar_encargado", "subir_resolucion",
            "verificar_pagos_beca", "recalcular", "revisar"
        ]
    }

    data = {
        "kpis": kpis,
        "inconsistencias": inconsistencias,
        "filtros": filtros,
        "programas_evaluados": len(cursos),
        "checks_ejecutados": 14,
        "errores_checks": errores,
        "timestamp": now.isoformat(),
        "_version": "r35-fase-3-v1",
        "_cache_ttl_s": _CACHE_TTL_S
    }

    # Guardar en cache
    _CACHE["timestamp"] = now
    _CACHE["data"] = data

    return _apply_filters(data, programa_id, tipo, severidad, current_user)


def _apply_filters(data, programa_id, tipo, severidad, current_user):
    """Aplica filtros opcionales sobre la data cacheada"""
    inconsistencias = data.get("inconsistencias", [])
    if programa_id:
        inconsistencias = [i for i in inconsistencias if i.get("programa_id") == programa_id]
    if tipo:
        tipos_filtrar = set(tipo.split(","))
        inconsistencias = [i for i in inconsistencias if i.get("tipo") in tipos_filtrar]
    if severidad:
        sevs_filtrar = set(severidad.split(","))
        inconsistencias = [i for i in inconsistencias if i.get("severidad") in sevs_filtrar]
    result = dict(data)
    result["inconsistencias"] = inconsistencias
    result["kpis_filtrados"] = {
        "criticas": sum(1 for i in inconsistencias if i.get("severidad") == "critica"),
        "altas": sum(1 for i in inconsistencias if i.get("severidad") == "alta"),
        "medias": sum(1 for i in inconsistencias if i.get("severidad") == "media"),
        "bajas": sum(1 for i in inconsistencias if i.get("severidad") == "baja"),
        "total": len(inconsistencias)
    }
    return result


# ============================================================================
# ACCIONES MASIVAS (con confirmación)
# ============================================================================

@router.post("/data-health/fix/{tipo_accion}")
async def fix_inconsistencia(
    tipo_accion: str,
    payload: dict,
    current_user: User = Depends(get_current_superadmin),
):
    """
    Aplica una accion correctiva a una inconsistencia.

    payload esperado: { "entidad_id": "...", "metadata": {...} }
    """
    entidad_id = payload.get("entidad_id")
    metadata = payload.get("metadata", {})
    if not entidad_id:
        raise HTTPException(400, "Falta entidad_id")

    if tipo_accion == "cambiar_a_activo":
        enr = await Enrollment.get(PydanticObjectId(entidad_id))
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        enr.estado = EstadoInscripcion.ACTIVO
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Enrollment {entidad_id} cambiado a ACTIVO"}

    elif tipo_accion == "reclasificar":
        # Reclasificar motivo_suspension
        nuevo_motivo = payload.get("motivo", "congelado")
        enr = await Enrollment.get(PydanticObjectId(entidad_id))
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        enr.motivo_suspension = nuevo_motivo
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Enrollment {entidad_id} reclasificado a {nuevo_motivo}"}

    elif tipo_accion == "marcar_cumple":
        # Marcar requisito como cumplido
        enr = await Enrollment.get(PydanticObjectId(entidad_id))
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        req_nombre = metadata.get("requisito")
        if not req_nombre:
            raise HTTPException(400, "Falta 'requisito' en metadata")
        requisitos = enr.requisitos or []
        for req in requisitos:
            if getattr(req, 'nombre', None) == req_nombre:
                req.cumple = True
                break
        enr.requisitos = requisitos
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Requisito '{req_nombre}' marcado como cumplido"}

    elif tipo_accion == "anular_duplicados":
        # Anular todos los pagos duplicados menos el primero
        ids = metadata.get("ids", [])
        if len(ids) < 2:
            raise HTTPException(400, "Se necesitan al menos 2 IDs")
        # Mantener el primero, anular el resto
        keep_id = ids[0]
        anulados = 0
        for pid in ids[1:]:
            pago = await Payment.get(PydanticObjectId(pid))
            if pago:
                pago.estado_pago = EstadoPago.ANULADO
                pago.motivo_rechazo = f"Anulado automáticamente por R35-FASE-3 (duplicado de {keep_id})"
                await pago.save()
                anulados += 1
        _invalidate_cache()
        return {"ok": True, "message": f"{anulados} pagos anulados, 1 mantenido", "mantenido": keep_id}

    elif tipo_accion == "decidir_historico_o_activo":
        decision = payload.get("decision")  # "marcar_historico" | "marcar_activo"
        c = await Course.get(PydanticObjectId(entidad_id))
        if not c:
            raise HTTPException(404, "Curso no encontrado")
        if decision == "marcar_historico":
            c.es_historico = True
        elif decision == "marcar_activo":
            c.es_historico = False
        await c.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Curso {c.codigo} marcado como {decision}"}

    elif tipo_accion == "corregir_porcentaje":
        nuevo = payload.get("porcentaje")
        if nuevo is None or nuevo < 0 or nuevo > 100:
            raise HTTPException(400, "Porcentaje inválido")
        d = await Discount.get(PydanticObjectId(entidad_id))
        if not d:
            raise HTTPException(404, "Descuento no encontrado")
        d.porcentaje = float(nuevo)
        await d.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Descuento {d.nombre} corregido a {nuevo}%"}

    elif tipo_accion == "subir_resolucion":
        # Solo se puede hacer via el endpoint normal de upload
        raise HTTPException(400, "Use el endpoint PUT /courses/{id}/resolucion")

    elif tipo_accion == "reasignar_encargado":
        raise HTTPException(400, "Use el endpoint PUT /courses/{id}/encargados")

    elif tipo_accion == "verificar_pagos_beca":
        # Recalcula el saldo pendiente del enrollment
        enr = await Enrollment.get(PydanticObjectId(entidad_id))
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        # Recalcular
        pagos_aprobados = await Payment.find(
            {"inscripcion_id": enr._id, "estado_pago": "aprobado"}
        ).to_list()
        total_pagado = sum(p.cantidad_pago for p in pagos_aprobados)
        costo_total = getattr(enr, 'costo_total', 0) or 0
        descuento = getattr(enr, 'descuento_efectivo', 0) or 0
        costo_con_descuento = costo_total * (1 - descuento / 100)
        nuevo_saldo = max(0, costo_con_descuento - total_pagado)
        enr.total_pagado = total_pagado
        enr.saldo_pendiente = nuevo_saldo
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Saldo recalculado: Bs {nuevo_saldo:.2f} (de {metadata.get('saldo_anterior', '?')})"}

    else:
        raise HTTPException(400, f"Accion {tipo_accion} no implementada")


def _invalidate_cache():
    """Invalida el cache de data-health"""
    _CACHE["timestamp"] = None
    _CACHE["data"] = None
