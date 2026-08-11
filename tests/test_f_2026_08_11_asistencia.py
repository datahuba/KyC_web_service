"""
F-2026-08-11-ASISTENCIA: tests de regresion para el sistema de
registro de asistencia por sesion/clase (educacion continua UAGRM).

Backend:
- Modelo Sesion (sesiones de clase)
- Modelo AsistenciaRegistro (asistencia de cada estudiante)
- Enum EstadoAsistencia
- Endpoints CRUD de sesiones
- Endpoint bulk register de asistencia
- Endpoint calculo de % asistencia

Estos tests NO importan la app entera (no init_beanie, no FastAPI).
Usan lectura estatica del codigo (mismo patron que test_f082, test_f083,
test_limite_10, test_campos_ec, test_modulos_ec).
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

ASISTENCIA_MODEL = REPO / "models" / "asistencia.py"
ENUMS = REPO / "models" / "enums.py"
ASISTENCIA_SCHEMA = REPO / "schemas" / "asistencia.py"
ASISTENCIA_API = REPO / "api" / "asistencia.py"
DATABASE = REPO / "core" / "database.py"
API_ROUTER = REPO / "api" / "api.py"
MODELS_INIT = REPO / "models" / "__init__.py"


def _read(path: Path) -> str:
    assert path.exists(), f"Archivo no encontrado: {path}"
    return path.read_text(encoding="utf-8")


# ============================================================
# MODELO: Sesion
# ============================================================

def test_model_sesion_tiene_campos_clave():
    """models/asistencia.py:Sesion debe tener enrollment_id, modulo_index,
    fecha, tema (opcional), creado_por."""
    text = _read(ASISTENCIA_MODEL)
    for campo in ("enrollment_id", "modulo_index", "fecha", "tema", "creado_por"):
        assert campo in text, (
            f"models/asistencia.py:Sesion no tiene el campo `{campo}`. "
            f"F-2026-08-11-ASISTENCIA incompleto."
        )


def test_model_sesion_tiene_indice_compuesto():
    """Sesion debe tener un indice (enrollment_id, modulo_index, fecha)."""
    text = _read(ASISTENCIA_MODEL)
    # Buscar [("enrollment_id", 1), ("modulo_index", 1), ("fecha", 1)]
    assert re.search(
        r'\[\s*\(\s*["\']enrollment_id["\']\s*,\s*1\s*\)\s*,\s*\(\s*["\']modulo_index["\']\s*,\s*1\s*\)',
        text,
    ), (
        "Sesion debe tener un indice compuesto (enrollment_id, modulo_index, fecha). "
        "F-2026-08-11-ASISTENCIA incompleto."
    )


def test_model_asistencia_registro_tiene_campos():
    """AsistenciaRegistro debe tener sesion_id, estudiante_id, estado,
    observacion (opcional), registrado_por."""
    text = _read(ASISTENCIA_MODEL)
    for campo in ("sesion_id", "estudiante_id", "estado", "observacion", "registrado_por"):
        assert campo in text, (
            f"models/asistencia.py:AsistenciaRegistro no tiene el campo `{campo}`. "
            f"F-2026-08-11-ASISTENCIA incompleto."
        )


# ============================================================
# ENUM: EstadoAsistencia
# ============================================================

def test_enum_estado_asistencia_existe():
    """models/enums.py debe tener el enum EstadoAsistencia con
    presente, ausente, tarde, justificado."""
    text = _read(ENUMS)
    assert "class EstadoAsistencia" in text, (
        "models/enums.py no tiene la clase `EstadoAsistencia`. "
        "F-2026-08-11-ASISTENCIA incompleto."
    )
    for estado in ("PRESENTE", "AUSENTE", "TARDE", "JUSTIFICADO"):
        assert estado in text, (
            f"EstadoAsistencia no tiene el valor `{estado}`. "
            f"Estados esperados: presente, ausente, tarde, justificado."
        )


# ============================================================
# SCHEMAS
# ============================================================

def test_schemas_existen():
    """schemas/asistencia.py debe tener SesionCreate, SesionResponse,
    AsistenciaItem, AsistenciaBulkRegister, AsistenciaRegistroResponse,
    PorcentajeAsistenciaModulo."""
    text = _read(ASISTENCIA_SCHEMA)
    for schema in (
        "SesionCreate",
        "SesionResponse",
        "AsistenciaItem",
        "AsistenciaBulkRegister",
        "AsistenciaRegistroResponse",
        "PorcentajeAsistenciaModulo",
    ):
        assert f"class {schema}" in text, (
            f"schemas/asistencia.py no tiene la clase `{schema}`. "
            f"F-2026-08-11-ASISTENCIA incompleto."
        )


def test_porcentaje_asistencia_tiene_formula():
    """PorcentajeAsistenciaModulo debe tener el campo `porcentaje` y
    `cumple_regla_80`."""
    text = _read(ASISTENCIA_SCHEMA)
    assert "porcentaje" in text, (
        "PorcentajeAsistenciaModulo no tiene el campo `porcentaje`."
    )
    assert "cumple_regla_80" in text, (
        "PorcentajeAsistenciaModulo no tiene el campo `cumple_regla_80`."
    )


# ============================================================
# API: endpoints
# ============================================================

def test_api_tiene_endpoints_clave():
    """api/asistencia.py debe tener los 6 endpoints principales."""
    text = _read(ASISTENCIA_API)
    endpoints = [
        ('"/sesiones"', "POST crear sesion"),
        ('"/sesiones"', "GET listar sesiones"),
        ('"/sesiones/{sesion_id}"', "GET detalle sesion"),
        ('"/sesiones/{sesion_id}"', "DELETE eliminar sesion"),
        ('"/sesiones/{sesion_id}/registrar"', "POST registrar asistencia"),
        ('"/enrollment/{enrollment_id}/modulo/{modulo_index}/porcentaje/{estudiante_id}"',
         "GET porcentaje asistencia"),
    ]
    for path, desc in endpoints:
        assert path in text, (
            f"api/asistencia.py no tiene el endpoint `{path}` ({desc}). "
            f"F-2026-08-11-ASISTENCIA incompleto."
        )


def test_api_calcula_porcentaje_con_regla_80():
    """El endpoint de % debe calcular: (presentes + 0.5*tardes) / total * 100"""
    text = _read(ASISTENCIA_API)
    # Buscar la formula
    assert "0.5" in text and "presentes" in text, (
        "El calculo del % debe usar la formula (presentes + 0.5*tardes) / total * 100. "
        "F-2026-08-11-ASISTENCIA formula incorrecta."
    )
    assert "cumple_regla_80" in text, (
        "El endpoint debe devolver cumple_regla_80 (>= 80). "
        "F-2026-08-11-ASISTENCIA regla del 80% no aplicada."
    )


# ============================================================
# REGISTRO EN API_ROUTER y DATABASE
# ============================================================

def test_router_registrado_en_api_router():
    """api/api.py debe importar e incluir el router de asistencia."""
    text = _read(API_ROUTER)
    assert "asistencia" in text, (
        "api/api.py no importa `asistencia`. "
        "F-2026-08-11-ASISTENCIA router no registrado."
    )
    assert 'prefix="/asistencia"' in text, (
        "api/api.py no incluye el router de asistencia con prefix '/asistencia'. "
        "F-2026-08-11-ASISTENCIA router no incluido."
    )


def test_modelos_registrados_en_init_beanie():
    """core/database.py debe registrar Sesion y AsistenciaRegistro
    en init_beanie, y los modelos deben importarse."""
    db_text = _read(DATABASE)
    init_text = _read(MODELS_INIT)

    # Import en database.py
    assert "from models.asistencia" in db_text, (
        "core/database.py no importa `from models.asistencia`. "
        "F-2026-08-11-ASISTENCIA modelos no importados en startup."
    )
    # document_models
    assert "Sesion," in db_text and "AsistenciaRegistro," in db_text, (
        "core/database.py no registra Sesion y AsistenciaRegistro en document_models. "
        "F-2026-08-11-ASISTENCIA modelos no inicializados en Beanie."
    )
    # __init__.py
    assert "Sesion" in init_text and "AsistenciaRegistro" in init_text, (
        "models/__init__.py no exporta Sesion y AsistenciaRegistro. "
        "F-2026-08-11-ASISTENCIA modelos no exportados."
    )
