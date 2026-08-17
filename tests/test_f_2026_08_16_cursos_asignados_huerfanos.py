"""
F-FIX-CURSOS-ASIGNADOS-HUERFANOS (2026-08-16)
=============================================

`delete_course()` solo hacia `course.delete()`. El id borrado seguia vivo
dentro de `users.cursos_asignados` de cada encargado / coordinador /
cobranza-segmentado que lo tuviera asignado.

Sintoma observado en produccion: SZSENCARGADO mostraba dos entradas
"Curso no encontrado" en /app/users. Los dos ids correspondian a cursos
creados el 2026-08-10 (04:17 y 04:22 UTC) y borrados despues, sin ninguna
inscripcion ni pago asociados.

No es cosmetico: `filtro_cursos_por_rol` arma sus queries a partir de esa
lista, asi que arrastrar ids muertos ensucia los filtros de todos los
listados que ese usuario ve.
"""

import io
import os


def _fuente_delete_course():
    ruta = os.path.join(os.path.dirname(__file__), "..", "services", "course_service.py")
    return io.open(ruta, encoding="utf-8").read()


def _cuerpo_delete_course():
    """
    Devuelve SOLO el codigo ejecutable de delete_course, sin el docstring.

    Necesario porque el docstring de la funcion cita `course.delete()` al
    explicar como era el bug; si no se recorta, un test de orden encuentra
    esa mencion en vez de la llamada real y falla por la razon equivocada.
    """
    src = _fuente_delete_course()
    inicio = src.index("async def delete_course")
    fin = src.index("async def ", inicio + 10)
    bloque = src[inicio:fin]

    # saltar el docstring triple-comillas si existe
    primera = bloque.find('"""')
    if primera != -1:
        segunda = bloque.find('"""', primera + 3)
        if segunda != -1:
            bloque = bloque[segunda + 3:]
    return bloque


class TestDeleteCourseLimpiaReferencias:
    def test_hace_pull_de_cursos_asignados(self):
        """El borrado debe sacar el id de los usuarios que lo tenian."""
        bloque = _cuerpo_delete_course()

        assert "$pull" in bloque, "delete_course ya no limpia cursos_asignados"
        assert "cursos_asignados" in bloque

    def test_limpia_antes_de_borrar(self):
        """
        Orden importante: si el delete fallara, es preferible haber limpiado
        de mas que dejar el id colgado apuntando a un curso inexistente.
        """
        bloque = _cuerpo_delete_course()

        pos_pull = bloque.index("$pull")
        pos_delete = bloque.index("course.delete()")
        assert pos_pull < pos_delete, "hay que limpiar las referencias ANTES del delete"

    def test_usa_el_modelo_user(self):
        src = _fuente_delete_course()
        assert "from models.user import User" in src
