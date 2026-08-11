"""
F-2026-08-11-LIMITE-10: tests de regresion para el limite de programas
asignados por encargado, subido de 5 a 10 en la reunion de educacion
continua UAGRM (2026-08-11).

Estos tests NO importan la app entera (no init_beanie, no FastAPI).
Usan lectura estatica del codigo (mismo patron que test_f082,
test_f083, test_f070_fix2) porque el cambio es 100% declarativo:
un numero constante y 3 lugares que lo usan.
"""
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ENUMS = REPO / "models" / "enums.py"
SCHEMAS = REPO / "schemas" / "user.py"
USER_SERVICE = REPO / "services" / "user_service.py"


def _read(path: Path) -> str:
    assert path.exists(), f"Archivo no encontrado: {path}"
    return path.read_text(encoding="utf-8")


def test_constante_existe_en_models_enums():
    """La constante MAX_PROGRAMAS_POR_ENCARGADO debe existir y valer 10."""
    text = _read(ENUMS)
    match = re.search(r"^MAX_PROGRAMAS_POR_ENCARGADO\s*=\s*(\d+)\s*$", text, re.MULTILINE)
    assert match is not None, (
        "Falta la constante MAX_PROGRAMAS_POR_ENCARGADO en models/enums.py"
    )
    valor = int(match.group(1))
    assert valor == 10, (
        f"MAX_PROGRAMAS_POR_ENCARGADO debe ser 10 (antes 5). Encontrado: {valor}. "
        f"Contexto: reunion educacion continua UAGRM 2026-08-11."
    )


def test_schemas_user_create_usa_constante():
    """schemas/user.py:UserCreate.validar_limite_programas debe usar la
    constante y NO un literal 5 hardcodeado."""
    text = _read(SCHEMAS)
    # Debe importar la constante
    assert "MAX_PROGRAMAS_POR_ENCARGADO" in text, (
        "schemas/user.py debe importar MAX_PROGRAMAS_POR_ENCARGADO"
    )
    # NO debe quedar ningun `> 5` ni `>= 5` (limite viejo)
    assert not re.search(r"len\([^)]+\)\s*>\s*5\b", text), (
        "schemas/user.py aun usa literal `> 5`. Debe ser "
        f"> MAX_PROGRAMAS_POR_ENCARGADO. Texto: {text[:200]}"
    )
    # El mensaje debe interpolar la constante (en runtime sera "10 programas").
    # En codigo fuente se ve como "{MAX_PROGRAMAS_POR_ENCARGADO} programas".
    assert "{MAX_PROGRAMAS_POR_ENCARGADO} programas" in text, (
        "El mensaje de error debe interpolar MAX_PROGRAMAS_POR_ENCARGADO. "
        "En codigo se ve como '{MAX_PROGRAMAS_POR_ENCARGADO} programas', "
        "en runtime dara '10 programas'."
    )


def test_schemas_user_update_usa_constante():
    """schemas/user.py:UserUpdate.validar_limite_programas (segundo bloque)
    tambien debe usar la constante."""
    text = _read(SCHEMAS)
    # El archivo tiene 2 model_validators con el mismo nombre. Contamos
    # ocurrencias para asegurar que AMBOS usan la constante.
    count_constante = text.count("> MAX_PROGRAMAS_POR_ENCARGADO")
    count_mensaje_interpolado = text.count("{MAX_PROGRAMAS_POR_ENCARGADO} programas")
    assert count_constante >= 2, (
        f"Esperaba >= 2 usos de '> MAX_PROGRAMAS_POR_ENCARGADO' "
        f"(UserCreate + UserUpdate). Encontrado: {count_constante}"
    )
    assert count_mensaje_interpolado >= 2, (
        f"Esperaba >= 2 mensajes que interpolen la constante. "
        f"Encontrado: {count_mensaje_interpolado}"
    )


def test_user_service_usa_constante():
    """services/user_service.py:assign_course_to_users debe usar la constante."""
    text = _read(USER_SERVICE)
    assert "MAX_PROGRAMAS_POR_ENCARGADO" in text, (
        "services/user_service.py debe importar MAX_PROGRAMAS_POR_ENCARGADO"
    )
    # Buscar la firma con un regex simple (sin [^)]* que falla con -> None).
    # Capturamos desde "async def assign_course_to_users" hasta el proximo
    # "async def" o "class " al inicio de linea.
    match_func = re.search(
        r"^async def assign_course_to_users\b.*?(?=^async def |\nclass |\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    assert match_func is not None, (
        "No encontre assign_course_to_users en services/user_service.py"
    )
    func_body = match_func.group(0)
    assert ">= 5" not in func_body, (
        f"assign_course_to_users aun tiene '>= 5' hardcodeado. "
        f"Debe ser '>= MAX_PROGRAMAS_POR_ENCARGADO'. Body: {func_body[:500]}"
    )
    assert func_body.count("MAX_PROGRAMAS_POR_ENCARGADO") >= 1, (
        "assign_course_to_users debe usar MAX_PROGRAMAS_POR_ENCARGADO en su cuerpo"
    )


def test_frontend_userform_menciona_10():
    """kyc-client/src/lib/features/users/UserForm.svelte: error message debe
    decir '10 programas', no '5 programas'."""
    f = REPO.parent / "kyc-client" / "src" / "lib" / "features" / "users" / "UserForm.svelte"
    text = _read(f)
    assert "10 programas" in text, (
        f"UserForm.svelte debe decir '10 programas' en el mensaje de error"
    )
    assert "5 programas" not in text, (
        f"UserForm.svelte AUN dice '5 programas'. "
        f"F-2026-08-11-LIMITE-10 no aplicado en frontend."
    )


def test_frontend_courseform_menciona_10():
    """kyc-client/src/lib/features/courses/CourseForm.svelte: texto de ayuda
    y mensaje de alerta deben decir '10 programas'."""
    f = REPO.parent / "kyc-client" / "src" / "lib" / "features" / "courses" / "CourseForm.svelte"
    text = _read(f)
    # Al menos 2 ocurrencias: 1 en el alert, 1 en el <p> de ayuda
    count_10 = text.count("10 programas")
    count_5 = text.count("5 programas")
    assert count_10 >= 2, (
        f"CourseForm.svelte debe mencionar '10 programas' al menos 2 veces "
        f"(alert + texto ayuda). Encontrado: {count_10}"
    )
    assert count_5 == 0, (
        f"CourseForm.svelte AUN dice '5 programas' {count_5} veces. "
        f"F-2026-08-11-LIMITE-10 no aplicado."
    )
