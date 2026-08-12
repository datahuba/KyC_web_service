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
    assert 'id="pr-carta"' in page, "Input de carta firmada debe existir (file upload)"

def test_pr_page_svelte_carta_es_file_upload_no_url():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD-FILE (Kevin 22:17): la carta es file upload,
    no un input type='url' (UX mejor: el visitante elige el archivo de su maquina)."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    # Usamos regex para tolerar variaciones en la cantidad de tabs
    import re
    m = re.search(r'<input[^>]*id="pr-carta"[^>]*type="(\w+)"', page)
    assert m is not None, (
        "El input pr-carta debe existir (F-2026-08-11-CAMPOS-EC-MODALIDAD-FILE)"
    )
    input_type = m.group(1)
    assert input_type == "file", (
        f"El input pr-carta debe ser type='file' (file upload directo a Cloudinary), "
        f"no type='{input_type}' (que obligaba al usuario a subir el archivo a Drive y pegar un link)."
    )
    # Acepta PDF, JPG, PNG
    assert 'accept=".pdf,.jpg,.jpeg,.png' in page, (
        "El input file debe aceptar PDF, JPG y PNG"
    )

def test_pr_page_svelte_tiene_handler_upload_y_remove():
    """Handlers para subir y quitar el archivo de carta."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert "function handleCartaSelected" in page, (
        "Debe existir funcion handleCartaSelected que sube el archivo a Cloudinary"
    )
    assert "function removeCarta" in page, (
        "Debe existir funcion removeCarta que limpia el state"
    )
    assert "uploadCartaFirmada" in page, (
        "El wizard debe importar y usar uploadCartaFirmada del servicio"
    )

def test_api_pre_registrations_tiene_endpoint_upload_carta():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD-FILE: el backend expone el endpoint
    POST /pre-registrations/public/{slug}/upload-carta."""
    api_py = (REPO_BACKEND / "api" / "pre_registrations.py").read_text(encoding="utf-8")
    assert "/public/{slug}/upload-carta" in api_py, (
        "El router debe tener el endpoint /public/{slug}/upload-carta"
    )
    assert "upload_carta_firmada" in api_py, (
        "La funcion del endpoint debe llamarse upload_carta_firmada"
    )
    assert "upload_document" in api_py, (
        "El endpoint debe reusar upload_document de cloudinary_utils (no reinventar la rueda)"
    )

def test_api_pre_registrations_tiene_endpoint_upload_resolucion():
    """F-2026-08-11-EC-FIX-COUNTERS-403 (Kevin 23:36): el backend expone el
    endpoint POST /pre-registrations/public/{slug}/upload-resolucion-beca
    (NO /upload-resolucion) para que el estudiante suba la resolucion de
    BECA/DESCUENTO emitida por Vicerrectorado. Renombrado para distinguir
    de la resolucion del PROGRAMA que emite el admin/CPD."""
    api_py = (REPO_BACKEND / "api" / "pre_registrations.py").read_text(encoding="utf-8")
    assert "/public/{slug}/upload-resolucion-beca" in api_py, (
        "El router debe tener el endpoint /public/{slug}/upload-resolucion-beca (renombrado desde upload-resolucion)"
    )
    assert "upload_resolucion" in api_py, (
        "La funcion del endpoint debe llamarse upload_resolucion"
    )

def test_pr_service_persiste_resolucion_url():
    """F-2026-08-11-CAMPOS-EC-RESOLUCION: el servicio persiste resolucion_url
    en el data dict del PreRegistration y al aprobar lo copia al Student."""
    svc = (REPO_BACKEND / "services" / "pre_registration_service.py").read_text(encoding="utf-8")
    assert '"resolucion_url"' in svc, (
        "submit_public_form debe persistir resolucion_url en el data dict"
    )
    assert "resolucion_url=(data.get(\"resolucion_url\") or None)" in svc, (
        "approve_submission debe copiar resolucion_url al Student"
    )

def test_student_model_tiene_resolucion_url():
    """F-2026-08-11-CAMPOS-EC-RESOLUCION: Student.resolucion_url existe."""
    student_py = (REPO_BACKEND / "models" / "student.py").read_text(encoding="utf-8")
    assert "resolucion_url: Optional[str]" in student_py, (
        "Student debe tener campo 'resolucion_url' para la URL de la resolucion de beca/descuento"
    )

