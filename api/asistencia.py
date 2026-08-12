"""
F-2026-08-11-ASISTENCIA: endpoints para el sistema de registro de
asistencia por sesion/clase (educacion continua UAGRM).

Casos de uso:
- Docente/encargado crea una Sesion por cada clase que da
- Docente/encargado registra la asistencia de N estudiantes en bulk
- Cierre de modulo: el sistema consulta el % asistencia calculado
  y aplica la regla del 80% (estado_academico='Reprobado' si < 80)

Permisos:
- Crear/modificar sesiones y registros: DOCENTE, ENCARGADO_CURSO,
  COORDINADOR, CPD, ADMIN, SUPERADMIN
- Ver sesiones: cualquier rol autenticado del mismo curso
- Ver % asistencia: el estudiante puede ver el suyo; staff puede ver
  el de cualquier estudiante
"""
from datetime import datetime
from typing import List, Any
from fastapi import APIRouter, Depends, HTTPException, Query, Path, Response
from beanie import PydanticObjectId

from models.asistencia import Sesion, AsistenciaRegistro
from models.enrollment import Enrollment
from models.user import User
from models.enums import EstadoAsistencia, UserRole
from schemas.asistencia import (
    SesionCreate, SesionResponse,
    AsistenciaItem, AsistenciaBulkRegister, AsistenciaRegistroResponse,
    PorcentajeAsistenciaModulo,
)
from api.dependencies import require_staff, get_current_user, require_docente

router = APIRouter()


# ============================================================
# SESIONES
# ============================================================

@router.post(
    "/sesiones",
    response_model=SesionResponse,
    summary="[Staff] Crear una nueva sesion de clase",
)
async def crear_sesion(
    payload: SesionCreate,
    current_user: User = Depends(require_staff),
) -> Any:
    """
    F-2026-08-11-ASISTENCIA: crea una sesion/clase para un modulo de un
    enrollment. La fecha es la fecha+hora de la clase. El tema es opcional.
    """
    # Verificar que el enrollment existe
    enrollment = await Enrollment.get(payload.enrollment_id)
    if not enrollment:
        raise HTTPException(status_code=404, detail="Inscripcion no encontrada")

    # Verificar que el modulo_index es valido
    if payload.modulo_index < 0 or payload.modulo_index >= len(enrollment.modulos or []):
        raise HTTPException(
            status_code=400,
            detail=f"Indice de modulo {payload.modulo_index} invalido (el enrollment tiene {len(enrollment.modulos or [])} modulos)",
        )

    sesion = Sesion(
        enrollment_id=payload.enrollment_id,
        modulo_index=payload.modulo_index,
        fecha=payload.fecha,
        tema=payload.tema,
        creado_por=current_user.username,
    )
    await sesion.insert()
    return sesion


