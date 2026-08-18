"""
F-FIX-AJUSTE-BORRA-NOTAS (2026-08-18)
=====================================

`api/admin_accounting.py` reemplazaba el arreglo de modulos ENTERO por
`MODULOS_CANONICOS` cuando se corria un ajuste de tipo "completo":

    enrollment.modulos = [ModuloEstado(**m) for m in MODULOS_CANONICOS]

`MODULOS_CANONICOS` solo describe la parte FINANCIERA (nombre, costo,
monto_pagado, estado). Como `ModuloEstado` nace con `nota=None` y
`estado_academico="Cursando"`, un ajuste CONTABLE borraba de paso todo el
historial ACADEMICO: la nota, si aprobo o reprobo, la asistencia, el
borrador del docente y la marca de que CPD ya lo habia validado.

Lo peor es que lo hacia en silencio. Nadie revisa notas despues de correr un
ajuste de plata, asi que se habria descubierto recien cuando un alumno abre
su libreta y su calificacion no esta.

Como se encontro: Kevin reporto que no veia las notas de Inteligencia
Artificial. Se comparo el backup del 17-ago contra produccion y resultaron
IDENTICOS (16 con nota de 54), asi que en ese caso NO se habia ejecutado
este ajuste — los modulos seguian siendo 5 y el canonico tiene 6. Pero al
buscar la causa aparecio este borrado latente, que todavia no se habia
disparado.

Estos tests fijan que un ajuste financiero no puede tocar lo academico.
"""

import pytest

from models.enrollment import ModuloEstado
from api.admin_accounting import MODULOS_CANONICOS


CAMPOS_ACADEMICOS = (
    "nota",
    "estado_academico",
    "nota_borrador",
    "estado_validacion_nota",
    "asistencia_porcentaje",
    "iniciado_en",
    "finalizado_en",
)


def _fusionar(modulos_previos):
    """
    Replica la fusion que hace el endpoint. Se mantiene igual que el codigo
    de `_aplicar_ajuste` para tipo="completo".
    """
    nuevos = []
    for i, plantilla in enumerate(MODULOS_CANONICOS):
        datos = dict(plantilla)
        if i < len(modulos_previos):
            anterior = modulos_previos[i]
            for campo in CAMPOS_ACADEMICOS:
                valor = getattr(anterior, campo, None)
                if valor is not None:
                    datos[campo] = valor
        nuevos.append(ModuloEstado(**datos))
    return nuevos


class TestElCanonicoNoTraeDatosAcademicos:
    def test_la_plantilla_no_define_notas(self):
        """
        Si alguien agrega `nota` al canonico, estaria imponiendo la misma
        calificacion a todos los estudiantes ajustados.
        """
        for m in MODULOS_CANONICOS:
            assert "nota" not in m, "MODULOS_CANONICOS no debe fijar notas"
            assert "nota_borrador" not in m

    def test_un_modulo_creado_del_canonico_nace_sin_nota(self):
        """Es justamente por esto que hacia falta arrastrar lo anterior."""
        mod = ModuloEstado(**MODULOS_CANONICOS[0])
        assert mod.nota is None
        assert mod.estado_academico == "Cursando"


