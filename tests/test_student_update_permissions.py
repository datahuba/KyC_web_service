# -*- coding: utf-8 -*-
"""
F-FIX-STUDENT-EDIT-PERMISSIONS (2026-08-11, Kevin)

Bug: Lisa/encargado_curso y coordinadores no podian editar datos personales
de estudiantes (cumpleanos, celular, domicilio, etc.) porque el endpoint
PUT /students/{id} usaba `require_cpd`, que solo permite CPD/ADMIN/SUPERADMIN.
El frontend permitia abrir el StudentForm en modo edicion sin chequear el
permiso real, asi que el usuario veia el form, llenaba los datos, y al
guardar recibia 403 "Acceso restringido. Esta accion academica esta reservada
para el CPD o Administracion".

Fix (3 capas, lo mejor de lo mejor):
  1. BACKEND: api/students.py - cambiar `require_cpd` por `require_encargado_curso`
              en update_student_admin (linea ~320)
  2. FRONTEND: routes/app/students/+page.svelte - alinear canEditStudent con
              canCreateStudent/canEnrollStudent (incluir encargado_curso y
              coordinador) Y validar canEditStudent dentro de handleEdit()
  3. TESTS: este archivo verifica las 3 capas

Roles que DEBEN poder editar (despues del fix):
  - SUPERADMIN, ADMIN, CPD, COORDINADOR, ENCARGADO_CURSO

Roles que NO deben poder editar (se mantienen como antes):
  - DOCENTE, COBRANZA, ESTUDIANTE (estos usan /me o nada)
"""
from pathlib import Path

ROOT = Path(__file__).parent.parent
STUDENTS_API = ROOT / "api" / "students.py"
DEPENDENCIES = ROOT / "api" / "dependencies.py"
STUDENTS_PAGE = ROOT.parent / "kyc-client" / "src" / "routes" / "app" / "students" / "+page.svelte"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestBackendUpdateStudentAdmin:
    """BACKEND: api/students.py update_student_admin usa require_encargado_curso."""

    def test_update_student_admin_usa_require_encargado_curso(self):
        """
        El endpoint update_student_admin debe usar `require_encargado_curso`,
        NO `require_cpd`. Antes del fix usaba `require_cpd` y rompia para
        encargado_curso / coordinador.
        """
        content = read(STUDENTS_API)
        # Buscar el bloque del endpoint
        idx = content.find("def update_student_admin")
        assert idx > -1, "F-FIX-STUDENT-EDIT-PERMISSIONS: no se encontro update_student_admin en api/students.py"

        # Extraer el bloque del endpoint hasta el final de la funcion (1500 chars
        # es suficiente porque hay un comentario F-FIX-STUDENT-EDIT-PERMISSIONS
        # que explica el cambio, no podemos cortar antes).
        bloque = content[idx:idx + 1500]
        assert "require_encargado_curso" in bloque, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: update_student_admin debe usar "
            "`require_encargado_curso` (no `require_cpd`). Encargado_curso y "
            "coordinador no pueden editar estudiantes con require_cpd."
        )
        # Verificar que la linea de la dependency NO tenga require_cpd
        # (puede aparecer en el comentario explicativo, pero no en la firma)
        import re
        match = re.search(r"current_user:\s*User\s*=\s*Depends\(([^)]+)\)", bloque)
        assert match, "No se encontro la firma de current_user en update_student_admin"
        dep_usada = match.group(1).strip()
        assert dep_usada == "require_encargado_curso", (
            f"F-FIX-STUDENT-EDIT-PERMISSIONS: la dependency en update_student_admin "
            f"debe ser exactamente `require_encargado_curso`, se encontro: `{dep_usada}`"
        )

    def test_comentario_explica_el_fix(self):
        """Debe haber un comentario F-FIX-STUDENT-EDIT-PERMISSIONS explicando el cambio."""
        content = read(STUDENTS_API)
        assert "F-FIX-STUDENT-EDIT-PERMISSIONS" in content, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: debe haber comentario en api/students.py "
            "explicando el fix (cambio de require_cpd a require_encargado_curso)"
        )

    def test_require_encargado_curso_esta_importado(self):
        """require_encargado_curso debe estar importado en api/students.py."""
        content = read(STUDENTS_API)
        assert "require_encargado_curso" in content[:2000], (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: require_encargado_curso debe estar "
            "importado en api/students.py"
        )


class TestBackendHelperRequireEncargadoCurso:
    """BACKEND: api/dependencies.py require_encargado_curso permite los 5 roles correctos."""

    def test_require_encargado_curso_existe(self):
        content = read(DEPENDENCIES)
        assert "def require_encargado_curso" in content, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: require_encargado_curso debe existir "
            "en api/dependencies.py"
        )

    def test_require_encargado_curso_permite_los_5_roles(self):
        """
        Los 5 roles que deben poder editar estudiantes:
          - SUPERADMIN, ADMIN, CPD, COORDINADOR, ENCARGADO_CURSO
        """
        content = read(DEPENDENCIES)
        idx = content.find("def require_encargado_curso")
        bloque = content[idx:idx + 800]
        for rol in ["SUPERADMIN", "ADMIN", "CPD", "COORDINADOR", "ENCARGADO_CURSO"]:
            assert rol in bloque, (
                f"F-FIX-STUDENT-EDIT-PERMISSIONS: require_encargado_curso debe "
                f"permitir el rol {rol}"
            )

    def test_require_encargado_curso_NO_permite_docente(self):
        """El rol DOCENTE no debe estar en la lista de require_encargado_curso."""
        content = read(DEPENDENCIES)
        idx = content.find("def require_encargado_curso")
        bloque = content[idx:idx + 800]
        # DOCENTE solo edita su propio perfil si acaso, no el de estudiantes
        assert "DOCENTE" not in bloque, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: require_encargado_curso no debe "
            "incluir DOCENTE (los docentes no editan datos de estudiantes)"
        )


