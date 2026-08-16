"""
F-R35-FASE-3: Reporte consolidado transversal de inconsistencias de datos

Endpoint: GET /api/v1/admin/data-health

Detecta 14 tipos de inconsistencias en los datos del sistema.
Solo superadmin (decision de Kevin 2026-08-07).
Cache 30s para soportar refresh cada 30s del frontend.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from beanie import PydanticObjectId
from collections import Counter

from models import (
    Course, Student, Enrollment, Payment, Discount, User
)
from models.user import UserRole
from models.enums import EstadoInscripcion, EstadoPago
from api.dependencies import get_current_user
from core.timezone_utils import utcnow_naive
from models.estado_programa import calcular_estado_actual

router = APIRouter(tags=["admin-data-health"])

# Cache simple de 30s
_CACHE = {"timestamp": None, "data": None}
_CACHE_TTL_S = 30


def require_superadmin(current_user: User = Depends(get_current_user)) -> User:
    """Solo superadmin puede ver el reporte de data-health"""
    if not isinstance(current_user, User):
        raise HTTPException(status_code=403, detail="Solo usuarios pueden acceder a /admin/data-health")
    if current_user.rol != UserRole.SUPERADMIN:
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin puede ver el reporte consolidado de inconsistencias"
        )
    return current_user


# ============================================================================
# DEFINICION DE LOS 14 CHECKS
# ============================================================================

CHECK_DEFS = [
    {"tipo": "docs_huerfanos", "severidad": "alta", "titulo": "Documentos en BD que la UI dice que no estan", "icono": "file"},
    {"tipo": "enrollment_huerfano", "severidad": "alta", "titulo": "Enrollments sin curso/programa asociado", "icono": "link-broken"},
    {"tipo": "student_sin_enrollment", "severidad": "media", "titulo": "Estudiantes sin ningun enrollment", "icono": "user-x"},
    {"tipo": "notas_fuera_rango", "severidad": "media", "titulo": "Modulos con notas fuera de rango", "icono": "alert-triangle"},
    {"tipo": "becados_mal", "severidad": "alta", "titulo": "Becados con pagos que no cuadran", "icono": "badge"},
    {"tipo": "historicos_mal", "severidad": "media", "titulo": "Historicos mal clasificados", "icono": "archive"},
    {"tipo": "pasivos_inconsistentes", "severidad": "media", "titulo": "Pasivos vs congelados vs retiros inconsistentes", "icono": "shuffle"},
    {"tipo": "pagos_duplicados", "severidad": "alta", "titulo": "Pagos duplicados (mismo estudiante+concepto+dia)", "icono": "copy"},
    {"tipo": "descuentos_mal", "severidad": "alta", "titulo": "Descuentos fuera de rango", "icono": "percent"},
    {"tipo": "pagos_anulados_activo", "severidad": "alta", "titulo": "Pagos anulados con enrollment activo", "icono": "x-circle"},
    {"tipo": "costo_vs_modulos", "severidad": "media", "titulo": "Costo total vs suma de modulos no cuadra", "icono": "calculator"},
    {"tipo": "matricula_pagada_pendiente", "severidad": "media", "titulo": "Matricula pagada pero enrollment pendiente_pago", "icono": "alert-circle"},
    {"tipo": "resolucion_faltante", "severidad": "media", "titulo": "Resoluciones faltantes en programas activos", "icono": "file-text"},
    {"tipo": "encargado_inactivo", "severidad": "baja", "titulo": "Encargado de curso inactivo con cursos asignados", "icono": "user-minus"},
]


# ============================================================================
# HELPERS
# ============================================================================

async def get_programas_en_ejecucion() -> List[Course]:
    """Retorna SOLO los programas en ejecucion (no historicos, no programados).
    Segun Kevin: 'los que estan en programas en ejecucion son los reales,
    los de historicos o en preinscripcion de programados no'."""
    todos = await Course.find_all().to_list()
    resultado = []
    for c in todos:
        # Calcular estado actual (con override)
        try:
            estado_actual = calcular_estado_actual(
                c.fecha_inicio,
                c.fecha_fin,
                getattr(c, 'estado_override', None),
            )
        except Exception:
            estado_actual = "desconocido"
        if estado_actual == "en_ejecucion" and not getattr(c, 'es_historico', False):
            resultado.append(c)
    return resultado


