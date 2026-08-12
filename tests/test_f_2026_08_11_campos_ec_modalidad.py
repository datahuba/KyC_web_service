"""
F-2026-08-11-CAMPOS-EC-MODALIDAD (reunion UAGRM 2026-08-11, seccion 4)
======================================================================

Kevin pidio agregar 3 campos al wizard de preinscripcion + backend:
- procedencia: codigo departamento Bolivia (SCZ, LPZ, CBA, TJA, CHS, POT, ORU, BEN, PND)
- modalidad: presencial o virtual
- carta_firmada_url: URL del PDF firmado por el director

Regla (de la reunion): si modalidad='virtual' o procedencia != 'SCZ',
la carta firmada es OBLIGATORIA.

Tambien fix de bug en consola del wizard: "r(...).trim is not a function"
cuando el usuario tipeaba en el input type="number" de descuentoPorcentaje.
El state se volvia number y number.prototype no tiene .trim().

Estos tests son de lectura estatica del codigo (mismo patron que
test_f_2026_08_11_campos_ec.py).
"""

import re
import sys
from pathlib import Path

REPO_BACKEND = Path(__file__).resolve().parent.parent
REPO_FRONTEND = REPO_BACKEND.parent / "kyc-client"

# ============================================================================
# BACKEND - modelo Student
# ============================================================================

def test_student_model_tiene_modalidad():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD: Student.modalidad existe."""
    student_py = (REPO_BACKEND / "models" / "student.py").read_text(encoding="utf-8")
    assert "modalidad: Optional[str]" in student_py, (
        "Student debe tener campo 'modalidad' (presencial | virtual). "
        "Si no existe, agregar la columna siguiendo el patron de las otras EC."
    )

def test_student_model_tiene_carta_firmada_url():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD: Student.carta_firmada_url existe."""
    student_py = (REPO_BACKEND / "models" / "student.py").read_text(encoding="utf-8")
    assert "carta_firmada_url: Optional[str]" in student_py, (
        "Student debe tener campo 'carta_firmada_url' (URL del PDF firmado)."
    )

# ============================================================================
# BACKEND - schemas
# ============================================================================

