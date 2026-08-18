"""
F-CARGA-INICIAL (2026-08-18)
============================

El flujo de carga inicial de estudiantes (`POST /courses/{id}/initial-enrollments`)
no tenia NINGUN test, pese a ser por donde entran al sistema cursos enteros de
estudiantes con sus pagos historicos. La auditoria manual del 2026-08-14 tuvo
que probarlo a mano con scripts ad-hoc y encontro varios bugs de permisos que
un test habria atajado antes de produccion.

Estos tests fijan tres invariantes que ya se rompieron una vez cada una:

1. RACE CONDITION (F-CARGA-RACE-INSCRITOS): el endpoint procesa los items con
   `asyncio.gather`. `course` es UN objeto compartido por todas las tareas, y
   ni Course ni Student declaran `use_revision`, asi que Beanie no detecta
   escrituras concurrentes. Hacer `course.inscritos.append()` + `course.save()`
   dentro de cada tarea pierde escrituras: dos tareas guardan snapshots
   distintos y la ultima pisa a la anterior, dejando el curso con MENOS
   inscritos que los Enrollment realmente creados.

   El proyecto ya sabia esto: `enrollment_service.create_enrollment` lo
   advierte en su docstring, `enrollments/bulk` procesa secuencial a proposito
   y `student_service.import_students_from_excel` batchea con un lock. Este
   endpoint era el unico de los tres que no lo hacia.

2. PERMISOS DEL COORDINADOR (F-CARGA-COORD-SEGMENTA): para LECTURA,
   `filtro_cursos_por_rol` segmenta al coordinador por `cursos_asignados` sin
   excepcion. Para ESCRITURA, en cambio, los tres endpoints de carga solo
   restringian al ENCARGADO_CURSO, asi que un coordinador podia inscribir en
   cualquier curso del sistema aunque en los listados solo viera los suyos.
   Kevin decidio el 2026-08-18 unificarlo con el criterio de lectura.

3. CONTEO DE RESULTADOS (F-CARGA-CONTEO-ESTRUCTURADO): los totales de la
   respuesta se calculaban buscando substrings dentro del mensaje de cada
   resultado ("actualizaron pagos", "ya esta inscrito"). Cambiar la redaccion
   de un mensaje —algo que nadie considera un cambio de comportamiento— movia
   los numeros que ve el usuario, sin romper ningun test.

Son tests de inspeccion de codigo, igual que el resto de invariantes
estructurales de esta suite (ver test_f_2026_08_16_cursos_asignados_huerfanos):
la suite no levanta MongoDB, y lo que hay que impedir aca es justamente que
alguien vuelva a escribir el patron peligroso.
"""

import io
import os


def _fuente(*ruta_rel):
    ruta = os.path.join(os.path.dirname(__file__), "..", *ruta_rel)
    return io.open(ruta, encoding="utf-8").read()


def _cuerpo_funcion(src: str, nombre: str) -> str:
    """
    Devuelve el CODIGO EJECUTABLE de una funcion: su firma y su cuerpo, sin
    docstring y sin comentarios.

    Se quitan docstring y comentarios porque estos endpoints documentan
    justamente el patron peligroso que evitan (lo citan textualmente para
    explicar por que no hay que volver a escribirlo). Si no se recortan, un
    test que busca ese patron lo encuentra en la explicacion y falla por la
    razon equivocada — exactamente lo que paso al escribir estos tests.

    La firma SI se conserva: ahi vive la dependencia de permisos
    (`Depends(require_...)`), que es lo que varios de estos tests verifican.
    """
    inicio = src.index(f"async def {nombre}")
    fin = src.find("\nasync def ", inicio + 10)
    if fin == -1:
        fin = len(src)
    bloque = src[inicio:fin]

    # Quitar SOLO el tramo del docstring, conservando la firma que lo precede.
    primera = bloque.find('"""')
    if primera != -1:
        segunda = bloque.find('"""', primera + 3)
        if segunda != -1:
            bloque = bloque[:primera] + bloque[segunda + 3:]

    # Quitar las lineas que son solo comentario.
    return "\n".join(
        linea for linea in bloque.splitlines() if not linea.strip().startswith("#")
    )


# ============================================================================
# 1. Race condition en la carga inicial
# ============================================================================
class TestCargaInicialNoEscribeCursoEnParalelo:
    def test_procesar_item_no_guarda_el_curso(self):
        """
        `procesar_item` corre bajo gather: no puede guardar el Course.

        Si este test falla, volvio el bug que deja `course.inscritos`
        desincronizado respecto a los Enrollment creados.
        """
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        ini = cuerpo.index("async def procesar_item")
        fin = cuerpo.index("SEM = 5")
        interno = cuerpo[ini:fin]

        assert "await course.save()" not in interno, (
            "procesar_item volvio a guardar el Course dentro de una tarea "
            "concurrente: se pierden inscritos por last-writer-wins"
        )
        assert "await student.save()" not in interno, (
            "procesar_item volvio a guardar el Student dentro de una tarea "
            "concurrente"
        )

    def test_las_referencias_se_acumulan_bajo_lock(self):
        """Las tareas concurrentes anotan bajo lock, no escriben."""
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        assert "links_lock = asyncio.Lock()" in cuerpo
        assert "async with links_lock:" in cuerpo
        assert "inscritos_a_agregar.add(" in cuerpo

    def test_persiste_despues_del_gather(self):
        """La escritura real ocurre una sola vez, ya fuera de la concurrencia."""
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        pos_gather = cuerpo.index("await asyncio.gather(")
        pos_persistencia = cuerpo.index("if inscritos_a_agregar:")

        assert pos_persistencia > pos_gather, (
            "la persistencia de inscritos debe ocurrir DESPUES del gather"
        )
        assert "AddToSet" in cuerpo, (
            "lista_cursos_ids debe actualizarse con AddToSet para no pisar "
            "los otros cursos que el estudiante ya tuviera"
        )

    def test_relee_el_curso_antes_de_guardarlo(self):
        """
        El `course` en memoria puede haber quedado viejo mientras corrian las
        tareas, asi que se re-lee antes de guardar en vez de volcar un
        snapshot potencialmente desactualizado.
        """
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        assert "course_fresco = await Course.get(course.id)" in cuerpo


