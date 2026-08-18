"""
F-FIX-FECHA-FIN-INVERTIDA (2026-08-18)
======================================

La validacion de `fecha_fin` en la creacion de programas estaba AL REVES y se
contradecia a si misma:

    if not es_historico_flag:      # si NO es historico
        if fin_dt >= now_naive:    # y la fecha fin es FUTURA
            raise ...              # -> error

O sea, le exigia a un programa EN EJECUCION haber terminado en el pasado. Y el
propio mensaje de error ofrecia como salida "usa una fecha futura si es un
programa programado o en ejecucion", que era exactamente lo que disparaba el
error.

Impacto real: al crear la maestria MAES-GTAF-2026/1 (de mayo 2026 a diciembre
2027) hubo que poner una fecha_fin FALSA del pasado para poder guardar, y
quedo un dato incorrecto en produccion. Ademas el frontend mostraba un aviso
—"como encargado solo puedes crear programas historicos"— que era el reflejo
de esta misma regla invertida.

La regla correcta: el que cierra en el pasado es el HISTORICO. Un programa en
ejecucion o programado termina en el futuro, y eso es lo normal.
"""

import io
import os


def _bloque_validacion():
    ruta = os.path.join(os.path.dirname(__file__), "..", "api", "courses.py")
    src = io.open(ruta, encoding="utf-8").read()
    ini = src.index("F-FIX-FECHA-FIN-INVERTIDA")
    fin = src.index("try:", ini)
    bloque = src[ini:fin]
    # Sin comentarios: el fix explica el patron viejo citandolo.
    return "\n".join(
        l for l in bloque.splitlines() if not l.strip().startswith("#")
    )


class TestLaValidacionMiraAlHistorico:
    def test_solo_valida_cuando_es_historico(self):
        """
        El guard tiene que ser `if es_historico_flag:`, no su negacion. Si
        alguien lo invierte de nuevo, vuelve a ser imposible cargar un
        programa vigente.
        """
        bloque = _bloque_validacion()

        assert "if es_historico_flag:" in bloque
        assert "if not es_historico_flag:" not in bloque

    def test_un_programa_vigente_no_tiene_restriccion_de_fecha_fin(self):
        """
        No debe quedar ninguna rama que rechace una fecha_fin futura para
        programas no historicos.
        """
        bloque = _bloque_validacion()
        assert bloque.count("raise HTTPException") == 1, (
            "deberia quedar una sola validacion, la del historico"
        )

    def test_el_mensaje_ya_no_se_contradice(self):
        """
        El mensaje viejo decia "debe ser ANTERIOR a hoy cuando NO es
        historico" y a la vez sugeria usar una fecha futura.
        """
        ruta = os.path.join(os.path.dirname(__file__), "..", "api", "courses.py")
        src = io.open(ruta, encoding="utf-8").read()
        cuerpo = "\n".join(
            l for l in src.splitlines() if not l.strip().startswith("#")
        )
        assert "debe ser ANTERIOR a hoy cuando el programa" not in cuerpo

    def test_el_mensaje_orienta_a_la_solucion_correcta(self):
        """
        Si alguien marca historico un programa vigente, el mensaje tiene que
        decirle que cambie el TIPO, no que falsee la fecha.
        """
        bloque = _bloque_validacion()
        assert "En ejecucion" in bloque or "Proximo" in bloque
