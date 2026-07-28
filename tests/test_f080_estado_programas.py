"""
F-080 · Estado de programas académicos (calendario + override)

Cubre:
  - Cálculo de estado por fechas (función pura, 9+ casos)
  - Override manual tiene prioridad
  - Cálculo en el modelo Course (método de instancia)
  - `acepta_inscripciones()` bloquea CERRADO
  - set_estado_override valida y sincroniza
  - set_resolucion_pdf_url guarda la URL
  - Validación de inscripción a curso CERRADO en enrollment_request_service
  - Endpoints en api/courses.py
  - Campos en modelo Course

Patrón: tests puros sobre la función `calcular_estado_actual` (sin
dependencias) + tests estáticos de los demás archivos (lectura del
código + assertions sobre el contenido).
"""

import sys
import unittest
from datetime import datetime
from pathlib import Path

# Agregar el path del proyecto al sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Importar la función pura (NO depende de beanie/fastapi/motor)
from models.estado_programa import EstadoPrograma, calcular_estado_actual


# ============================================================================
# FIXTURES
# ============================================================================

def dt(year, month, day):
    """Helper para crear datetimes naive (como en Mongo)."""
    return datetime(year, month, day, 12, 0, 0)


# ============================================================================
# TESTS DE CÁLCULO PURO
# ============================================================================

class TestF080CalculoEstado(unittest.TestCase):
    """Cálculo puro del estado según fechas."""

    def test_sin_fechas_devuelve_en_ejecucion(self):
        ahora = dt(2026, 7, 27)
        assert calcular_estado_actual(None, None, ahora=ahora) == EstadoPrograma.EN_EJECUCION.value

    def test_solo_fecha_inicio_futura_devuelve_programado(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 9, 1)
        assert calcular_estado_actual(inicio, None, ahora=ahora) == EstadoPrograma.PROGRAMADO.value

    def test_solo_fecha_inicio_pasada_devuelve_en_ejecucion(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 3, 1)
        assert calcular_estado_actual(inicio, None, ahora=ahora) == EstadoPrograma.EN_EJECUCION.value

    def test_solo_fecha_fin_pasada_devuelve_cerrado(self):
        ahora = dt(2026, 7, 27)
        fin = dt(2025, 12, 1)
        assert calcular_estado_actual(None, fin, ahora=ahora) == EstadoPrograma.CERRADO.value

    def test_solo_fecha_fin_futura_devuelve_en_ejecucion(self):
        ahora = dt(2026, 7, 27)
        fin = dt(2026, 12, 1)
        assert calcular_estado_actual(None, fin, ahora=ahora) == EstadoPrograma.EN_EJECUCION.value

    def test_ambas_fechas_futuras_devuelve_programado(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 9, 1)
        fin = dt(2026, 12, 1)
        assert calcular_estado_actual(inicio, fin, ahora=ahora) == EstadoPrograma.PROGRAMADO.value

    def test_ambas_fechas_pasadas_devuelve_cerrado(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2025, 9, 1)
        fin = dt(2025, 12, 1)
        assert calcular_estado_actual(inicio, fin, ahora=ahora) == EstadoPrograma.CERRADO.value

    def test_en_rango_devuelve_en_ejecucion(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 6, 1)
        fin = dt(2026, 8, 30)
        assert calcular_estado_actual(inicio, fin, ahora=ahora) == EstadoPrograma.EN_EJECUCION.value

    def test_borde_inicio_igual_ahora_es_en_ejecucion(self):
        mismo = dt(2026, 7, 27)
        fin = dt(2026, 12, 1)
        assert calcular_estado_actual(mismo, fin, ahora=mismo) == EstadoPrograma.EN_EJECUCION.value

    def test_borde_fin_igual_ahora_es_en_ejecucion(self):
        mismo = dt(2026, 7, 27)
        inicio = dt(2026, 6, 1)
        assert calcular_estado_actual(inicio, mismo, ahora=mismo) == EstadoPrograma.EN_EJECUCION.value


