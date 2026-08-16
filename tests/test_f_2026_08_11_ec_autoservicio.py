"""
F-2026-08-11-EC-AUTOSERVICIO: tests de regresion para los nuevos
permisos de educacion continua. Kevin pidio que el encargado de
educacion continua pueda:

1. Crear/editar/cerrar/reabrir/eliminar formularios de preinscripcion
   (antes solo superadmin).

2. Crear programas HISTORICOS (fecha_fin ya paso). NO puede crear
   programas nuevos ni en ejecucion (esos siguen siendo CPD/SUPERADMIN).

Estos tests NO importan la app entera (no init_beanie, no FastAPI).
Usan lectura estatica del codigo (mismo patron que test_f082, test_f083,
test_limite_10, test_campos_ec, test_modulos_ec, test_asistencia).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

COURSES_API = REPO / "api" / "courses.py"
PRE_REG_API = REPO / "api" / "pre_registrations.py"


def _read(path: Path) -> str:
    assert path.exists(), f"Archivo no encontrado: {path}"
    return path.read_text(encoding="utf-8")


# ============================================================
# COURSES: encargado_curso/coord puede crear solo historicos
# ============================================================

def test_courses_create_usa_require_encargado_curso():
    """api/courses.py:create_course debe usar require_encargado_curso
    (permite a los 5 roles: EC, coord, CPD, ADMIN, SUPERADMIN)."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_course en api/courses.py"
    body = match.group(0)
    assert "require_encargado_curso" in body, (
        "create_course debe usar require_encargado_curso para permitir a "
        "EC/coord intentar crear. F-2026-08-11-EC-AUTOSERVICIO no aplicado."
    )
    assert "F-2026-08-11-EC-AUTOSERVICIO" in body, (
        "Falta el comentario F-2026-08-11-EC-AUTOSERVICIO en create_course"
    )


def test_courses_create_bloquea_nuevo_o_en_ejecucion_a_ec():
    """create_course debe validar: si NO es CPD/ADMIN/SUPERADMIN, el
    curso debe ser HISTORICO (fecha_fin ya paso). Si intenta crear
    uno nuevo/en ejecucion, se rechaza con 403."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_course"
    body = match.group(0)
    # Debe chequear fecha_fin < now
    assert "fecha_fin" in body, (
        "create_course debe validar fecha_fin para EC/coord. "
        "F-2026-08-11-EC-AUTOSERVICIO no aplicado."
    )
    # Debe lanzar 403 si la fecha fin es futura
    assert re.search(
        r'status_code\s*=\s*403',
        body,
    ), (
        "create_course debe lanzar 403 si EC/coord intenta crear curso "
        "no historico. F-2026-08-11-EC-AUTOSERVICIO no aplicado."
    )
    # El mensaje debe mencionar 'historico'
    assert re.search(
        r"historico|hist\u00f3rico",
        body,
        re.IGNORECASE,
    ), (
        "El mensaje de error 403 debe mencionar 'historico' para que el "
        "usuario entienda la regla. F-2026-08-11-EC-AUTOSERVICIO incompleto."
    )


def test_courses_create_permite_cualquier_tipo_a_cpd_admin_super():
    """create_course NO debe restringir a CPD/ADMIN/SUPERADMIN
    (deben poder crear cualquier tipo: nuevo, en ejecucion, historico)."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    body = match.group(0)
    assert "UserRole.CPD" in body and "UserRole.SUPERADMIN" in body, (
        "create_course debe permitir a CPD/ADMIN/SUPERADMIN sin "
        "restriccion de tipo."
    )


# ============================================================
# PRE-REGISTRATIONS: EC/coord puede crear/editar/cerrar/reabrir/eliminar
# ============================================================

def test_pre_reg_crear_usa_require_encargado_curso():
    """api/pre_registrations.py:create_form debe usar require_encargado_curso."""
    text = _read(PRE_REG_API)
    # Localizar la funcion create_form
    match = re.search(
        r"async def create_form\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_form en api/pre_registrations.py"
    body = match.group(0)
    assert "require_encargado_curso" in body, (
        "create_form debe usar require_encargado_curso para que EC/coord "
        "puedan crear formularios. F-2026-08-11-EC-AUTOSERVICIO no aplicado."
    )
    assert "F-2026-08-11-EC-AUTOSERVICIO" in body, (
        "Falta el comentario F-2026-08-11-EC-AUTOSERVICIO en create_form"
    )


def test_pre_reg_editar_cerrar_reabrir_eliminar_usan_require_encargado_curso():
    """api/pre_registrations.py: update_form, close_form, reopen_form,
    delete_form deben usar require_encargado_curso (no superadmin)."""
    text = _read(PRE_REG_API)
    funcs = ["update_form", "close_form", "reopen_form", "delete_form"]
    for fn in funcs:
        match = re.search(
            rf"async def {fn}\b.*?(?=^async def |\n@router\.|\Z)",
            text,
            re.DOTALL | re.MULTILINE,
        )
        assert match is not None, f"No encontre {fn}"
        body = match.group(0)
        assert "require_encargado_curso" in body, (
            f"{fn} debe usar require_encargado_curso (no superadmin). "
            f"F-2026-08-11-EC-AUTOSERVICIO no aplicado."
        )
        assert "F-2026-08-11-EC-AUTOSERVICIO" in body, (
            f"Falta el comentario F-2026-08-11-EC-AUTOSERVICIO en {fn}"
        )


def test_pre_reg_no_usa_superadmin_en_endpoints_de_gestion():
    """api/pre_registrations.py NO debe seguir usando require_superadmin
    para los endpoints de gestion de formularios (create/edit/close/
    reopen/delete). Solo en endpoints que explicitamente lo requieran."""
    text = _read(PRE_REG_API)
    funcs = ["create_form", "update_form", "close_form", "reopen_form", "delete_form"]
    for fn in funcs:
        match = re.search(
            rf"async def {fn}\b.*?(?=^async def |\n@router\.|\Z)",
            text,
            re.DOTALL | re.MULTILINE,
        )
        assert match is not None, f"No encontre {fn}"
        body = match.group(0)
        assert "require_superadmin" not in body, (
            f"{fn} AUN usa require_superadmin. F-2026-08-11-EC-AUTOSERVICIO "
            f"debe permitir EC/coord, no solo superadmin."
        )
