"""
F-FIX-PORPAGO-FILTRO-CURSO (2026-08-16)
=======================================

En Gestion de Pagos > vista "Por Pago", elegir un programa no filtraba:
devolvia SIEMPRE lo mismo. Reportado por Kevin ("vi los filtros y muestran
todos en vez de los que se seleccionan").

Causa, en `get_matriz_por_pago`:

    if curso_id is not None:
        match["curso_id"] = curso_id          # <- ObjectId pelado

    ...mas abajo, la exclusion de historicos:

    if "curso_id" in match and isinstance(match["curso_id"], dict) and "$in" in ...:
        match["curso_id"]["$nin"] = historicos
    else:
        match["curso_id"] = {"$nin": historicos}   # <- PISA el filtro

Como `match["curso_id"]` era un ObjectId y no un dict, la condicion daba
False y el `else` reemplazaba el filtro entero. La query terminaba siendo
"todos los pagos de cursos no historicos", sin importar que curso se
hubiera pedido.

Verificado en produccion antes del fix, con cache-busting: pedir sin
filtro, IA, DDU o MAE devolvia los mismos 54 registros de IA en los cuatro
casos, y `filtros_aplicados.curso_id` reportaba IA incluso cuando no se
mandaba ningun curso. El unico curso no historico con pagos es IA, de ahi
que siempre saliera ese.

Regla que fija este test: una seleccion EXPLICITA de curso manda, incluso
sobre la exclusion de historicos — para auditar un programa historico hay
que poder abrirlo.
"""

import io
import os


def _cuerpo_get_matriz_por_pago():
    """Codigo de la funcion sin su docstring (los comentarios citan el bug viejo)."""
    ruta = os.path.join(os.path.dirname(__file__), "..", "services", "payment_service.py")
    src = io.open(ruta, encoding="utf-8").read()
    inicio = src.index("async def get_matriz_por_pago")
    fin = src.index("\nasync def ", inicio + 10)
    return src[inicio:fin]


class TestSeleccionExplicitaDeCursoManda:
    def test_el_curso_pedido_no_se_pisa_con_la_exclusion_de_historicos(self):
        """
        El `$nin` de historicos debe estar en la rama `else` — es decir, solo
        cuando NO se pidio un curso concreto. Si vuelve a ejecutarse siempre,
        el filtro de curso se pierde otra vez.
        """
        cuerpo = _cuerpo_get_matriz_por_pago()

        pos_if = cuerpo.index("if curso_id is not None:")
        pos_nin = cuerpo.index('"$nin": list(curso_historico_ids)')
        pos_else = cuerpo.index("else:", pos_if)

        assert pos_if < pos_else < pos_nin, (
            "la exclusion de historicos debe estar en el else de "
            "`if curso_id is not None`, no ejecutarse siempre"
        )

    def test_la_consulta_de_historicos_no_corre_si_hay_curso_explicito(self):
        """Ademas de correcto, evita una query inutil a Course."""
        cuerpo = _cuerpo_get_matriz_por_pago()
        pos_if = cuerpo.index("if curso_id is not None:")
        pos_query = cuerpo.index("Course.es_historico == True")
        pos_else = cuerpo.index("else:", pos_if)
        assert pos_else < pos_query, (
            "la busqueda de cursos historicos debe quedar dentro del else"
        )

    def test_se_conserva_el_alcance_por_rol(self):
        """
        Un rol segmentado (cursos_permitidos) sigue restandole los historicos
        a su conjunto permitido, sin perder el `$in`.
        """
        cuerpo = _cuerpo_get_matriz_por_pago()
        assert 'isinstance(match.get("curso_id"), dict)' in cuerpo
        assert '"$in" in match["curso_id"]' in cuerpo
        assert 'match["curso_id"]["$nin"] = list(curso_historico_ids)' in cuerpo
