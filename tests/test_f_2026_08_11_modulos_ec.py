"""
F-2026-08-11-MODULOS-EC: tests de regresion para el workflow de gestion
de modulos SOLO educacion continua, agregando dos reglas de la reunion
UAGRM 2026-08-11:

A) Estudiante NO ve nota hasta pagar: si saldo_pendiente > 0, el
   endpoint /api/v1/enrollments/me oculta nota, nota_borrador,
   estado_academico (lo fuerza a "Cursando") y nota_final.

B) Regla 80% asistencia: el endpoint POST /enrollments/{id}/modulos/
   {index}/finalizar acepta asistencia_porcentaje opcional. Si < 80%,
   fuerza estado_academico='Reprobado'.

Estos tests NO importan la app entera (no init_beanie, no FastAPI).
Usan lectura estatica del codigo (mismo patron que test_f082, test_f083,
test_limite_10, test_campos_ec) porque los cambios son declarativos:
1 campo nuevo, 1 endpoint modificado, 1 filtro en otro endpoint.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ENROLLMENT_MODEL = REPO / "models" / "enrollment.py"
ENROLLMENT_SCHEMA = REPO / "schemas" / "enrollment.py"
ENROLLMENTS_API = REPO / "api" / "enrollments.py"


def _read(path: Path) -> str:
    assert path.exists(), f"Archivo no encontrado: {path}"
    return path.read_text(encoding="utf-8")


# ============================================================
# MODELO: asistencia_porcentaje
# ============================================================

def test_model_tiene_asistencia_porcentaje():
    """models/enrollment.py:ModuloEstado debe tener el campo
    asistencia_porcentaje (Optional[float], 0-100)."""
    text = _read(ENROLLMENT_MODEL)
    assert "asistencia_porcentaje" in text, (
        "models/enrollment.py no contiene el campo `asistencia_porcentaje`. "
        "F-2026-08-11-MODULOS-EC no aplicado en modelo."
    )
    # Debe tener ge=0, le=100 (validacion de rango 0-100)
    match = re.search(
        r"asistencia_porcentaje[\s\S]*?ge\s*=\s*0[\s\S]*?le\s*=\s*100",
        text,
    )
    assert match is not None, (
        "asistencia_porcentaje debe tener validacion ge=0, le=100. "
        "Verificar que el Field tiene los parametros correctos."
    )
    # Comentario de trazabilidad
    assert "F-2026-08-11-MODULOS-EC" in text, (
        "Falta el comentario F-2026-08-11-MODULOS-EC en models/enrollment.py"
    )


# ============================================================
# SCHEMA: asistencia_porcentaje expuesto
# ============================================================

def test_schema_expone_asistencia_porcentaje():
    """schemas/enrollment.py:ModuloEstadoSchema debe tener
    asistencia_porcentaje: Optional[float] = None para que se exponga
    en el EnrollmentResponse."""
    text = _read(ENROLLMENT_SCHEMA)
    assert "asistencia_porcentaje" in text, (
        "schemas/enrollment.py no expone `asistencia_porcentaje`. "
        "F-2026-08-11-MODULOS-EC no aplicado en schema."
    )
    # Debe ser Optional[float] con default None
    match = re.search(
        r"asistencia_porcentaje:\s*Optional\[float\]\s*=\s*None",
        text,
    )
    assert match is not None, (
        "asistencia_porcentaje debe declararse como "
        "`Optional[float] = None` en el schema."
    )


# ============================================================
# ENDPOINT: filtro de notas en /me si hay deuda
# ============================================================

def test_me_endpoint_filtra_notas_si_deuda():
    """api/enrollments.py:get_my_enrollments debe filtrar nota,
    nota_borrador, estado_academico y nota_final cuando
    saldo_pendiente > 0."""
    text = _read(ENROLLMENTS_API)
    # Localizar la funcion get_my_enrollments
    match = re.search(
        r"async def get_my_enrollments\b.*?(?=^async def |\n@router\.|\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "No encontre get_my_enrollments en api/enrollments.py"
    )
    body = match.group(0)
    # Debe verificar saldo_pendiente > 0
    assert "saldo_pendiente" in body, (
        "get_my_enrollments no referencia saldo_pendiente. "
        "F-2026-08-11-MODULOS-EC no aplicado."
    )
    # Debe limpiar nota
    assert re.search(r'm\[?\s*["\']?nota["\']?\s*\]?\s*=\s*None', body) or re.search(
        r"\.nota\s*=\s*None", body
    ), (
        "get_my_enrollments no limpia el campo nota. "
        "F-2026-08-11-MODULOS-EC no aplicado (filtro de notas)."
    )
    # Debe limpiar nota_borrador
    assert "nota_borrador" in body, (
        "get_my_enrollments no limpia nota_borrador. "
        "F-2026-08-11-MODULOS-EC no aplicado (filtro de borradores)."
    )
    # Comentario de trazabilidad
    assert "F-2026-08-11-MODULOS-EC" in body, (
        "Falta el comentario F-2026-08-11-MODULOS-EC en get_my_enrollments"
    )


# ============================================================
# ENDPOINT: finalizar modulo con asistencia_porcentaje
# ============================================================

def test_finalizar_modulo_acepta_asistencia():
    """api/enrollments.py:finalizar_modulo_endpoint debe aceptar
    asistencia_porcentaje como parametro Body."""
    text = _read(ENROLLMENTS_API)
    match = re.search(
        r"async def finalizar_modulo_endpoint\b.*?(?=^async def |\n@router\.|\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "No encontre finalizar_modulo_endpoint en api/enrollments.py"
    )
    body = match.group(0)
    # Parametro asistencia_porcentaje con Body
    assert "asistencia_porcentaje" in body, (
        "finalizar_modulo_endpoint no tiene parametro asistencia_porcentaje. "
        "F-2026-08-11-MODULOS-EC no aplicado."
    )
    # Debe persistir el campo
    assert re.search(
        r"modulo\.asistencia_porcentaje\s*=\s*asistencia_porcentaje",
        body,
    ), (
        "finalizar_modulo_endpoint no persiste modulo.asistencia_porcentaje. "
        "F-2026-08-11-MODULOS-EC no aplicado."
    )


def test_finalizar_modulo_aplica_regla_80_por_ciento():
    """Si asistencia_porcentaje < 80, finalizar_modulo_endpoint debe
    forzar estado_academico='Reprobado'."""
    text = _read(ENROLLMENTS_API)
    match = re.search(
        r"async def finalizar_modulo_endpoint\b.*?(?=^async def |\n@router\.|\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "No encontre finalizar_modulo_endpoint en api/enrollments.py"
    )
    body = match.group(0)
    # Buscar la condicion: if asistencia_porcentaje < 80
    assert re.search(
        r"asistencia_porcentaje\s*<\s*80",
        body,
    ), (
        "finalizar_modulo_endpoint no valida la regla del 80%. "
        "F-2026-08-11-MODULOS-EC no aplicado (regla 80%)."
    )
    # Debe asignar Reprobado
    assert re.search(
        r"estado_academico\s*=\s*[\"']Reprobado[\"']",
        body,
    ), (
        "finalizar_modulo_endpoint no fuerza estado_academico='Reprobado' "
        "cuando asistencia < 80. F-2026-08-11-MODULOS-EC no aplicado."
    )