class TestFrontendCanEditStudent:
    """FRONTEND: routes/app/students/+page.svelte canEditStudent incluye los 5 roles."""

    def test_canEditStudent_incluye_encargado_curso(self):
        """
        canEditStudent debe incluir encargado_curso (antes NO lo incluia,
        estaba desincronizado con canCreateStudent y canEnrollStudent).
        """
        content = read(STUDENTS_PAGE)
        # Buscar la declaracion real de canEditStudent (let canEditStudent = ...)
        # (puede aparecer antes en un comentario, queremos la asignacion)
        import re
        m = re.search(r"let\s+canEditStudent\s*=\s*\$derived\(\[", content)
        assert m, "F-FIX-STUDENT-EDIT-PERMISSIONS: declaracion `let canEditStudent = $derived([...])` no encontrada"
        # Extraer el array de la declaracion (hasta el `]`)
        idx = m.end() - 1  # posicion del `[`
        end = content.find("]", idx)
        array_content = content[idx:end + 1]
        assert "encargado_curso" in array_content, (
            f"F-FIX-STUDENT-EDIT-PERMISSIONS: canEditStudent debe incluir "
            f"'encargado_curso'. Array actual: {array_content}"
        )
        assert "coordinador" in array_content, (
            f"F-FIX-STUDENT-EDIT-PERMISSIONS: canEditStudent debe incluir "
            f"'coordinador'. Array actual: {array_content}"
        )

    def test_canEditStudent_alineado_con_canCreateStudent(self):
        """
        canEditStudent y canCreateStudent deben permitir los MISMOS roles
        (alineacion que el bug original rompio).
        """
        content = read(STUDENTS_PAGE)
        import re
        m_create = re.search(r"let\s+canCreateStudent\s*=\s*\$derived\(\[([^\]]+)\]", content)
        m_edit = re.search(r"let\s+canEditStudent\s*=\s*\$derived\(\[([^\]]+)\]", content)
        assert m_create, "canCreateStudent no encontrado"
        assert m_edit, "canEditStudent no encontrado"
        roles_create = set(re.findall(r"'(\w+)'", m_create.group(1)))
        roles_edit = set(re.findall(r"'(\w+)'", m_edit.group(1)))
        assert roles_create == roles_edit, (
            f"F-FIX-STUDENT-EDIT-PERMISSIONS: canCreateStudent {sorted(roles_create)} "
            f"y canEditStudent {sorted(roles_edit)} deben permitir los MISMOS roles"
        )


class TestFrontendHandleEdit:
    """FRONTEND: handleEdit() debe chequear canEditStudent antes de abrir el form."""

    def test_handleEdit_valida_canEditStudent(self):
        """
        handleEdit(student) debe chequear canEditStudent antes de abrir el form.
        Antes del fix, handleEdit abria el form sin chequear, lo que causaba
        403 al guardar.
        """
        content = read(STUDENTS_PAGE)
        idx = content.find("function handleEdit")
        assert idx > -1, "F-FIX-STUDENT-EDIT-PERMISSIONS: handleEdit no existe en /app/students"
        # Extraer el bloque (300 chars)
        bloque = content[idx:idx + 300]
        assert "canEditStudent" in bloque, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: handleEdit() debe chequear "
            "canEditStudent antes de abrir el form. Si el usuario no puede "
            "editar, mostrar alert o no abrir el modal."
        )

    def test_handleEdit_retorna_si_no_puede_editar(self):
        """
        handleEdit debe retornar early (sin abrir el form) si canEditStudent
        es false. Patron esperado:
            if (!canEditStudent) {
                alert('error', '...');
                return;
            }
        """
        content = read(STUDENTS_PAGE)
        idx = content.find("function handleEdit")
        bloque = content[idx:idx + 400]
        assert ("return" in bloque and "alert" in bloque) or "canEditStudent" in bloque, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: handleEdit debe retornar early "
            "con un alert si el usuario no tiene canEditStudent"
        )


class TestRegresion:
    """Verifica que el fix no rompio otros endpoints relacionados."""

    def test_update_student_self_no_fue_tocado(self):
        """
        El endpoint PUT /students/me (auto-actualizacion del estudiante) NO
        debe haber sido tocado por este fix - sigue siendo para el propio
        estudiante.
        """
        content = read(STUDENTS_API)
        idx = content.find("def update_student_self")
        assert idx > -1, "update_student_self no encontrado"
        bloque = content[idx:idx + 300]
        assert "get_current_user" in bloque, (
            "F-FIX-STUDENT-EDIT-PERMISSIONS: update_student_self debe seguir "
            "usando get_current_user (es para auto-edicion del estudiante)"
        )