def to_id(obj) -> Optional[str]:
    """Convierte un objeto Beanie a su ID string"""
    if obj is None:
        return None
    if hasattr(obj, 'id') and obj.id is not None:
        return str(obj.id)
    if hasattr(obj, '_id') and obj._id is not None:
        return str(obj._id)
    return None


def prog_obj_ids_list(prog_ids: List[str]) -> list:
    """
    R35-FASE-3 FIX (2026-08-07): convierte la lista de IDs string a ObjectId.
    El campo curso_id en enrollments/payments se guarda como ObjectId en MongoDB.
    Si comparas con string, MongoDB NO matchea y el check falla silenciosamente.

    Uso:
        {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}}
        {"curso_id": {"$nin": prog_obj_ids_list(programas_ids)}}
    """
    from bson import ObjectId
    out = []
    for p in prog_ids:
        try:
            out.append(ObjectId(str(p)))
        except Exception:
            continue
    return out


# ============================================================================
# CHECKS (uno por cada tipo de inconsistencia)
# ============================================================================

async def check_docs_huerfanos(programas_ids: List[str]) -> List[dict]:
    """Check 1: Documentos en BD que la UI dice que no estan"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": programas_ids}, "requisitos": {"$exists": True, "$ne": []}}
    ).limit(500).to_list()
    for enr in enrollments:
        for req in (enr.requisitos or []):
            archivo = getattr(req, 'archivo_url', None)
            cumple = getattr(req, 'cumple', None)
            if archivo and not cumple:
                inconsistencias.append({
                    "tipo": "docs_huerfanos",
                    "severidad": "alta",
                    "entidad_tipo": "enrollment",
                    "entidad_id": to_id(enr),
                    "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
                    "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
                    "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
                    "descripcion": f"Requisito '{getattr(req, 'nombre', '?')}' tiene archivo subido pero marca 'no cumple'",
                    "accion_sugerida": "marcar_cumple",
                    "metadata": {"requisito": getattr(req, 'nombre', '?')}
                })
    return inconsistencias


async def check_enrollment_huerfano(programas_ids: List[str]) -> List[dict]:
    """Check 2: Enrollments sin curso/programa asociado

    R35-FASE-3 FIX (2026-08-07): el check usaba [str(p) for p in programas_ids]
    que son STRINGS, pero el campo curso_id en MongoDB se guarda como ObjectId.
    MongoDB NO matchea ObjectId con string en $nin, por lo que el check reportaba
    245 falsos huerfanos cuando en realidad solo 1 era real.

    Fix: usar bson.ObjectId para construir los IDs de la lista $nin.

    R35-FASE-3 FIX 2 (2026-08-07, Kevin): el check NO filtraba por estado,
    asi que contaba TODOS los huérfanos incluyendo los que ya habian sido
    retirados con la accion 'revisar_y_asignar'. Ahora filtra por
    estado != "retirado" para que el contador baje después de aplicar un fix.

    R35-FASE-3 FIX 3 (2026-08-07, Kevin): tambien excluye los enrollments
    cuyo curso es historico o programado. Decision Kevin: "esos programas
    son historicos, esas inscripciones a esos modulos no deberian quedar
    igual como datos historicos, no sirven para nada mas que ser datos
    historicos". Antes solo excluiamos cursos en ejecucion.
    """
    from bson import ObjectId
    inconsistencias = []

    # 1. Programas en ejecucion (excluidos = vigentes)
    prog_ejecucion_ids = []
    for p in programas_ids:
        try:
            prog_ejecucion_ids.append(ObjectId(str(p)))
        except Exception:
            continue

    # 2. Programas historicos (es_historico=True)
    # Decision Kevin 2026-08-07: estos enrollments NO son inconsistencias,
    # son datos historicos que se mantienen por valor historico.
    historicos = await Course.find({"es_historico": True}).to_list()
    prog_hist_ids = []
    for c in historicos:
        cid = c.id
        if cid:
            try:
                prog_hist_ids.append(ObjectId(str(cid)))
            except Exception:
                continue

    # 3. Programas programados (estado_calculado == "programado")
    # Tambien excluidos: son programas que aun no empezaron, sus enrollments
    # son legitimos pero no son "en ejecucion" todavia.
    prog_prog_ids = []
    for c in await Course.find_all().to_list():
        if c.id is None:
            continue
        if getattr(c, 'es_historico', False):
            continue
        try:
            estado = calcular_estado_actual(
                c.fecha_inicio,
                c.fecha_fin,
                getattr(c, 'estado_override', None),
            )
        except Exception:
            continue
        if estado == "programado":
            try:
                prog_prog_ids.append(ObjectId(str(c.id)))
            except Exception:
                continue

    # Combinamos todos los IDs validos a excluir
    all_valid_ids = prog_ejecucion_ids + prog_hist_ids + prog_prog_ids

    # 4. Query final: enrollments con curso_id None o fuera de los IDs validos,
    #    Y estado != "retirado" (para que el fix baje el contador)
    orfanos = await Enrollment.find({
        "$and": [
            {"$or": [{"curso_id": None}, {"curso_id": {"$nin": all_valid_ids}}]},
            {"estado": {"$ne": "retirado"}}
        ]
    }).limit(200).to_list()

    for enr in orfanos:
        inconsistencias.append({
            "tipo": "enrollment_huerfano",
            "severidad": "alta",
            "entidad_tipo": "enrollment",
            "entidad_id": to_id(enr),
            "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
            "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
            "programa_codigo": "ORFANO",
            "descripcion": f"Enrollment huerfano (curso no existe o no esta en ejecucion)",
            "accion_sugerida": "revisar_y_asignar",
            "metadata": {"estado": str(getattr(enr, 'estado', '?'))}
        })
    return inconsistencias


async def check_student_sin_enrollment(programas_ids: List[str]) -> List[dict]:
    """Check 3: Estudiantes sin ningun enrollment

    R35-FASE-3 FIX (2026-08-07): mismo bug de tipo que check_enrollment_huerfano.
    curso_id en enrollments es ObjectId, programas_ids eran strings -> MongoDB
    no matcheaba y el check fallaba.

    Approach: 2 queries (ObjectId) + diff en Python. Mas rapido y simple que
    $lookup aggregation (~870ms vs ~930ms en benchmarks).

    R35-FASE-3 FIX 2 (2026-08-08, Kevin): el check solo buscaba enrollments
    en programas en ejecucion, pero hay estudiantes con enrollment en
    programas historicos/programados que SI pagaron matricula y modulos.
    Esos aparecian como falsos positivos (238 inconsistencias). Ahora el
    check busca enrollments en CUALQUIER curso (sin importar el estado del
    curso), porque un estudiante con al menos un enrollment registrado
    no es "sin enrollment" aunque su curso sea historico o programado.
    Decisión Kevin 2026-08-08: "todos están con matrícula pagada todos
    han pagado sus módulos respectivos".

    R35-FASE-3 FIX 3 (2026-08-08, Kevin): ademas de la coleccion enrollments,
    el modelo Student tiene un campo `lista_cursos_ids` (List[PyObjectId])
    que mantiene la lista oficial de cursos del estudiante. Si el estudiante
    tiene al menos 1 curso en `lista_cursos_ids`, NO es inconsistente
    aunque no aparezca en la coleccion enrollments. Esto cubre casos donde
    el estudiante fue matriculado pero la coleccion enrollments no esta
    sincronizada (por bug en una importacion de excel o en el script de
    pagos). Decision Kevin 2026-08-08: el excel de pagos + el sistema de
    gestion de pagos SI registran la matricula del estudiante.
    """
    inconsistencias = []

    # Q1: TODOS los enrollments (sin filtrar por curso_id)
    # Si el estudiante tiene al menos 1 enrollment en cualquier curso,
    # NO es "sin enrollment" (puede estar en programa historico/programado).
    enrollments = await Enrollment.find_all().limit(5000).to_list()
    student_ids_con_enrollment = set()
    for e in enrollments:
        eid = to_id(e.estudiante_id) if e.estudiante_id else None
        if eid:
            student_ids_con_enrollment.add(eid)

    # Q2: todos los estudiantes
    students = await Student.find_all().limit(1000).to_list()
    for s in students:
        sid = to_id(s)
        if sid and sid not in student_ids_con_enrollment:
            # R35-FASE-3 FIX 3 (2026-08-08, Kevin): verificar tambien
            # lista_cursos_ids del Student. Si tiene al menos 1 curso,
            # NO es inconsistente (fuente de verdad oficial: la lista
            # se mantiene sincronizada con pagos y matricula).
            lista_cursos = getattr(s, 'lista_cursos_ids', None) or []
            if lista_cursos and len(lista_cursos) > 0:
                continue
            nombre = getattr(s, 'nombre', '') or ''
            apellido = getattr(s, 'apellido_paterno', '') or ''
            inconsistencias.append({
                "tipo": "student_sin_enrollment",
                "severidad": "media",
                "entidad_tipo": "student",
                "entidad_id": sid,
                "estudiante_nombre": f"{nombre} {apellido}".strip() or sid,
                "programa_codigo": "NINGUNO",
                "descripcion": f"Estudiante sin enrollment en programas activos",
                "accion_sugerida": "revisar",
                "metadata": {"carnet": getattr(s, 'carnet', None)}
            })
    return inconsistencias


async def check_notas_fuera_rango(programas_ids: List[str]) -> List[dict]:
    """Check 4: Modulos con notas fuera de rango"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}, "modulos": {"$exists": True, "$ne": []}}
    ).limit(500).to_list()
    for enr in enrollments:
        for m in (enr.modulos or []):
            nota = getattr(m, 'nota', None)
            if nota is not None and (nota < 0 or nota > 100):
                inconsistencias.append({
                    "tipo": "notas_fuera_rango",
                    "severidad": "media",
                    "entidad_tipo": "enrollment",
                    "entidad_id": to_id(enr),
                    "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
                    "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
                    "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
                    "descripcion": f"Modulo '{getattr(m, 'nombre', '?')}' tiene nota {nota} (fuera de 0-100)",
                    "accion_sugerida": "revisar_calificacion",
                    "metadata": {"modulo": getattr(m, 'nombre', '?'), "nota": nota}
                })
    return inconsistencias


