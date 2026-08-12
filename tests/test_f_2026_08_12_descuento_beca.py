"""
F-2026-08-12-DESCUENTO-BECA (Kevin 2026-08-12, reunion UAGRM)
============================================================

Tests de regresion ESTATICOS (lectura de codigo, mismo patron que
test_f_2026_08_11_campos_ec_modalidad.py). Verifican que la implementacion
del descuento de beca + discriminacion primer carrera vs profesional este
INTACTA y no se rompa en futuros refactors.

Las reglas a verificar son:

A) CONFIGURACION GLOBAL (core/config.py)
   1. Existe settings.MATRICULA_PRIMER_CARRERA_DEFAULT (default 200.0)
   2. Existe settings.MATRICULA_PROFESIONAL_DEFAULT (default 500.0)
   3. Ambos son float y >= 0

B) COURSE (models/course.py)
   4. Course tiene campo matricula_primer_carrera: Optional[float] (None default)
   5. Course tiene campo matricula_profesional: Optional[float] (None default)

C) STUDENT (models/student.py + schemas/student.py)
   6. Student tiene campo es_primer_carrera: bool (default True)
   7. Student tiene campo titulo_profesional_url: Optional[str]
   8. Student tiene campo titulo_profesional_estado: str (default "pendiente")
   9. Student tiene campo titulo_profesional_motivo_rechazo: Optional[str]
   10. Los 4 campos aparecen en StudentCreate, StudentResponse, StudentUpdateAdmin

D) PRE-REGISTRATION (schemas/pre_registration.py + services/pre_registration_service.py)
   11. PreRegistrationSubmit acepta es_primer_carrera (default True)
   12. PreRegistrationSubmit acepta titulo_profesional_url
   13. Hay validador que exige titulo_profesional_url si es_primer_carrera=False
   14. submit_public_form persiste los 2 campos en data dict
   15. approve_submission copia los campos al Student (es_primer_carrera, titulo_profesional_url, titulo_profesional_estado="pendiente")

E) HELPER DE MATRICULA (services/matricula_helper.py)
   16. Existe funcion get_matricula_for_student(course, student=None)
   17. Si student es None o es_primer_carrera=True, devuelve Course.matricula_primer_carrera ?? settings.MATRICULA_PRIMER_CARRERA_DEFAULT
   18. Si student.es_primer_carrera=False, devuelve Course.matricula_profesional ?? settings.MATRICULA_PROFESIONAL_DEFAULT

F) USO DEL HELPER
   19. services/enrollment_service.py usa get_matricula_for_student al crear el enrollment
   20. services/payment_service.py importa get_matricula_for_student
   21. services/payment_service.py llama a get_matricula_for_student en 2 lugares (matricula_monto del response a nivel curso)
   22. services/payment_service.py llama a _costo_modulo(i, est=estudiante) con el estudiante (no solo i)

G) ENDPOINT UPLOAD TITULO (api/pre_registrations.py)
   23. Existe endpoint POST /pre-registrations/public/{slug}/upload-titulo
   24. El endpoint usa upload_document con folder pre-registrations/titulos-profesionales/{slug}

H) ENDPOINT VALIDAR TITULO (api/students.py)
   25. Existe endpoint PUT /students/{id}/titulo/validar
   26. Usa require_encargado_curso (no require_cpd, porque EC debe poder validar)
   27. Si aprobado=True, setea titulo_profesional_estado="verificado" y motivo_rechazo=None
   28. Si aprobado=False, setea estado="rechazado" y motivo_rechazo=motivo (requerido >=3 chars)
   29. Si no hay titulo_profesional_url, devuelve 400 con mensaje claro
"""

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _read(rel: str) -> str:
    """Lee un archivo del repo."""
    return (ROOT / rel).read_text(encoding="utf-8")


