"""
F-2026-08-11-EC-AUTOSERVICIO: tests de regresion para los nuevos
permisos de educacion continua. Kevin pidio que el encargado de
educacion continua pueda:

1. Crear/editar/cerrar/reabrir/eliminar formularios de preinscripcion
   (antes solo superadmin).

2. Crear programas HISTORICOS (fecha_fin ya paso). NO puede crear
   programas nuevos ni en ejecucion (esos siguen siendo CPD/SUPERADMIN).

   ACTUALIZACION F-2026-08-12-EC-RESOLUCION-OBLIGATORIA (Kevin, post-reunion
   2026-08-12): esta restriccion se REVIRTIO al dia siguiente. Ahora
   EC/COORD/CPD/ADMIN/SUPERADMIN pueden crear los 3 tipos de programa
   (historico, programado, en ejecucion) sin distincion de rol. El unico
   gate que queda es documental: un programa en_ejecucion exige
   resolucion_pdf_url (400 si falta), pareja para todos los roles. Ver
   api/courses.py:create_course y los tests mas abajo.

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
    """api/courses.py:create_course debe usar require_gestion_academica
    (permite a los 5 roles: EC, coord, CPD, ADMIN, SUPERADMIN — salvo el
    coordinador financiero, ver F-FIX-COORD-FINANCIERO-NO-ACADEMICO,
    2026-08-19, que envuelve a require_encargado_curso)."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_course en api/courses.py"
    body = match.group(0)
    assert "require_gestion_academica" in body, (
        "create_course debe usar require_gestion_academica (que envuelve a "
        "require_encargado_curso) para permitir a EC/coord intentar crear, "
        "salvo el coordinador financiero. F-2026-08-11-EC-AUTOSERVICIO / "
        "F-FIX-COORD-FINANCIERO-NO-ACADEMICO no aplicado."
    )
    assert "F-2026-08-11-EC-AUTOSERVICIO" in body, (
        "Falta el comentario F-2026-08-11-EC-AUTOSERVICIO en create_course"
    )


def test_courses_create_no_bloquea_nuevo_o_en_ejecucion_a_ec():
    """F-2026-08-12-EC-RESOLUCION-OBLIGATORIA revirtio la restriccion de
    F-2026-08-11-EC-AUTOSERVICIO: EC/coord YA NO estan limitados a crear
    solo programas historicos. create_course no debe tener ningun gate de
    403 basado en rol para el tipo de programa."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_course"
    body = match.group(0)
    assert "F-2026-08-12-EC-RESOLUCION-OBLIGATORIA" in body, (
        "Falta el comentario F-2026-08-12-EC-RESOLUCION-OBLIGATORIA en "
        "create_course (la reversion de la restriccion por rol)."
    )
    # No debe existir un 403 condicionado al tipo de programa (fecha_fin /
    # es_historico). El unico 403 legitimo en el archivo es de otros
    # endpoints (ej. RBAC de edicion), no de este bloque de validacion.
    assert not re.search(r'status_code\s*=\s*403', body), (
        "create_course NO debe lanzar 403 por tipo de programa: desde "
        "F-2026-08-12-EC-RESOLUCION-OBLIGATORIA cualquier rol autorizado "
        "puede crear historico/programado/en_ejecucion."
    )


def test_courses_create_exige_resolucion_para_en_ejecucion():
    """F-2026-08-12-EC-RESOLUCION-OBLIGATORIA: el unico gate para crear un
    programa EN EJECUCION es la resolucion PDF (400 si falta), parejo para
    todos los roles habilitados por require_encargado_curso."""
    text = _read(COURSES_API)
    match = re.search(
        r"async def create_course\b.*?(?=^async def |\n@router\.|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, "No encontre create_course"
    body = match.group(0)
    assert "resolucion_pdf_url" in body, (
        "create_course debe validar resolucion_pdf_url para programas en_ejecucion."
    )
    assert re.search(r'status_code\s*=\s*400', body), (
        "La falta de resolucion en un programa en_ejecucion debe rechazarse con 400."
    )
    # No hay branching por UserRole para decidir si se permite el tipo de
    # programa: el mismo codigo corre para EC, coord, CPD, admin y superadmin.
    assert "UserRole.CPD" not in body and "UserRole.SUPERADMIN" not in body, (
        "create_course no debe distinguir CPD/ADMIN/SUPERADMIN del resto: "
        "la validacion de tipo de programa es la misma para todos los "
        "roles que pasan require_encargado_curso."
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