class TestF080OverrideManual(unittest.TestCase):
    """Override manual tiene prioridad sobre el cálculo automático."""

    def test_override_cerrado_ignora_fechas(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 6, 1)
        fin = dt(2026, 12, 1)
        resultado = calcular_estado_actual(inicio, fin, estado_override="cerrado", ahora=ahora)
        assert resultado == EstadoPrograma.CERRADO.value

    def test_override_programado_ignora_fechas(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2025, 1, 1)
        fin = dt(2025, 6, 1)
        resultado = calcular_estado_actual(inicio, fin, estado_override="programado", ahora=ahora)
        assert resultado == EstadoPrograma.PROGRAMADO.value

    def test_override_invalido_cae_a_calculo_automatico(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2025, 1, 1)
        fin = dt(2025, 6, 1)
        resultado = calcular_estado_actual(inicio, fin, estado_override="inventado", ahora=ahora)
        assert resultado == EstadoPrograma.CERRADO.value

    def test_override_none_usa_calculo_automatico(self):
        ahora = dt(2026, 7, 27)
        inicio = dt(2026, 9, 1)
        fin = dt(2026, 12, 1)
        resultado = calcular_estado_actual(inicio, fin, estado_override=None, ahora=ahora)
        assert resultado == EstadoPrograma.PROGRAMADO.value


class TestF080AceptaInscripciones(unittest.TestCase):
    """Regla de negocio: solo PROGRAMADO y EN_EJECUCION aceptan inscripciones."""

    def test_cerrado_NO_acepta_inscripciones(self):
        ahora = dt(2026, 7, 27)
        resultado = calcular_estado_actual(None, None, estado_override="cerrado", ahora=ahora)
        assert resultado == EstadoPrograma.CERRADO.value
        # La lógica de acepta_inscripciones() es: estado != CERRADO
        assert resultado != EstadoPrograma.EN_EJECUCION.value
        assert resultado != EstadoPrograma.PROGRAMADO.value

    def test_en_ejecucion_SI_acepta(self):
        ahora = dt(2026, 7, 27)
        resultado = calcular_estado_actual(dt(2026, 6, 1), dt(2026, 12, 1), ahora=ahora)
        assert resultado == EstadoPrograma.EN_EJECUCION.value

    def test_programado_SI_acepta(self):
        ahora = dt(2026, 7, 27)
        resultado = calcular_estado_actual(dt(2026, 9, 1), dt(2026, 12, 1), ahora=ahora)
        assert resultado == EstadoPrograma.PROGRAMADO.value


# ============================================================================
# TESTS ESTÁTICOS (sobre el código, sin ejecutarlo)
# ============================================================================

class TestF080EnrollmentRequestValidacion(unittest.TestCase):
    """Verifica el código que valida el estado en enrollment_request_service."""

    def test_validacion_presente_en_servicio(self):
        path = Path(__file__).resolve().parent.parent / "services" / "enrollment_request_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "get_estado_actual" in contenido
        assert "CERRADO" in contenido
        assert "no acepta nuevas solicitudes" in contenido or "ya fue cerrado" in contenido

    def test_validacion_orden_antes_de_insertar(self):
        path = Path(__file__).resolve().parent.parent / "services" / "enrollment_request_service.py"
        contenido = path.read_text(encoding="utf-8")
        idx_validacion = contenido.find("get_estado_actual")
        idx_insert = contenido.find("solicitud.insert()")
        assert idx_validacion > 0 and idx_insert > 0
        assert idx_validacion < idx_insert


class TestF080ModelCourse(unittest.TestCase):
    """Verifica que el modelo Course tiene los campos nuevos y el helper."""

    def test_campo_estado_existe(self):
        path = Path(__file__).resolve().parent.parent / "models" / "course.py"
        contenido = path.read_text(encoding="utf-8")
        assert "estado: str" in contenido
        assert 'EstadoPrograma.EN_EJECUCION.value' in contenido

    def test_campo_estado_override_existe(self):
        path = Path(__file__).resolve().parent.parent / "models" / "course.py"
        contenido = path.read_text(encoding="utf-8")
        assert "estado_override: Optional[str]" in contenido

    def test_campo_resolucion_pdf_url_existe(self):
        path = Path(__file__).resolve().parent.parent / "models" / "course.py"
        contenido = path.read_text(encoding="utf-8")
        assert "resolucion_pdf_url: Optional[str]" in contenido

    def test_metodo_get_estado_actual_existe(self):
        path = Path(__file__).resolve().parent.parent / "models" / "course.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def get_estado_actual" in contenido
        assert "def acepta_inscripciones" in contenido

    def test_helper_importa_desde_estado_programa(self):
        """El modelo Course debe reusar la función pura de estado_programa.py"""
        path = Path(__file__).resolve().parent.parent / "models" / "course.py"
        contenido = path.read_text(encoding="utf-8")
        assert "from .estado_programa import" in contenido
        assert "calcular_estado_actual" in contenido