def test_api_pre_registrations_endpoints_lectura_usan_encargado_curso():
    """F-2026-08-11-EC-FIX-COUNTERS-403 (Kevin 23:36): los endpoints de
    LECTURA (list, get, counters) deben usar require_encargado_curso
    (NO require_cpd) para que encargado_curso y coordinador puedan ver
    el panel de pre-registros sin 403.

    El bug: el encargado EC veia 'Acceso restringido. La seccion academica
    esta reservada para el CPD o Administracion' al cargar el panel
    porque los endpoints get_de_list/submissions/counters usaban
    require_cpd. Los endpoints de DECISION (approve/reject) deben
    seguir usando require_cpd."""
    api_py = (REPO_BACKEND / "api" / "pre_registrations.py").read_text(encoding="utf-8")

    # Contar require_cpd: deben quedar SOLO 2 (approve + reject)
    cpd_count = api_py.count("Depends(require_cpd)")
    assert cpd_count == 2, (
        f"Debe haber exactamente 2 dependencias de require_cpd (approve + reject). "
        f"Encontre {cpd_count}. Los endpoints de LECTURA (list_forms, get_form, "
        f"list_submissions, counters) deben usar require_encargado_curso para "
        f"que EC/coord puedan acceder al panel sin 403."
    )

    # Verificar que los 4 endpoints de lectura usan require_encargado_curso
    import re
    # Patrones: "async def list_forms(", "async def get_form(", "async def list_submissions(", "async def counters("
    # seguido de (lineas intermedias) "Depends(require_encargado_curso)"
    lectura_funcs = ["list_forms", "get_form", "list_submissions", "counters"]
    for fname in lectura_funcs:
        # Buscar la firma de la funcion y verificar que use require_encargado_curso
        m = re.search(rf"async def {fname}\([^)]*\)[^:]*:[^#\n]*\n[^#\n]*Depends\((\w+)\)", api_py, re.DOTALL)
        if m:
            dep = m.group(1)
            assert dep == "require_encargado_curso", (
                f"F-2026-08-11-EC-FIX-COUNTERS-403: {fname}() debe usar "
                f"require_encargado_curso (no {dep}) para que EC/coord puedan acceder. "
                f"Sin este fix, el encargado de EC ve 'Acceso restringido' en el panel."
            )

def test_pre_registration_submit_tiene_resolucion_url():
    """F-2026-08-11-CAMPOS-EC-RESOLUCION: PreRegistrationSubmit acepta resolucion_url."""
    schema_py = (REPO_BACKEND / "schemas" / "pre_registration.py").read_text(encoding="utf-8")
    assert "resolucion_url: Optional[str]" in schema_py, (
        "PreRegistrationSubmit debe aceptar resolucion_url"
    )

def test_apiKyC_config_tiene_postFormData():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD-FILE: apiKyC.config.ts expone
    postFormData para multipart upload."""
    cfg = (REPO_FRONTEND / "src" / "lib" / "config" / "apiKyC.config.ts").read_text(encoding="utf-8")
    assert "async postFormData" in cfg, (
        "apiKyC debe tener un metodo postFormData para multipart (lo usa uploadCartaFirmada)"
    )
    # NO debe setear Content-Type a mano (el browser lo hace)
    assert "delete headersObj['Content-Type']" in cfg or 'delete headersObj["Content-Type"]' in cfg, (
        "postFormData debe eliminar Content-Type para que el browser ponga el boundary"
    )

def test_pr_service_ts_tiene_uploadCartaFirmada():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD-FILE: pre-registration.service.ts
    expone uploadCartaFirmada que usa postFormData."""
    svc = (REPO_FRONTEND / "src" / "lib" / "services" / "pre-registration.service.ts").read_text(encoding="utf-8")
    assert "export async function uploadCartaFirmada" in svc, (
        "pre-registration.service.ts debe exportar uploadCartaFirmada"
    )
    assert "postFormData" in svc, (
        "uploadCartaFirmada debe usar apiKyC.postFormData (no fetch manual)"
    )

def test_pr_service_ts_tiene_uploadResolucion():
    """F-2026-08-11-CAMPOS-EC-RESOLUCION: pre-registration.service.ts
    expone uploadResolucion que usa postFormData."""
    svc = (REPO_FRONTEND / "src" / "lib" / "services" / "pre-registration.service.ts").read_text(encoding="utf-8")
    assert "export async function uploadResolucion" in svc, (
        "pre-registration.service.ts debe exportar uploadResolucion"
    )

def test_pr_page_svelte_tiene_resolucion_input_y_handler():
    """F-2026-08-11-CAMPOS-EC-RESOLUCION: el wizard tiene el input file de
    resolucion y los handlers handleResolucionSelected + removeResolucion."""
    page = (REPO_FRONTEND / "src" / "routes" / "pre-registro" / "[slug]" / "+page.svelte").read_text(encoding="utf-8")
    assert "id=\"pr-resolucion\"" in page, "Input file pr-resolucion debe existir"
    assert "function handleResolucionSelected" in page, "Handler handleResolucionSelected debe existir"
    assert "function removeResolucion" in page, "Handler removeResolucion debe existir"
    assert "uploadResolucion" in page, "Wizard debe importar uploadResolucion del servicio"

def test_pre_registros_admin_page_muestra_carta_y_resolucion():
    """F-2026-08-11-CAMPOS-EC-MODALIDAD-VIEW (Kevin 22:37): el panel del
    encargado muestra las URLs de carta firmada y resolucion en la tabla
    de submissions, y un modal de detalle con TODO."""
    page = (REPO_FRONTEND / "src" / "routes" / "app" / "pre-registros" / "+page.svelte").read_text(encoding="utf-8")
    assert "openDetailModal" in page, "Funcion openDetailModal debe existir en la pagina admin"
    assert "showDetailModal" in page, "State showDetailModal debe existir"
    assert "detailSubmission" in page, "State detailSubmission debe existir"
    # La tabla debe mostrar badges de carta y resol como links
    assert "sub.data.carta_firmada_url" in page, "Tabla debe iterar sub.data.carta_firmada_url"
    assert "sub.data.resolucion_url" in page, "Tabla debe iterar sub.data.resolucion_url"
    # El modal debe mostrar preview de imagen para JPG/PNG
    assert "isCloudinaryImage" in page, "Helper isCloudinaryImage debe existir para mostrar preview inline"

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