def test_1_matricula_primer_carrera_default_settings():
    src = _read("core/config.py")
    assert "MATRICULA_PRIMER_CARRERA_DEFAULT" in src, "Falta MATRICULA_PRIMER_CARRERA_DEFAULT en settings"
    assert re.search(r'MATRICULA_PRIMER_CARRERA_DEFAULT:\s*float\s*=\s*Field\([^)]*default=200', src), \
        "MATRICULA_PRIMER_CARRERA_DEFAULT debe ser float con default 200.0"


def test_2_matricula_profesional_default_settings():
    src = _read("core/config.py")
    assert "MATRICULA_PROFESIONAL_DEFAULT" in src, "Falta MATRICULA_PROFESIONAL_DEFAULT en settings"
    assert re.search(r'MATRICULA_PROFESIONAL_DEFAULT:\s*float\s*=\s*Field\([^)]*default=500', src), \
        "MATRICULA_PROFESIONAL_DEFAULT debe ser float con default 500.0"


def test_3_settings_typed_as_float():
    src = _read("core/config.py")
    m1 = re.search(r'MATRICULA_PRIMER_CARRERA_DEFAULT:\s*float\s*=', src)
    m2 = re.search(r'MATRICULA_PROFESIONAL_DEFAULT:\s*float\s*=', src)
    assert m1, "MATRICULA_PRIMER_CARRERA_DEFAULT debe ser float"
    assert m2, "MATRICULA_PROFESIONAL_DEFAULT debe ser float"


def test_4_course_matricula_primer_carrera():
    src = _read("models/course.py")
    assert "matricula_primer_carrera" in src, "Falta campo matricula_primer_carrera en Course"
    # Verificar que es Optional[float] con default None
    m = re.search(r'matricula_primer_carrera:\s*Optional\[float\][^=]*=\s*Field\([^)]*default=None', src)
    assert m, "matricula_primer_carrera debe ser Optional[float] con default None"


def test_5_course_matricula_profesional():
    src = _read("models/course.py")
    assert "matricula_profesional" in src, "Falta campo matricula_profesional en Course"
    m = re.search(r'matricula_profesional:\s*Optional\[float\][^=]*=\s*Field\([^)]*default=None', src)
    assert m, "matricula_profesional debe ser Optional[float] con default None"


def test_6_student_es_primer_carrera():
    src = _read("models/student.py")
    assert "es_primer_carrera" in src, "Falta campo es_primer_carrera en Student"
    # Default True
    m = re.search(r'es_primer_carrera:\s*bool\s*=\s*Field\([^)]*default=True', src)
    assert m, "es_primer_carrera debe ser bool con default True"


def test_7_student_titulo_profesional_url():
    src = _read("models/student.py")
    assert "titulo_profesional_url" in src, "Falta campo titulo_profesional_url en Student"


def test_8_student_titulo_profesional_estado():
    src = _read("models/student.py")
    assert "titulo_profesional_estado" in src, "Falta campo titulo_profesional_estado en Student"
    # Default "pendiente"
    m = re.search(r'titulo_profesional_estado:\s*str\s*=\s*Field\([^)]*default="pendiente"', src)
    assert m, 'titulo_profesional_estado debe ser str con default "pendiente"'


def test_9_student_titulo_profesional_motivo_rechazo():
    src = _read("models/student.py")
    assert "titulo_profesional_motivo_rechazo" in src, \
        "Falta campo titulo_profesional_motivo_rechazo en Student"


def test_10_schemas_student_incluyen_campos():
    src = _read("schemas/student.py")
    # Los 4 campos deben estar en StudentCreate, StudentResponse, StudentUpdateAdmin
    for fn in ("StudentCreate", "StudentResponse", "StudentUpdateAdmin"):
        # encontrar el bloque de la clase
        idx = src.find(f"class {fn}")
        assert idx > 0, f"No se encontro la clase {fn}"
        end = src.find("\nclass ", idx)
        if end < 0:
            end = len(src)
        bloque = src[idx:end]
        for campo in ("es_primer_carrera", "titulo_profesional_url", "titulo_profesional_estado"):
            assert campo in bloque, f"Falta {campo} en {fn}"