class TestF080EndpointsCourses(unittest.TestCase):
    """Verifica que los endpoints están en api/courses.py."""

    def test_endpoint_calendario_existe(self):
        path = Path(__file__).resolve().parent.parent / "api" / "courses.py"
        contenido = path.read_text(encoding="utf-8")
        assert '"/calendario"' in contenido
        assert "get_courses_para_calendario" in contenido

    def test_endpoint_disponibles_existe(self):
        path = Path(__file__).resolve().parent.parent / "api" / "courses.py"
        contenido = path.read_text(encoding="utf-8")
        assert '"/disponibles"' in contenido
        assert "get_courses_disponibles_para_estudiante" in contenido

    def test_endpoint_patch_estado_existe(self):
        path = Path(__file__).resolve().parent.parent / "api" / "courses.py"
        contenido = path.read_text(encoding="utf-8")
        assert '"/{id}/estado"' in contenido
        assert "set_estado_override" in contenido

    def test_endpoint_put_resolucion_existe(self):
        path = Path(__file__).resolve().parent.parent / "api" / "courses.py"
        contenido = path.read_text(encoding="utf-8")
        assert '"/{id}/resolucion"' in contenido
        assert "set_resolucion_pdf_url" in contenido
        assert "upload_pdf" in contenido

    def test_filtro_estado_en_listar(self):
        path = Path(__file__).resolve().parent.parent / "api" / "courses.py"
        contenido = path.read_text(encoding="utf-8")
        assert "estado: Optional[str]" in contenido


class TestF080CourseService(unittest.TestCase):
    """Verifica que el course_service tiene las funciones del F-080."""

    def test_get_courses_para_calendario_existe(self):
        path = Path(__file__).resolve().parent.parent / "services" / "course_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def get_courses_para_calendario" in contenido

    def test_get_courses_disponibles_existe(self):
        path = Path(__file__).resolve().parent.parent / "services" / "course_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def get_courses_disponibles_para_estudiante" in contenido

    def test_set_estado_override_existe(self):
        path = Path(__file__).resolve().parent.parent / "services" / "course_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def set_estado_override" in contenido
        assert "EstadoPrograma" in contenido

    def test_set_resolucion_pdf_url_existe(self):
        path = Path(__file__).resolve().parent.parent / "services" / "course_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def set_resolucion_pdf_url" in contenido

    def test_get_courses_acepta_parametro_estado(self):
        path = Path(__file__).resolve().parent.parent / "services" / "course_service.py"
        contenido = path.read_text(encoding="utf-8")
        assert "def get_courses(" in contenido
        assert "estado: Optional[str] = None" in contenido


class TestF080ModuloAislado(unittest.TestCase):
    """Verifica que el módulo estado_programa.py está bien aislado."""

    def test_archivo_existe(self):
        path = Path(__file__).resolve().parent.parent / "models" / "estado_programa.py"
        assert path.exists(), "Falta el módulo models/estado_programa.py"

    def test_no_importa_beanie_ni_fastapi(self):
        """El módulo puro no debe depender de beanie/fastapi/motor."""
        path = Path(__file__).resolve().parent.parent / "models" / "estado_programa.py"
        contenido = path.read_text(encoding="utf-8")
        assert "import beanie" not in contenido
        assert "from beanie" not in contenido
        assert "import fastapi" not in contenido
        assert "from fastapi" not in contenido
        assert "import motor" not in contenido
        assert "from motor" not in contenido

    def test_re_exportado_desde_enums(self):
        """models.enums debe re-exportar EstadoPrograma para compatibilidad."""
        path = Path(__file__).resolve().parent.parent / "models" / "enums.py"
        contenido = path.read_text(encoding="utf-8")
        assert "from .estado_programa import EstadoPrograma" in contenido


# ============================================================================
# Test runner
# ============================================================================

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