def test_pre_registration_submit_tiene_procedencia_modalidad_carta():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD: PreRegistrationSubmit acepta los 3 campos."""
    schema_py = (REPO_BACKEND / "schemas" / "pre_registration.py").read_text(encoding="utf-8")
    assert "procedencia: Optional[str]" in schema_py, "PreRegistrationSubmit debe aceptar procedencia"
    assert "modalidad: Optional[str]" in schema_py, "PreRegistrationSubmit debe aceptar modalidad"
    assert "carta_firmada_url: Optional[str]" in schema_py, "PreRegistrationSubmit debe aceptar carta_firmada_url"

def test_pre_registration_submit_valida_procedencia_bolivia():
    """Solo codigos de departamento validos de Bolivia (9 departamentos)."""
    schema_py = (REPO_BACKEND / "schemas" / "pre_registration.py").read_text(encoding="utf-8")
    # Verificar que el codigo valida SCZ, LPZ, CBA, TJA, CHS, POT, ORU, BEN, PND
    for code in ["SCZ", "LPZ", "CBA", "TJA", "CHS", "POT", "ORU", "BEN", "PND"]:
        assert f'"{code}"' in schema_py, f"Departamento {code} debe ser aceptado como procedencia"

def test_pre_registration_submit_valida_modalidad_presencial_virtual():
    """Modalidad solo puede ser 'presencial' o 'virtual'."""
    schema_py = (REPO_BACKEND / "schemas" / "pre_registration.py").read_text(encoding="utf-8")
    assert '"presencial"' in schema_py and '"virtual"' in schema_py, (
        "Modalidad debe aceptar solo 'presencial' o 'virtual'"
    )

def test_carta_firmada_requerida_si_provincia_o_virtual():
    """Regla de la reunion: carta obligatoria si modalidad=virtual o procedencia!=SCZ."""
    schema_py = (REPO_BACKEND / "schemas" / "pre_registration.py").read_text(encoding="utf-8")
    # Verificar que existe un validador carta_firmada_requerida_si_provincia_o_virtual
    assert "carta_firmada_requerida_si_provincia_o_virtual" in schema_py, (
        "Debe existir validador carta_firmada_requerida_si_provincia_o_virtual en PreRegistrationSubmit"
    )
    # Verificar que la regla este en el codigo
    regla = "modalidad == \"virtual\"" in schema_py or "modalidad == 'virtual'" in schema_py
    regla2 = "procedencia != \"SCZ\"" in schema_py or "procedencia != 'SCZ'" in schema_py
    assert regla and regla2, "La regla debe mencionar modalidad=virtual Y procedencia!=SCZ"

def test_schemas_student_tienen_los_3_campos():
    """StudentCreate, StudentResponse, StudentUpdateAdmin tienen los 3 campos."""
    schema_py = (REPO_BACKEND / "schemas" / "student.py").read_text(encoding="utf-8")
    # Contar ocurrencias de cada campo (3 schemas: Create, Response, UpdateAdmin)
    assert schema_py.count("procedencia: Optional[str]") >= 3, (
        "procedencia debe estar en StudentCreate, StudentResponse, StudentUpdateAdmin"
    )
    assert schema_py.count("modalidad: Optional[str]") >= 3, (
        "modalidad debe estar en StudentCreate, StudentResponse, StudentUpdateAdmin"
    )
    assert schema_py.count("carta_firmada_url: Optional[str]") >= 3, (
        "carta_firmada_url debe estar en StudentCreate, StudentResponse, StudentUpdateAdmin"
    )

# ============================================================================
# BACKEND - pre-registration service
# ============================================================================

def test_pr_service_submit_persiste_los_3_campos():
    """submit_public_form persiste procedencia/modalidad/carta_firmada_url en data."""
    svc = (REPO_BACKEND / "services" / "pre_registration_service.py").read_text(encoding="utf-8")
    # En la seccion del payload, los 3 campos deben estar
    assert '"procedencia"' in svc, "submit_public_form debe persistir procedencia"
    assert '"modalidad"' in svc, "submit_public_form debe persistir modalidad"
    assert '"carta_firmada_url"' in svc, "submit_public_form debe persistir carta_firmada_url"

def test_pr_service_approve_copia_los_3_campos():
    """approve_submission copia los 3 campos al Student creado."""
    svc = (REPO_BACKEND / "services" / "pre_registration_service.py").read_text(encoding="utf-8")
    # Aprox: la seccion del Student() debe incluir los 3 campos
    assert "procedencia=(data.get(\"procedencia\") or None)" in svc, (
        "approve_submission debe copiar procedencia al Student"
    )
    assert "modalidad=(data.get(\"modalidad\") or None)" in svc, (
        "approve_submission debe copiar modalidad al Student"
    )
    assert "carta_firmada_url=(data.get(\"carta_firmada_url\") or None)" in svc, (
        "approve_submission debe copiar carta_firmada_url al Student"
    )

# ============================================================================
# FRONTEND - servicio TS
# ============================================================================

def test_pr_service_ts_declara_los_3_campos():
    """PreRegistrationSubmit interface declara los 3 campos nuevos."""
    svc = (REPO_FRONTEND / "src" / "lib" / "services" / "pre-registration.service.ts").read_text(encoding="utf-8")
    assert "procedencia?" in svc, "Interfaz TS debe declarar procedencia?"
    assert "modalidad?" in svc, "Interfaz TS debe declarar modalidad?"
    assert "carta_firmada_url?" in svc, "Interfaz TS debe declarar carta_firmada_url?"

# ============================================================================
# FRONTEND - wizard svelte
# ============================================================================

def test_pr_page_svelte_tiene_3_state_vars_nuevas():
    """El wizard declara state vars para los 3 campos nuevos."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert "let procedencia = $state" in page, "State var procedencia debe existir"
    assert "let modalidad = $state" in page, "State var modalidad debe existir"
    assert "let cartaFirmadaUrl = $state" in page, "State var cartaFirmadaUrl debe existir"