async def check_becados_mal(programas_ids: List[str]) -> List[dict]:
    """Check 5: Becados con pagos que no cuadran"""
    inconsistencias = []
    discounts = await Discount.find({"porcentaje": {"$gte": 99}}).to_list()
    discount_ids_beca = [to_id(d) for d in discounts]
    discount_ids_beca = [d for d in discount_ids_beca if d]
    if discount_ids_beca:
        enrollments = await Enrollment.find(
            {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}, "descuento_id": {"$in": discount_ids_beca}}
        ).limit(300).to_list()
        for enr in enrollments:
            saldo = getattr(enr, 'saldo_pendiente', 0) or 0
            if saldo and saldo > 0:
                inconsistencias.append({
                    "tipo": "becados_mal",
                    "severidad": "alta",
                    "entidad_tipo": "enrollment",
                    "entidad_id": to_id(enr),
                    "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
                    "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
                    "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
                    "descripcion": f"Becado 100% con saldo pendiente de Bs {saldo}",
                    "accion_sugerida": "verificar_pagos_beca",
                    "metadata": {"saldo": saldo}
                })
    return inconsistencias


async def check_historicos_mal(programas_ids: List[str]) -> List[dict]:
    """Check 6: Historicos mal clasificados (es_historico=True pero estado=en_ejecucion)

    R35-FASE-3 FIX 2 (2026-08-07, Kevin): el check reportaba DIP-DDU-2026/1
    como inconsistente porque tiene es_historico=True y estado_override=en_ejecucion.
    Kevin decidio en la questionnaire que ese programa ESTA bien como historico,
    no quiere tocar el flag. La inconsistencia se reporta SOLO si el programa
    todavia esta en fechas (fecha_fin >= hoy o sin fecha_fin), porque ahi si
    podria ser un error de marcado. Si ya paso la fecha_fin, el programa
    efectivamente termino y el flag es_historico=True es coherente aunque
    estado_override diga en_ejecucion (ej: caso de un programa que se dio
    por terminado administrativamente pero los modulos siguen visibles).
    """
    from datetime import datetime, timezone
    inconsistencias = []
    todos = await Course.find({"es_historico": True}).to_list()
    hoy = datetime.now(timezone.utc).date()
    for c in todos:
        try:
            estado_actual = calcular_estado_actual(
                c.fecha_inicio,
                c.fecha_fin,
                getattr(c, 'estado_override', None),
            )
        except Exception:
            estado_actual = "desconocido"
        # R35-FASE-3 FIX (2026-08-07): el helper calcular_estado_actual() devuelve
        # 'en_ejecucion' como DEFAULT CONSERVADOR cuando el curso no tiene fechas.
        # Esto causaba que DIP-DDU-2026/1 (es_historico=true, sin fechas) sea
        # reportado como mal clasificado cuando en realidad solo no tiene fechas
        # catalogadas. Solo reportar si el curso tiene fechas validas o un override
        # que justifique el estado de ejecucion.
        # R35-FASE-3 FIX 2 (2026-08-07, Kevin): ademas, solo reportar si la
        # fecha_fin es FUTURA (o None). Si ya paso, el programa realmente
        # termino y el flag es_historico=True es legitimo.
        fecha_fin_pasada = (
            c.fecha_fin is not None
            and hasattr(c.fecha_fin, 'date')
            and c.fecha_fin.date() < hoy
        )
        if (
            estado_actual == "en_ejecucion"
            and (c.fecha_inicio is not None or getattr(c, 'estado_override', None) is not None)
            and not fecha_fin_pasada
        ):
            inscritos_count = len(c.inscritos) if getattr(c, 'inscritos', None) else 0
            inconsistencias.append({
                "tipo": "historicos_mal",
                "severidad": "media",
                "entidad_tipo": "course",
                "entidad_id": to_id(c),
                "estudiante_nombre": None,
                "programa_id": to_id(c),
                "programa_codigo": c.codigo,
                "descripcion": f"Programa marcado como historico pero estado=en_ejecucion. Tiene {inscritos_count} inscritos.",
                "accion_sugerida": "decidir_historico_o_activo",
                "metadata": {"inscritos": inscritos_count}
            })
    return inconsistencias