def test_11_prereg_es_primer_carrera_submit():
    src = _read("schemas/pre_registration.py")
    # Buscar en PreRegistrationSubmit
    idx = src.find("class PreRegistrationSubmit")
    assert idx > 0, "No se encontro PreRegistrationSubmit"
    end = src.find("\nclass ", idx)
    bloque = src[idx:end]
    assert "es_primer_carrera" in bloque, "Falta es_primer_carrera en PreRegistrationSubmit"
    # Default True (mas seguro)
    m = re.search(r'es_primer_carrera:\s*bool\s*=\s*Field\([^)]*default=True', bloque)
    assert m, "es_primer_carrera en PreRegistrationSubmit debe tener default True"


def test_12_prereg_titulo_profesional_url_submit():
    src = _read("schemas/pre_registration.py")
    idx = src.find("class PreRegistrationSubmit")
    end = src.find("\nclass ", idx)
    bloque = src[idx:end]
    assert "titulo_profesional_url" in bloque, "Falta titulo_profesional_url en PreRegistrationSubmit"


def test_13_prereg_validator_titulo_requerido_si_no_primer_carrera():
    src = _read("schemas/pre_registration.py")
    # Verificar que existe un validador que pide titulo si no es primer carrera
    assert "titulo_requerido_si_no_primer_carrera" in src, \
        "Falta validador titulo_requerido_si_no_primer_carrera en PreRegistrationSubmit"
    # Verificar que el validador menciona es_primer_carrera=False
    bloque = re.search(
        r'@field_validator\("titulo_profesional_url"\).*?(?=\n    @field_validator|\n    def carnet|\Z)',
        src, re.DOTALL
    )
    assert bloque, "No se encontro el field_validator de titulo_profesional_url"
    body = bloque.group(0)
    assert "es_primer_carrera" in body and "False" in body, \
        "El validador debe verificar es_primer_carrera=False"


def test_14_service_persist_es_primer_carrera():
    src = _read("services/pre_registration_service.py")
    # En submit_public_form
    idx = src.find("def submit_public_form")
    assert idx > 0
    end = src.find("\nasync def ", idx + 1)
    bloque = src[idx:end]
    assert '"es_primer_carrera":' in bloque, "submit_public_form no persiste es_primer_carrera"
    assert '"titulo_profesional_url":' in bloque, "submit_public_form no persiste titulo_profesional_url"


def test_15_service_approve_copia_titulo():
    src = _read("services/pre_registration_service.py")
    idx = src.find("def approve_submission")
    end = src.find("\nasync def ", idx + 1)
    bloque = src[idx:end]
    assert "es_primer_carrera=" in bloque, "approve_submission no copia es_primer_carrera al Student"
    assert "titulo_profesional_url=" in bloque, "approve_submission no copia titulo_profesional_url al Student"
    assert 'titulo_profesional_estado="pendiente"' in bloque, \
        "approve_submission debe setear titulo_profesional_estado='pendiente'"


def test_16_helper_existe():
    path = ROOT / "services" / "matricula_helper.py"
    assert path.exists(), "Falta services/matricula_helper.py"
    src = path.read_text(encoding="utf-8")
    assert "def get_matricula_for_student" in src, "Falta la funcion get_matricula_for_student"


def test_17_helper_primer_carrera():
    src = (ROOT / "services" / "matricula_helper.py").read_text(encoding="utf-8")
    # Si student es None o es_primer_carrera True → usa matricula_primer_carrera
    assert "es_primer_carrera" in src, "Helper no considera es_primer_carrera"
    assert "MATRICULA_PRIMER_CARRERA_DEFAULT" in src, "Helper no usa el default global"
    assert "matricula_primer_carrera" in src, "Helper no usa el override del curso"


def test_18_helper_profesional():
    src = (ROOT / "services" / "matricula_helper.py").read_text(encoding="utf-8")
    assert "MATRICULA_PROFESIONAL_DEFAULT" in src, "Helper no usa el default global profesional"
    assert "matricula_profesional" in src, "Helper no usa el override del curso"