def test_pr_page_svelte_tiene_3_inputs_nuevos():
    """El wizard tiene los 3 inputs en el HTML (paso 3)."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert 'id="pr-procedencia"' in page, "Input de procedencia debe existir"
    assert 'id="pr-modalidad"' in page, "Input de modalidad debe existir"
    assert 'id="pr-carta"' in page, "Input de carta firmada debe existir"

def test_pr_page_svelte_select_procedencia_tiene_9_departamentos():
    """El select de procedencia tiene los 9 departamentos de Bolivia."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    for code in ["SCZ", "LPZ", "CBA", "TJA", "CHS", "POT", "ORU", "BEN", "PND"]:
        assert f'value="{code}"' in page, f"Departamento {code} debe estar en el select de procedencia"

def test_pr_page_svelte_select_modidad_tiene_presencial_y_virtual():
    """El select de modalidad tiene las 2 opciones."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert 'value="presencial"' in page, "Opcion presencial debe existir"
    assert 'value="virtual"' in page, "Opcion virtual debe existir"

def test_pr_page_svelte_envia_los_3_campos_al_submit():
    """handleSubmit envia los 3 campos al backend."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert "procedencia:" in page, "handleSubmit debe enviar procedencia"
    assert "modalidad:" in page, "handleSubmit debe enviar modalidad"
    assert "carta_firmada_url:" in page, "handleSubmit debe enviar carta_firmada_url"

def test_pr_page_svelte_autosave_incluye_los_3_campos():
    """saveAutosave y loadAutosave manejan los 3 campos."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    # saveAutosave debe incluirlos en el payload
    assert "procedencia," in page, "saveAutosave debe persistir procedencia"
    assert "modalidad," in page, "saveAutosave debe persistir modalidad"
    assert "cartaFirmadaUrl," in page, "saveAutosave debe persistir cartaFirmadaUrl"
    # loadAutosave debe leerlos
    assert "data.procedencia" in page, "loadAutosave debe leer procedencia"
    assert "data.modalidad" in page, "loadAutosave debe leer modalidad"
    assert "data.cartaFirmadaUrl" in page, "loadAutosave debe leer cartaFirmadaUrl"

# ============================================================================
# F-FIX-TRIM-NUMBER: fix del bug "r(...).trim is not a function"
# ============================================================================

def test_fix_trim_number_validador_usa_string():
    """El validateField usa String(...) para evitar que number se rompa con .trim()."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    # La funcion validateField debe coercear a String con String(v ?? '').trim()
    assert "String(raw ?? '').trim()" in page or "String(raw ?? \"\").trim()" in page, (
        "validateField debe usar String() para coercear el state (puede ser number en type=number). "
        "Sin esto, cuando el usuario tipea en input type='number', el state se vuelve number "
        "y number.prototype no tiene .trim() -> TypeError en consola."
    )

def test_fix_trim_number_input_descuento_es_type_text():
    """El input de descuentoPorcentaje es type='text' para que el state siempre sea string."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    # El input pr-descuento debe ser type="text" (no number)
    # Buscamos el bloque con id="pr-descuento"
    m = re.search(r'<input\s+id="pr-descuento"[^>]*>', page, re.DOTALL)
    assert m, "Input pr-descuento debe existir"
    assert 'type="text"' in m.group(0), (
        "El input pr-descuento debe ser type='text' (no type='number') para que el state "
        "siempre sea string y no se rompa con .trim()."
    )

def test_fix_trim_number_explica_el_bug():
    """Hay un comentario que explica el bug del .trim para que no se repita."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    # Debe haber un comentario que mencione F-FIX-TRIM-NUMBER o el bug
    assert "F-FIX-TRIM-NUMBER" in page, (
        "Debe haber un comentario F-FIX-TRIM-NUMBER que explique el bug y la solucion. "
        "Esto es para que un futuro dev no rompa el fix cambiando el type a number de nuevo."
    )