async def check_pasivos_inconsistentes(programas_ids: List[str]) -> List[dict]:
    """Check 7: SUSPENDIDO sin motivo_suspension"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}, "estado": EstadoInscripcion.SUSPENDIDO}
    ).limit(300).to_list()
    for enr in enrollments:
        motivo = getattr(enr, 'motivo_suspension', None)
        if not motivo:
            inconsistencias.append({
                "tipo": "pasivos_inconsistentes",
                "severidad": "media",
                "entidad_tipo": "enrollment",
                "entidad_id": to_id(enr),
                "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
                "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
                "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
                "descripcion": f"SUSPENDIDO sin motivo_suspension definido",
                "accion_sugerida": "reclasificar",
                "metadata": {"motivo": None}
            })
    return inconsistencias


async def check_pagos_duplicados(programas_ids: List[str]) -> List[dict]:
    """Check 8: Pagos duplicados"""
    inconsistencias = []
    pipeline = [
        {"$match": {
            "curso_id": {"$in": prog_obj_ids_list(programas_ids)},
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
    try:
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
    except Exception as e:
        pass  # Si la aggregation falla, no retornar error
    return inconsistencias


async def check_descuentos_mal(programas_ids: List[str]) -> List[dict]:
    """Check 9: Descuentos fuera de rango"""
    inconsistencias = []
    descuentos = await Discount.find_all().to_list()
    for d in descuentos:
        if d.porcentaje < 0 or d.porcentaje > 100:
            inconsistencias.append({
                "tipo": "descuentos_mal",
                "severidad": "alta",
                "entidad_tipo": "discount",
                "entidad_id": to_id(d),
                "estudiante_nombre": None,
                "programa_codigo": d.nombre,
                "descripcion": f"Descuento '{d.nombre}' con porcentaje {d.porcentaje}% (fuera de 0-100)",
                "accion_sugerida": "corregir_porcentaje",
                "metadata": {"porcentaje": d.porcentaje}
            })
    return inconsistencias


async def check_pagos_anulados_activo(programas_ids: List[str]) -> List[dict]:
    """Check 10: Pagos anulados con enrollment activo

    R35-FASE-3 FIX (2026-08-07): el codigo original hacia 1 query a Payment
    POR CADA enrollment (300 queries en serie = 25s!). Optimizado: 2 queries
    totales (1 enrollment + 1 payment con $in todos los IDs).
    """
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}, "estado": {"$in": [EstadoInscripcion.ACTIVO.value, EstadoInscripcion.PENDIENTE_PAGO.value, EstadoInscripcion.COMPLETADO.value]}}
    ).limit(300).to_list()
    if not enrollments:
        return inconsistencias
    enrollment_ids = [to_id(e) for e in enrollments if to_id(e)]
    enrollments_by_id = {to_id(e): e for e in enrollments if to_id(e)}

    # 1 sola query: todos los pagos anulados/rechazados de estos enrollments
    from bson import ObjectId
    enr_obj_ids = [ObjectId(eid) for eid in enrollment_ids if eid]
    pagos_malos = await Payment.find(
        {"inscripcion_id": {"$in": enr_obj_ids}, "estado_pago": {"$in": ["anulado", "rechazado"]}}
    ).limit(1000).to_list()

    for p in pagos_malos:
        pid = to_id(getattr(p, 'inscripcion_id', None))
        enr = enrollments_by_id.get(pid)
        if not enr:
            continue
        inconsistencias.append({
            "tipo": "pagos_anulados_activo",
            "severidad": "alta",
            "entidad_tipo": "pago",
            "entidad_id": to_id(p),
            "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
            "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
            "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
            "descripcion": f"Pago anulado/rechazado (Bs {p.cantidad_pago}) en enrollment {enr.estado}",
            "accion_sugerida": "revisar_consistencia",
            "metadata": {"estado_pago": p.estado_pago, "monto": p.cantidad_pago}
        })
    return inconsistencias


async def check_costo_vs_modulos(programas_ids: List[str]) -> List[dict]:
    """Check 11: Costo total vs suma de modulos"""
    inconsistencias = []
    programas = await Course.find({"_id": {"$in": [p for p in programas_ids if isinstance(p, str)]}}).to_list() if programas_ids else []
    # Si programas_ids son strings, convertir
    if programas_ids and isinstance(programas_ids[0], str):
        try:
            object_ids = [PydanticObjectId(p) for p in programas_ids]
            programas = await Course.find({"_id": {"$in": object_ids}}).to_list()
        except Exception:
            programas = []
    for c in programas:
        costo_total = getattr(c, 'costo_total_interno', 0) or 0
        modulos = getattr(c, 'modulos', []) or []
        suma_modulos = sum((m.costo for m in modulos if hasattr(m, 'costo')), 0)
        if costo_total > 0 and suma_modulos > 0 and abs(costo_total - suma_modulos) / max(costo_total, 1) > 0.05:
            inconsistencias.append({
                "tipo": "costo_vs_modulos",
                "severidad": "media",
                "entidad_tipo": "course",
                "entidad_id": to_id(c),
                "programa_id": to_id(c),
                "programa_codigo": c.codigo,
                "descripcion": f"Costo total (Bs {costo_total:.0f}) != suma de {len(modulos)} modulos (Bs {suma_modulos:.0f}), dif={abs(costo_total-suma_modulos):.0f}",
                "accion_sugerida": "revisar_costos",
                "metadata": {"costo_total": costo_total, "suma_modulos": suma_modulos}
            })
    return inconsistencias


async def check_matricula_pagada_pendiente(programas_ids: List[str]) -> List[dict]:
    """Check 12: Matricula pagada pero enrollment pendiente_pago"""
    inconsistencias = []
    enrollments = await Enrollment.find(
        {"curso_id": {"$in": prog_obj_ids_list(programas_ids)}, "matricula_pagada": True, "estado": EstadoInscripcion.PENDIENTE_PAGO}
    ).limit(100).to_list()
    for enr in enrollments:
        inconsistencias.append({
            "tipo": "matricula_pagada_pendiente",
            "severidad": "media",
            "entidad_tipo": "enrollment",
            "entidad_id": to_id(enr),
            "estudiante_nombre": getattr(enr, 'estudiante_nombre', None) or "?",
            "programa_id": to_id(enr.curso_id) if enr.curso_id else None,
            "programa_codigo": getattr(enr, 'curso_codigo', None) or "?",
            "descripcion": f"Matricula pagada pero estado sigue PENDIENTE_PAGO",
            "accion_sugerida": "cambiar_a_activo",
            "metadata": {"estado_actual": str(getattr(enr, 'estado', '?'))}
        })
    return inconsistencias


async def check_resolucion_faltante(programas_ids: List[str]) -> List[dict]:
    """Check 13: Resoluciones faltantes en programas activos"""
    inconsistencias = []
    object_ids = []
    for p in programas_ids:
        try:
            object_ids.append(PydanticObjectId(p))
        except Exception:
            pass
    if not object_ids:
        return inconsistencias
    programas = await Course.find({"_id": {"$in": object_ids}}).to_list()
    for c in programas:
        resolucion = getattr(c, 'resolucion_pdf_url', None)
        if not resolucion:
            inconsistencias.append({
                "tipo": "resolucion_faltante",
                "severidad": "media",
                "entidad_tipo": "course",
                "entidad_id": to_id(c),
                "programa_id": to_id(c),
                "programa_codigo": c.codigo,
                "descripcion": f"Programa activo sin PDF de resolucion",
                "accion_sugerida": "subir_resolucion",
                "metadata": {"estado_calculado": "en_ejecucion"}
            })
    return inconsistencias


async def check_encargado_inactivo(programas_ids: List[str]) -> List[dict]:
    """Check 14: Encargado de curso inactivo con cursos asignados"""
    inconsistencias = []
    users = await User.find(
        {"cursos_asignados": {"$exists": True, "$ne": []}, "activo": False}
    ).limit(50).to_list()
    for u in users:
        cursos_asig = u.cursos_asignados or []
        prog_ids_str = set(str(p) for p in programas_ids)
        for cid in cursos_asig:
            if str(cid) in prog_ids_str:
                inconsistencias.append({
                    "tipo": "encargado_inactivo",
                    "severidad": "baja",
                    "entidad_tipo": "user",
                    "entidad_id": to_id(u),
                    "estudiante_nombre": getattr(u, 'nombre', None) or u.username,
                    "programa_id": str(cid),
                    "programa_codigo": "ASIGNADO",
                    "descripcion": f"Usuario '{u.username}' esta inactivo pero tiene cursos asignados activos",
                    "accion_sugerida": "reasignar_encargado",
                    "metadata": {"username": u.username}
                })
    return inconsistencias


# ============================================================================
# ENDPOINT PRINCIPAL
# ============================================================================

@router.get("/data-health")
async def get_data_health(
    current_user: User = Depends(require_superadmin),
    programa_id: Optional[str] = None,
    tipo: Optional[str] = None,
    severidad: Optional[str] = None,
):
    """
    Reporte consolidado de inconsistencias de datos.
    Cache 30s. Performance: < 1s.
    """
    now = utcnow_naive()
    if _CACHE["timestamp"] and (now - _CACHE["timestamp"]).total_seconds() < _CACHE_TTL_S:
        data = _CACHE["data"]
        return _apply_filters(data, programa_id, tipo, severidad)

    # Programas en ejecucion (no historicos)
    cursos = await get_programas_en_ejecucion()
    programas_ids = [str(c.id) for c in cursos if c.id is not None]

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

    kpis = {
        "criticas": sum(1 for i in inconsistencias if i["severidad"] == "critica"),
        "altas": sum(1 for i in inconsistencias if i["severidad"] == "alta"),
        "medias": sum(1 for i in inconsistencias if i["severidad"] == "media"),
        "bajas": sum(1 for i in inconsistencias if i["severidad"] == "baja"),
        "total": len(inconsistencias),
    }
    kpis["por_tipo"] = dict(Counter(i["tipo"] for i in inconsistencias))

    filtros = {
        "programas": [{"id": str(c.id), "codigo": c.codigo, "nombre": c.nombre_programa, "inscritos": len(c.inscritos) if c.inscritos else 0} for c in cursos],
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
        "_version": "r35-fase-3-v3",
        "_cache_ttl_s": _CACHE_TTL_S
    }

    _CACHE["timestamp"] = now
    _CACHE["data"] = data

    return _apply_filters(data, programa_id, tipo, severidad)


def _apply_filters(data, programa_id, tipo, severidad):
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
# ACCIONES MASIVAS
# ============================================================================

@router.post("/data-health/fix/{tipo_accion}")
async def fix_inconsistencia(
    tipo_accion: str,
    payload: dict,
    current_user: User = Depends(require_superadmin),
):
    entidad_id = payload.get("entidad_id")
    metadata = payload.get("metadata", {})
    if not entidad_id:
        raise HTTPException(400, "Falta entidad_id")

    if tipo_accion == "cambiar_a_activo":
        try:
            eid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        enr = await Enrollment.get(eid)
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        enr.estado = EstadoInscripcion.ACTIVO
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Enrollment {entidad_id} cambiado a ACTIVO"}

    elif tipo_accion == "reclasificar":
        nuevo_motivo = payload.get("motivo", "congelado")
        try:
            eid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        enr = await Enrollment.get(eid)
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        enr.motivo_suspension = nuevo_motivo
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Enrollment {entidad_id} reclasificado a {nuevo_motivo}"}

    elif tipo_accion == "marcar_cumple":
        req_nombre = metadata.get("requisito")
        if not req_nombre:
            raise HTTPException(400, "Falta 'requisito' en metadata")
        try:
            eid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        enr = await Enrollment.get(eid)
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
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
        ids = metadata.get("ids", [])
        if len(ids) < 2:
            raise HTTPException(400, "Se necesitan al menos 2 IDs")
        keep_id = ids[0]
        anulados = 0
        for pid in ids[1:]:
            try:
                pago = await Payment.get(PydanticObjectId(pid))
            except Exception:
                continue
            if pago:
                pago.estado_pago = EstadoPago.ANULADO
                pago.motivo_rechazo = f"Anulado por R35-FASE-3 (duplicado de {keep_id})"
                await pago.save()
                anulados += 1
        _invalidate_cache()
        return {"ok": True, "message": f"{anulados} pagos anulados, 1 mantenido", "mantenido": keep_id}

    elif tipo_accion == "decidir_historico_o_activo":
        decision = payload.get("decision")
        try:
            cid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        c = await Course.get(cid)
        if not c:
            raise HTTPException(404, "Curso no encontrado")
        if decision == "marcar_historico":
            c.es_historico = True
        elif decision == "marcar_activo":
            c.es_historico = False
        else:
            raise HTTPException(400, "decision debe ser 'marcar_historico' o 'marcar_activo'")
        await c.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Curso {c.codigo} actualizado ({decision})"}

    elif tipo_accion == "corregir_porcentaje":
        nuevo = payload.get("porcentaje")
        if nuevo is None or nuevo < 0 or nuevo > 100:
            raise HTTPException(400, "Porcentaje invalido (0-100)")
        try:
            did = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        d = await Discount.get(did)
        if not d:
            raise HTTPException(404, "Descuento no encontrado")
        d.porcentaje = float(nuevo)
        await d.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Descuento {d.nombre} corregido a {nuevo}%"}

    elif tipo_accion == "verificar_pagos_beca":
        try:
            eid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        enr = await Enrollment.get(eid)
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        pagos_aprobados = await Payment.find(
            {"inscripcion_id": eid, "estado_pago": "aprobado"}
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
        return {"ok": True, "message": f"Saldo recalculado: Bs {nuevo_saldo:.2f}"}

    elif tipo_accion in ("subir_resolucion", "reasignar_encargado"):
        raise HTTPException(400, f"Use el endpoint existente para {tipo_accion}")

    elif tipo_accion in ("retirar", "revisar_y_asignar"):
        # R35-FASE-3 FIX (2026-08-07): "revisar_y_asignar" era la accion sugerida
        # para enrollment_huerfano pero no estaba implementada. Ahora
        # "retirar" / "revisar_y_asignar" cambian el enrollment a RETIRADO
        # con motivo claro. Sirve para los 200 enrollments de programas
        # historicos/cerrados que no se pueden reasignar.
        try:
            eid = PydanticObjectId(entidad_id)
        except Exception:
            raise HTTPException(400, "entidad_id invalido")
        enr = await Enrollment.get(eid)
        if not enr:
            raise HTTPException(404, "Enrollment no encontrado")
        enr.estado = EstadoInscripcion.RETIRADO
        enr.motivo_retiro = f"R35-FASE-3: enrollment huerfano (curso no existe o no esta en ejecucion). Accion: {tipo_accion}"
        enr.fecha_retiro = utcnow_naive()
        enr.retirado_por = "Mavis (R35-FASE-3)"
        await enr.save()
        _invalidate_cache()
        return {"ok": True, "message": f"Enrollment {entidad_id} retirado correctamente"}

    else:
        raise HTTPException(400, f"Accion {tipo_accion} no implementada")


def _invalidate_cache():
    _CACHE["timestamp"] = None
    _CACHE["data"] = None