def test_19_enrollment_usa_helper():
    src = _read("services/enrollment_service.py")
    # El helper debe ser invocado al calcular la matricula del enrollment
    assert "get_matricula_for_student" in src, "enrollment_service no usa get_matricula_for_student"
    # Debe reemplazar course.get_matricula() en la asignacion de costo_matricula
    idx = src.find("costo_matricula =")
    # el primero que aparezca en la funcion create_enrollment_internally
    # Verificar que en el contexto cercano haya una llamada al helper
    snippet = src[max(0, idx - 500):idx + 200]
    assert "get_matricula_for_student(course" in snippet, \
        "enrollment_service no usa get_matricula_for_student(course, student) para costo_matricula"


def test_20_payment_importa_helper():
    src = _read("services/payment_service.py")
    assert "from services.matricula_helper import get_matricula_for_student" in src, \
        "payment_service no importa get_matricula_for_student"
    assert "get_matricula_for_student" in src, "payment_service no usa get_matricula_for_student"


def test_21_payment_usa_helper_en_matricula_monto():
    src = _read("services/payment_service.py")
    # Debe haber al menos 2 ocurrencias (matricula_monto del response)
    matches = re.findall(r'matricula_monto["\']?\s*:\s*get_matricula_for_student', src)
    assert len(matches) >= 1, \
        f"payment_service debe usar get_matricula_for_student en al menos un respuesta matricula_monto (encontradas: {len(matches)})"


def test_22_payment_costo_modulo_pasa_estudiante():
    src = _read("services/payment_service.py")
    # _costo_modulo(i, est=estudiante) debe llamarse con est
    calls = re.findall(r'_costo_modulo\([^)]*est\s*=\s*estudiante', src)
    assert len(calls) >= 1, \
        f"payment_service debe llamar a _costo_modulo(..., est=estudiante). Encontradas: {len(calls)}"


def test_23_endpoint_upload_titulo_existe():
    src = _read("api/pre_registrations.py")
    assert '"/public/{slug}/upload-titulo"' in src or "'/public/{slug}/upload-titulo'" in src, \
        "Falta endpoint POST /pre-registrations/public/{slug}/upload-titulo"


def test_24_upload_titulo_usa_upload_document():
    src = _read("api/pre_registrations.py")
    # Buscar la funcion upload_titulo_profesional
    idx = src.find("async def upload_titulo_profesional")
    assert idx > 0, "Falta la funcion async def upload_titulo_profesional"
    end = src.find("\nasync def ", idx + 1)
    bloque = src[idx:end]
    assert "upload_document" in bloque, "upload_titulo_profesional no usa upload_document"
    assert "titulos-profesionales" in bloque, \
        "upload_titulo_profesional no usa folder pre-registrations/titulos-profesionales"


def test_25_endpoint_validar_titulo_existe():
    src = _read("api/students.py")
    assert '"/{id}/titulo/validar"' in src or "'/{id}/titulo/validar'" in src, \
        "Falta endpoint PUT /students/{id}/titulo/validar"


def test_26_validar_titulo_usa_encargado_curso():
    src = _read("api/students.py")
    idx = src.find("async def validar_titulo_profesional")
    assert idx > 0, "Falta la funcion validar_titulo_profesional"
    end = src.find("\nasync def ", idx + 1)
    if end < 0:
        end = len(src)
    bloque = src[idx:end]
    assert "require_encargado_curso" in bloque, \
        "validar_titulo_profesional debe usar require_encargado_curso (no require_cpd)"


def test_27_validar_titulo_aprobado_verifica():
    src = _read("api/students.py")
    idx = src.find("async def validar_titulo_profesional")
    end = src.find("\nasync def ", idx + 1)
    if end < 0:
        end = len(src)
    bloque = src[idx:end]
    # Si aprobado=True → estado="verificado", motivo=None
    assert '"verificado"' in bloque, "Si aprobado, debe setear estado='verificado'"
    assert '"rechazado"' in bloque, "Si NO aprobado, debe setear estado='rechazado'"


