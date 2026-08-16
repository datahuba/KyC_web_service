"""
F-2026-08-11-CAMPOS-EC: tests de regresion para los 5 campos del formulario
de preinscripcion de Educacion Continua (Diplomado Gestion Tributaria V6
y similares), agregados tras la reunion UAGRM 2026-08-11.

Campos:
  - registro_universitario (str)
  - avance_academico_codigo (int)
  - formulario_descuento_numero (int)
  - carrera_codigo (str)
  - descuento_porcentaje (float 0-1, regla F-074-FIX-4: aplica a modulos, no matricula)

Estos tests NO importan la app entera (no init_beanie, no FastAPI).
Usan lectura estatica del codigo (mismo patron que test_f082, test_f083,
test_f_2026_08_11_limite_10) porque los cambios son declarativos:
5 campos agregados en 3 schemas (Student + PreRegistration), 1 modelo,
2 servicios, 1 servicio TS y 1 pagina Svelte del wizard.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
KYC_CLIENT = REPO.parent / "kyc-client"

STUDENT_MODEL = REPO / "models" / "student.py"
STUDENT_SCHEMA = REPO / "schemas" / "student.py"
PR_SCHEMA = REPO / "schemas" / "pre_registration.py"
PR_SERVICE = REPO / "services" / "pre_registration_service.py"

PR_SERVICE_TS = KYC_CLIENT / "src" / "lib" / "services" / "pre-registration.service.ts"
PR_PAGE_SVELTE = KYC_CLIENT / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte"

# Los 5 campos canonicos que debe aceptar el sistema
CAMPOS_EC = [
    "registro_universitario",
    "avance_academico_codigo",
    "formulario_descuento_numero",
    "carrera_codigo",
    "descuento_porcentaje",
]


def _read(path: Path) -> str:
    assert path.exists(), f"Archivo no encontrado: {path}"
    return path.read_text(encoding="utf-8")


# ============================================================
# BACKEND: modelo Student
# ============================================================

def test_student_model_tiene_los_5_campos():
    """models/student.py:Student debe definir los 5 campos EC con tipos
    correctos. descuento_porcentaje debe ser float 0-1 (regla F-074)."""
    text = _read(STUDENT_MODEL)
    for campo in CAMPOS_EC:
        assert campo in text, (
            f"models/student.py no contiene el campo `{campo}`. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en modelo Student."
        )
    # Comentario de trazabilidad F-2026-08-11-CAMPOS-EC debe existir
    assert "F-2026-08-11-CAMPOS-EC" in text, (
        "Falta el comentario F-2026-08-11-CAMPOS-EC en models/student.py"
    )


# ============================================================
# BACKEND: schemas
# ============================================================

def test_schemas_student_tienen_los_5_campos():
    """schemas/student.py:StudentCreate, StudentUpdateAdmin y
    StudentResponse deben tener los 5 campos EC."""
    text = _read(STUDENT_SCHEMA)
    for campo in CAMPOS_EC:
        # Al menos 3 ocurrencias (StudentCreate + StudentUpdateAdmin + StudentResponse)
        count = text.count(campo)
        assert count >= 3, (
            f"schemas/student.py debe declarar `{campo}` en al menos 3 schemas "
            f"(StudentCreate, StudentUpdateAdmin, StudentResponse). "
            f"Encontrado: {count}"
        )


def test_schemas_pre_registration_tiene_los_5_campos():
    """schemas/pre_registration.py:PreRegistrationSubmit debe tener los 5 campos."""
    text = _read(PR_SCHEMA)
    for campo in CAMPOS_EC:
        assert campo in text, (
            f"schemas/pre_registration.py no contiene `{campo}`. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en PreRegistrationSubmit."
        )
    assert "F-2026-08-11-CAMPOS-EC" in text, (
        "Falta el comentario F-2026-08-11-CAMPOS-EC en schemas/pre_registration.py"
    )


# ============================================================
# BACKEND: services
# ============================================================

def test_pr_service_submit_persiste_los_5_campos():
    """services/pre_registration_service.py:submit_public_form debe
    persistir los 5 campos en data dict del PreRegistration."""
    text = _read(PR_SERVICE)
    # Localizar la funcion submit_public_form
    match = re.search(
        r"^async def submit_public_form\b.*?(?=^async def |\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "No encontre submit_public_form en services/pre_registration_service.py"
    )
    body = match.group(0)
    for campo in CAMPOS_EC:
        assert campo in body, (
            f"submit_public_form no persiste `{campo}` en data dict. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en submit_public_form."
        )


def test_pr_service_approve_copia_los_5_campos():
    """services/pre_registration_service.py:approve_submission debe
    copiar los 5 campos del data dict al Student."""
    text = _read(PR_SERVICE)
    # Localizar la funcion approve_submission
    match = re.search(
        r"^async def approve_submission\b.*?(?=^async def |\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match is not None, (
        "No encontre approve_submission en services/pre_registration_service.py"
    )
    body = match.group(0)
    for campo in CAMPOS_EC:
        assert campo in body, (
            f"approve_submission no copia `{campo}` del data al Student. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en approve_submission."
        )


# ============================================================
# FRONTEND: servicio TS
# ============================================================

def test_pr_service_ts_declara_los_5_campos():
    """kyc-client/src/lib/services/pre-registration.service.ts:
    PreRegistrationSubmit interface debe declarar los 5 campos."""
    text = _read(PR_SERVICE_TS)
    # Mapear snake_case del backend a camelCase del frontend
    CAMPOS_FRONT = [
        "registro_universitario",
        "avance_academico_codigo",
        "formulario_descuento_numero",
        "carrera_codigo",
        "descuento_porcentaje",
    ]
    for campo in CAMPOS_FRONT:
        assert campo in text, (
            f"pre-registration.service.ts no declara `{campo}`. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en servicio TS."
        )


# ============================================================
# FRONTEND: pagina Svelte del wizard
# ============================================================

def test_pr_page_svelte_tiene_4_pasos():
    """[slug]/+page.svelte: el wizard debe tener 4 pasos (1, 2, 3, 4).
    El paso 3 nuevo es 'Datos EC (opcional)'. El paso 4 es 'Confirmar'."""
    text = _read(PR_PAGE_SVELTE)
    # Debe haber 4 bloques {#if currentStep === N}
    for n in (1, 2, 3, 4):
        assert f"currentStep === {n}" in text, (
            f"[slug]/+page.svelte no tiene `{{#if currentStep === {n}}}`. "
            f"Wizard debe tener 4 pasos (Datos EC insertado en paso 3, "
            f"Confirmar renumerado a paso 4)."
        )
    # El STEPS array debe tener 4 elementos
    match_steps = re.search(r"const STEPS\s*=\s*\[(.*?)\]\s*as const", text, re.DOTALL)
    assert match_steps is not None, "No encontre el array STEPS"
    steps_body = match_steps.group(1)
    # Contar { id: N, ... } donde N es 1, 2, 3, 4
    step_ids = re.findall(r"\{\s*id:\s*(\d+)\s*,", steps_body)
    step_ids_int = sorted(set(int(x) for x in step_ids))
    assert step_ids_int == [1, 2, 3, 4], (
        f"STEPS debe tener 4 elementos con id 1, 2, 3, 4. Encontrado: {step_ids_int}"
    )


def test_pr_page_svelte_paso_3_es_datos_ec():
    """[slug]/+page.svelte: el paso 3 debe llamarse 'Datos EC'."""
    text = _read(PR_PAGE_SVELTE)
    # Buscar el step con id: 3 en el array STEPS
    match = re.search(r"\{\s*id:\s*3\s*,\s*title:\s*'([^']+)'", text)
    assert match is not None, (
        "No encontre el step con id: 3 en el array STEPS"
    )
    title = match.group(1)
    assert "Datos EC" in title, (
        f"El paso 3 debe llamarse 'Datos EC ...'. Encontrado: '{title}'"
    )


def test_pr_page_svelte_tiene_5_state_vars_ec():
    """[slug]/+page.svelte: deben existir 5 state variables $state('')
    para los campos EC."""
    text = _read(PR_PAGE_SVELTE)
    state_vars = [
        "registroUniversitario",
        "avanceAcademicoCodigo",
        "formularioDescuentoNumero",
        "carreraCodigo",
        "descuentoPorcentaje",
    ]
    for var in state_vars:
        # Patrón: `let varName = $state(...)`
        pattern = rf"\blet\s+{var}\s*=\s*\$state\("
        assert re.search(pattern, text), (
            f"[slug]/+page.svelte no define el state `$state` para `{var}`. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en el wizard."
        )


def test_pr_page_svelte_tiene_5_inputs_ec():
    """[slug]/+page.svelte: el paso 3 debe tener 5 inputs con id pr-xxx
    correspondientes a los campos EC."""
    text = _read(PR_PAGE_SVELTE)
    input_ids = [
        "pr-registro",
        "pr-avance",
        "pr-formdesc",
        "pr-carrera",
        "pr-descuento",
    ]
    for input_id in input_ids:
        assert f'id="{input_id}"' in text, (
            f"[slug]/+page.svelte no contiene `<input id=\"{input_id}\" ...>`. "
            f"F-2026-08-11-CAMPOS-EC UI incompleta."
        )


def test_pr_page_svelte_envia_los_5_campos_al_submit():
    """[slug]/+page.svelte:handleSubmit debe enviar los 5 campos EC
    al servicio submitPublicForm."""
    text = _read(PR_PAGE_SVELTE)
    # Localizar la funcion handleSubmit
    match = re.search(
        r"async function handleSubmit\b.*?(?=\n\s*//\s*----|\n\s*\}\s*\n\s*<|\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "No encontre handleSubmit en [slug]/+page.svelte"
    )
    body = match.group(0)
    # Las 5 propiedades que se envian
    expected = [
        "registro_universitario",
        "avance_academico_codigo",
        "formulario_descuento_numero",
        "carrera_codigo",
        "descuento_porcentaje",
    ]
    for prop in expected:
        assert prop in body, (
            f"handleSubmit no envia `{prop}` al backend. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en envio."
        )


def test_pr_page_svelte_valida_campos_ec():
    """[slug]/+page.svelte:validateField debe validar los 5 campos EC
    (opcionales, pero con formato si están llenos)."""
    text = _read(PR_PAGE_SVELTE)
    # Localizar validateField function
    match = re.search(
        r"function validateField\b.*?(?=\nfunction validateStep|\nfunction nextStep|\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, (
        "No encontre validateField en [slug]/+page.svelte"
    )
    body = match.group(0)
    cases = [
        "registroUniversitario",
        "avanceAcademicoCodigo",
        "formularioDescuentoNumero",
        "carreraCodigo",
        "descuentoPorcentaje",
    ]
    for case in cases:
        assert f"case '{case}'" in body, (
            f"validateField no maneja el caso '{case}'. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en validacion."
        )


def test_pr_page_svelte_autosave_incluye_campos_ec():
    """[slug]/+page.svelte:saveAutosave debe persistir los 5 campos EC."""
    text = _read(PR_PAGE_SVELTE)
    # Localizar saveAutosave
    match = re.search(
        r"function saveAutosave\b.*?(?=\nfunction loadAutosave|\Z)",
        text,
        re.DOTALL,
    )
    assert match is not None, "No encontre saveAutosave"
    body = match.group(0)
    campos = [
        "registroUniversitario",
        "avanceAcademicoCodigo",
        "formularioDescuentoNumero",
        "carreraCodigo",
        "descuentoPorcentaje",
    ]
    for campo in campos:
        assert campo in body, (
            f"saveAutosave no persiste `{campo}`. "
            f"F-2026-08-11-CAMPOS-EC no aplicado en autosave."
        )