# ============================================================================
# 2. El coordinador queda segmentado por cursos_asignados tambien al escribir
# ============================================================================
class TestCoordinadorSegmentadoAlEscribir:
    def test_carga_inicial_restringe_al_coordinador(self):
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        assert "UserRole.COORDINADOR" in cuerpo, (
            "la carga inicial dejo de restringir al coordinador por curso"
        )
        assert "cursos_asignados" in cuerpo

    def test_bulk_de_inscripciones_restringe_al_coordinador(self):
        src = _fuente("api", "enrollments.py")
        cuerpo = _cuerpo_funcion(src, "create_enrollments_bulk")

        assert "UserRole.COORDINADOR" in cuerpo
        assert "cursos_asignados" in cuerpo

    def test_inscripcion_individual_restringe_al_coordinador(self):
        src = _fuente("api", "enrollments.py")
        cuerpo = _cuerpo_funcion(src, "create_enrollment")

        assert "UserRole.COORDINADOR" in cuerpo
        assert "cursos_asignados" in cuerpo

    def test_import_excel_restringe_al_coordinador(self):
        """Esta ruta ya lo hacia (FIX-ISSUE-253); el test evita que se pierda."""
        src = _fuente("api", "students.py")
        cuerpo = _cuerpo_funcion(src, "import_students")

        assert "UserRole.COORDINADOR" in cuerpo
        assert "cursos_asignados" in cuerpo

    def test_las_cuatro_rutas_de_escritura_coinciden(self):
        """
        Las cuatro puertas de entrada de inscripciones deben aplicar el mismo
        criterio. Ya hubo una desincronizacion entre ellas (ISSUE-253, donde
        import/excel rechazaba al EC mientras initial-enrollments lo permitia
        sobre el mismo curso).
        """
        rutas = [
            (("api", "courses.py"), "post_initial_enrollments"),
            (("api", "enrollments.py"), "create_enrollments_bulk"),
            (("api", "enrollments.py"), "create_enrollment"),
            (("api", "students.py"), "import_students"),
        ]
        for ruta, funcion in rutas:
            cuerpo = _cuerpo_funcion(_fuente(*ruta), funcion)
            assert "UserRole.ENCARGADO_CURSO" in cuerpo, f"{funcion} no restringe al EC"
            assert "UserRole.COORDINADOR" in cuerpo, f"{funcion} no restringe al coordinador"


# ============================================================================
# 3. El conteo de la respuesta no depende de la redaccion de los mensajes
# ============================================================================
class TestConteoEstructurado:
    def test_el_resultado_declara_su_accion(self):
        src = _fuente("api", "courses.py")

        assert "class InitialEnrollmentResultado" in src
        bloque = src[src.index("class InitialEnrollmentResultado"):]
        bloque = bloque[: bloque.index("class InitialEnrollmentResponse")]

        assert "accion:" in bloque, (
            "InitialEnrollmentResultado perdio el campo `accion`; el conteo "
            "volveria a depender del texto del mensaje"
        )
        for valor in ("creado", "actualizado", "ya_inscrito", "error"):
            assert valor in bloque, f"falta el valor de accion '{valor}'"

    def test_no_se_cuenta_por_substrings_del_mensaje(self):
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        assert '"actualizaron pagos" in' not in cuerpo, (
            "volvio el conteo por substring del mensaje"
        )
        assert '"ya esta inscrito" in' not in cuerpo.lower().replace("'", '"'), (
            "volvio el conteo por substring del mensaje"
        )
        assert "r.accion" in cuerpo, "el conteo debe leer el campo estructurado"

    def test_cada_retorno_declara_una_accion(self):
        """
        Todos los caminos de salida deben setear `accion`; si uno se olvida,
        cae en el default "error" y el resultado se cuenta como fallido
        aunque haya sido exitoso.
        """
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "post_initial_enrollments")

        retornos = cuerpo.count("InitialEnrollmentResultado(")
        acciones = cuerpo.count("accion=")

        assert acciones == retornos, (
            f"{retornos} construcciones de resultado pero solo {acciones} "
            "declaran accion"
        )


# ============================================================================
# 4. La resolucion del programa sigue el mismo criterio que editarlo
# ============================================================================
class TestResolucionMismoCriterioQueEdicion:
    def test_el_encargado_puede_reemplazar_la_resolucion_de_su_programa(self):
        """
        Antes `put_resolucion` exigia require_cpd, dejando al EC sin poder
        reemplazar la resolucion de su propio programa aunque SI puede
        subirla al crearlo y editar el resto del programa.
        """
        src = _fuente("api", "courses.py")
        cuerpo = _cuerpo_funcion(src, "put_resolucion")

        assert "require_encargado_curso" in cuerpo, (
            "put_resolucion volvio a exigir CPD; el EC no puede reemplazar "
            "la resolucion de su propio programa"
        )
        assert "cursos_asignados" in cuerpo, (
            "put_resolucion debe seguir limitando al EC/COORD a sus cursos"
        )