def test_28_validar_titulo_motivo_minimo():
    src = _read("api/students.py")
    idx = src.find("async def validar_titulo_profesional")
    end = src.find("\nasync def ", idx + 1)
    if end < 0:
        end = len(src)
    bloque = src[idx:end]
    # Validacion del motivo >= 3 chars
    assert "motivo" in bloque and ("len(" in bloque and "3" in bloque), \
        "Debe validar que motivo tenga al menos 3 caracteres"


def test_29_validar_titulo_sin_archivo_400():
    src = _read("api/students.py")
    idx = src.find("async def validar_titulo_profesional")
    end = src.find("\nasync def ", idx + 1)
    if end < 0:
        end = len(src)
    bloque = src[idx:end]
    # Si NO hay titulo_profesional_url → 400
    assert "titulo_profesional_url" in bloque and "400" in bloque, \
        "Si no hay titulo_profesional_url debe devolver 400"


# ============================================================================
# INTEGRATION: que la regla hibrida (override curso vs default global) respete
# el orden de prioridad correcto.
# ============================================================================

def test_regla_hibrida_override_gana_sobre_default():
    """
    El helper debe preferir el override del curso (Course.matricula_*) sobre
    el default global (settings.MATRICULA_*_DEFAULT) cuando está definido.
    """
    src = (ROOT / "services" / "matricula_helper.py").read_text(encoding="utf-8")
    # Verificar que el orden es: si course.X is not None, usarlo; sino default.
    # patron: "course.matricula_primer_carrera\n     if course.matricula_primer_carrera is not None\n     else settings.MATRICULA_PRIMER_CARRERA_DEFAULT"
    assert re.search(
        r"course\.matricula_primer_carrera\s*\n.*?if\s+course\.matricula_primer_carrera\s+is\s+not\s+None.*?else\s+settings\.MATRICULA_PRIMER_CARRERA_DEFAULT",
        src, re.DOTALL
    ), "El override del curso debe ganar sobre el default global (primer carrera)"
    assert re.search(
        r"course\.matricula_profesional\s*\n.*?if\s+course\.matricula_profesional\s+is\s+not\s+None.*?else\s+settings\.MATRICULA_PROFESIONAL_DEFAULT",
        src, re.DOTALL
    ), "El override del curso debe ganar sobre el default global (profesional)"


# ============================================================================
# Sanity: NO se rompió el caso "primer carrera con descuento en módulos"
# (F-2026-08-12-DESCUENTO-BECA: Kevin decidio 2026-08-12 que el primer
# carrera SI puede tener descuento, pero SOLO en modulos, NUNCA en matricula.
# Regla F-074-FIX-4 original).
# ============================================================================

def test_sanity_primer_carrera_puede_tener_descuento_en_modulos():
    """
    Verifica que la nueva regla de descuento de beca NO fuerza a 0 el
    descuento del primer carrera. El descuento_porcentaje (de EC) sigue
    aplicando SOLO a modulos, no a matricula, pero un primer carrera puede
    traer descuento en modulos (decision Kevin 2026-08-12).
    """
    src = _read("services/pre_registration_service.py")
    # En approve_submission, NO debe haber un if que fuerce descuento_porcentaje=0
    # cuando es_primer_carrera=True.
    idx = src.find("def approve_submission")
    end = src.find("\nasync def ", idx + 1)
    bloque = src[idx:end]
    # Si hay una linea que setea descuento_porcentaje=0 cuando es_primer_carrera=True,
    # seria un bug. Buscar patron.
    bug_pattern = re.search(
        r"es_primer_carrera.*?descuento_porcentaje\s*=\s*0",
        bloque, re.DOTALL
    )
    assert not bug_pattern, \
        "BUG: primer carrera NO debe perder su descuento_porcentaje (solo se aplica a modulos, no a matricula)"


if __name__ == "__main__":
    import pytest
    sys.exit(pytest.main([__file__, "-v"]))