class TestElAjusteConservaLoAcademico:
    def test_conserva_la_nota_y_el_estado_academico(self):
        previos = [
            ModuloEstado(
                nombre="M1: Fundamentos de IA",
                costo=252.0,
                monto_pagado=252.0,
                estado="Pagado",
                nota=94.0,
                estado_academico="Aprobado",
                estado_validacion_nota="validada",
            )
        ]

        nuevos = _fusionar(previos)

        assert nuevos[0].nota == 94.0, "el ajuste contable borro la nota"
        assert nuevos[0].estado_academico == "Aprobado"
        assert nuevos[0].estado_validacion_nota == "validada"

    def test_conserva_el_borrador_del_docente_sin_validar(self):
        """
        Perder un borrador es igual de grave: el docente ya hizo el trabajo y
        CPD todavia no lo valido, asi que no hay de donde recuperarlo.
        """
        previos = [
            ModuloEstado(
                nombre="M1",
                costo=252.0,
                nota_borrador=78.0,
                estado_validacion_nota="pendiente_validacion",
            )
        ]

        nuevos = _fusionar(previos)

        assert nuevos[0].nota_borrador == 78.0
        assert nuevos[0].estado_validacion_nota == "pendiente_validacion"

    def test_conserva_asistencia_y_fechas_del_cronograma(self):
        from datetime import datetime, timezone

        inicio = datetime(2026, 5, 20, tzinfo=timezone.utc)
        fin = datetime(2026, 6, 20, tzinfo=timezone.utc)
        previos = [
            ModuloEstado(
                nombre="M1",
                costo=252.0,
                asistencia_porcentaje=85.0,
                iniciado_en=inicio,
                finalizado_en=fin,
            )
        ]

        nuevos = _fusionar(previos)

        assert nuevos[0].asistencia_porcentaje == 85.0
        assert nuevos[0].iniciado_en == inicio
        assert nuevos[0].finalizado_en == fin

    def test_si_aplica_lo_financiero_del_canonico(self):
        """
        El ajuste debe seguir haciendo su trabajo: lo financiero SI se pisa,
        que es el proposito de la herramienta.
        """
        previos = [
            ModuloEstado(
                nombre="M1", costo=999.0, monto_pagado=0.0,
                estado="Pendiente", nota=94.0,
            )
        ]

        nuevos = _fusionar(previos)

        assert nuevos[0].costo == MODULOS_CANONICOS[0]["costo"]
        assert nuevos[0].monto_pagado == MODULOS_CANONICOS[0]["monto_pagado"]
        assert nuevos[0].estado == "Pagado"
        # ...pero sin llevarse la nota puesta
        assert nuevos[0].nota == 94.0

    def test_los_modulos_extra_del_canonico_nacen_vacios(self):
        """
        El canonico tiene 6 modulos; una inscripcion puede tener 5 (es el caso
        real de DIPL-IA-2026). El sexto no tiene historial que preservar.
        """
        previos = [
            ModuloEstado(nombre=f"M{i+1}", costo=252.0, nota=80.0 + i)
            for i in range(5)
        ]

        nuevos = _fusionar(previos)

        assert len(nuevos) == len(MODULOS_CANONICOS)
        for i in range(5):
            assert nuevos[i].nota == 80.0 + i
        assert nuevos[-1].nota is None
        assert nuevos[-1].estado_academico == "Cursando"

    def test_un_curso_entero_no_pierde_ninguna_nota(self):
        """
        El escenario que motivo el fix: correr el ajuste sobre un curso con
        notas ya validadas no puede perder ni una.
        """
        previos = [
            ModuloEstado(
                nombre=f"M{i+1}", costo=252.0, nota=float(60 + i * 5),
                estado_academico="Aprobado", estado_validacion_nota="validada",
            )
            for i in range(5)
        ]

        nuevos = _fusionar(previos)

        notas_antes = [m.nota for m in previos]
        notas_despues = [m.nota for m in nuevos[:5]]
        assert notas_despues == notas_antes
        assert all(m.estado_validacion_nota == "validada" for m in nuevos[:5])


class TestElCodigoRealUsaLaFusion:
    def test_el_endpoint_ya_no_reemplaza_a_ciegas(self):
        """
        Evita que alguien vuelva a la linea de una sola pasada. Se lee el
        fuente porque la suite no levanta MongoDB para ejercitar el endpoint.
        """
        import io
        import os

        ruta = os.path.join(os.path.dirname(__file__), "..", "api", "admin_accounting.py")
        src = io.open(ruta, encoding="utf-8").read()

        # Quitar comentarios: el fix explica el patron viejo citandolo.
        codigo = "\n".join(
            l for l in src.splitlines() if not l.strip().startswith("#")
        )

        assert "enrollment.modulos = [ModuloEstado(**m) for m in MODULOS_CANONICOS]" not in codigo, (
            "volvio el reemplazo a ciegas que borra las notas"
        )
        assert "CAMPOS_ACADEMICOS" in codigo
        assert "modulos_previos" in codigo