@router.get(
    "/sesiones",
    response_model=List[SesionResponse],
    summary="Listar sesiones de un modulo de un enrollment",
)
async def listar_sesiones(
    enrollment_id: PydanticObjectId = Query(..., description="ID del enrollment"),
    modulo_index: int = Query(..., ge=0, description="Indice del modulo"),
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    F-2026-08-11-ASISTENCIA: lista todas las sesiones registradas para
    un modulo de un enrollment, ordenadas por fecha ascendente.
    """
    sesiones = await Sesion.find(
        Sesion.enrollment_id == enrollment_id,
        Sesion.modulo_index == modulo_index,
    ).sort("+fecha").to_list()
    return sesiones


@router.get(
    "/sesiones/{sesion_id}",
    response_model=Any,
    summary="Detalle de una sesion (incluye los registros de asistencia)",
)
async def get_sesion(
    sesion_id: PydanticObjectId,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    F-2026-08-11-ASISTENCIA: devuelve la sesion + todos los registros
    de asistencia de los estudiantes.
    """
    sesion = await Sesion.get(sesion_id)
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    registros = await AsistenciaRegistro.find(
        AsistenciaRegistro.sesion_id == sesion_id,
    ).to_list()

    return {
        "sesion": sesion,
        "registros": registros,
        "total_registros": len(registros),
    }


@router.delete(
    "/sesiones/{sesion_id}",
    status_code=204,
    response_class=Response,
    summary="[Staff] Eliminar una sesion y todos sus registros de asistencia",
)
async def eliminar_sesion(
    sesion_id: PydanticObjectId,
    current_user: User = Depends(require_staff),
):
    """
    F-2026-08-11-ASISTENCIA: elimina la sesion Y todos sus registros
    de asistencia asociados. CUIDADO: accion irreversible.
    """
    sesion = await Sesion.get(sesion_id)
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    # Eliminar registros asociados primero
    await AsistenciaRegistro.find(
        AsistenciaRegistro.sesion_id == sesion_id,
    ).delete()

    await sesion.delete()
    return None


# ============================================================
# REGISTRO DE ASISTENCIA
# ============================================================

@router.post(
    "/sesiones/{sesion_id}/registrar",
    response_model=List[AsistenciaRegistroResponse],
    summary="[Staff] Registrar asistencia de N estudiantes en una sesion (bulk)",
)
async def registrar_asistencia_bulk(
    sesion_id: PydanticObjectId,
    payload: AsistenciaBulkRegister,
    current_user: User = Depends(require_docente),  # DOCENTE+ (todos los roles que pueden calificar)
) -> Any:
    """
    F-2026-08-11-ASISTENCIA: bulk-register de asistencia. Tipico uso:
    el docente pasa lista al inicio de la clase y manda todos los
    registros de una. Si un estudiante ya tenia un registro en esta
    sesion, se actualiza (upsert por sesion_id+estudiante_id).
    """
    sesion = await Sesion.get(sesion_id)
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesion no encontrada")

    username = current_user.nombre_visible if hasattr(current_user, "nombre_visible") else current_user.username

    resultados: List[AsistenciaRegistro] = []
    for item in payload.registros:
        # Buscar registro existente
        existing = await AsistenciaRegistro.find_one(
            AsistenciaRegistro.sesion_id == sesion_id,
            AsistenciaRegistro.estudiante_id == item.estudiante_id,
        )
        if existing:
            existing.estado = item.estado.value
            existing.observacion = item.observacion
            existing.registrado_por = username
            await existing.save()
            resultados.append(existing)
        else:
            nuevo = AsistenciaRegistro(
                sesion_id=sesion_id,
                estudiante_id=item.estudiante_id,
                estado=item.estado.value,
                observacion=item.observacion,
                registrado_por=username,
            )
            await nuevo.insert()
            resultados.append(nuevo)

    return resultados


# ============================================================
# CONSULTA DE % ASISTENCIA
# ============================================================

@router.get(
    "/enrollment/{enrollment_id}/modulo/{modulo_index}/porcentaje/{estudiante_id}",
    response_model=PorcentajeAsistenciaModulo,
    summary="% de asistencia de un estudiante en un modulo",
)
async def get_porcentaje_asistencia(
    enrollment_id: PydanticObjectId,
    modulo_index: int = Path(..., ge=0),
    estudiante_id: PydanticObjectId = ...,
    current_user: User = Depends(get_current_user),
) -> Any:
    """
    F-2026-08-11-ASISTENCIA: calcula el % de asistencia de UN estudiante
    en UN modulo. Formula:
        % = (presentes + 0.5 * tardes) / total_sesiones * 100
    donde `total_sesiones` cuenta las sesiones que tienen al menos un
    registro para este estudiante (asi sesiones "fantasma" sin marcar
    no lo hunden).

    Permisos: el estudiante solo puede ver el suyo; staff puede ver
    el de cualquier estudiante.
    """
    # Permiso: estudiante solo el suyo; staff cualquier estudiante
    if current_user.rol == UserRole.ESTUDIANTE:
        if str(current_user.id) != str(estudiante_id):
            raise HTTPException(
                status_code=403,
                detail="Solo puedes consultar tu propia asistencia",
            )

    # Obtener todas las sesiones del modulo
    sesiones = await Sesion.find(
        Sesion.enrollment_id == enrollment_id,
        Sesion.modulo_index == modulo_index,
    ).to_list()

    if not sesiones:
        # Sin sesiones registradas: 0% asistencia por default
        return PorcentajeAsistenciaModulo(
            enrollment_id=enrollment_id,
            modulo_index=modulo_index,
            estudiante_id=estudiante_id,
            total_sesiones=0,
            presentes=0,
            ausentes=0,
            tardes=0,
            justificados=0,
            porcentaje=0.0,
            cumple_regla_80=False,
        )

    # Obtener registros del estudiante
    registros = await AsistenciaRegistro.find(
        AsistenciaRegistro.estudiante_id == estudiante_id,
        AsistenciaRegistro.sesion_id.in_([s.id for s in sesiones]),
    ).to_list()

    # Mapear sesion_id -> estado
    registros_map = {str(r.sesion_id): r.estado for r in registros}

    # total_sesiones cuenta solo las sesiones donde el estudiante tiene
    # un registro (asi sesiones "fantasma" sin marcar no cuentan)
    sesiones_con_registro = [s for s in sesiones if str(s.id) in registros_map]

    presentes = sum(1 for e in registros_map.values() if e == "presente")
    ausentes = sum(1 for e in registros_map.values() if e == "ausente")
    tardes = sum(1 for e in registros_map.values() if e == "tarde")
    justificados = sum(1 for e in registros_map.values() if e == "justificado")

    total = len(sesiones_con_registro)
    if total == 0:
        porcentaje = 0.0
    else:
        # tarde = 0.5 presente, justificado = neutro (no suma al numerador ni al denominador)
        porcentaje = (presentes + 0.5 * tardes) / total * 100
        porcentaje = round(porcentaje, 2)

    return PorcentajeAsistenciaModulo(
        enrollment_id=enrollment_id,
        modulo_index=modulo_index,
        estudiante_id=estudiante_id,
        total_sesiones=total,
        presentes=presentes,
        ausentes=ausentes,
        tardes=tardes,
        justificados=justificados,
        porcentaje=porcentaje,
        cumple_regla_80=porcentaje >= 80,
    )
