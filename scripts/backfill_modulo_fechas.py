"""
Backfill de fechas de módulos
==============================

Script one-shot que copia `Course.fecha_inicio` y `Course.fecha_fin` a cada
`Course.modulos[i].fecha_inicio` y `Course.modulos[i].fecha_fin` para los
cursos que aún no tienen estas fechas pobladas.

Por qué existe
--------------
F-CERTIFICADOS (2026-07-29): los Certificados de Notas muestran la fecha de
inicio y fin de cada módulo (ej: "26/10/2020 al 30/10/2020"). Para que el
PDF se vea bien en los cursos existentes que aún no tienen estas fechas a
nivel de módulo, las copiamos del rango del programa completo como
aproximación razonable.

Uso
---
Desde KyC_web_service/:

    # Modo dry-run (default): muestra qué cambiaría sin tocar la BD
    .venv/Scripts/python.exe scripts/backfill_modulo_fechas.py

    # Aplicar cambios
    .venv/Scripts/python.exe scripts/backfill_modulo_fechas.py --apply

Salida esperada
---------------
- Lista de cursos con módulos SIN fechas (los que se actualizarían).
- Resumen: N cursos actualizados, M módulos actualizados.
"""

import argparse
import asyncio
import sys
from datetime import datetime

# Asegurar que podemos importar los modelos del backend
sys.path.insert(0, ".")

from core.database import init_db  # noqa: E402
from models.course import Course  # noqa: E402


async def backfill(dry_run: bool = True):
    print(f"[BACKFILL] fecha_inicio/fin en Modulo")
    print(f"[BACKFILL] Modo: {'DRY-RUN (no se aplica)' if dry_run else 'APPLY (cambia la BD)'}")
    print("=" * 70)

    await init_db()

    # Cursos activos con módulos (al menos 1 módulo)
    cursos = await Course.find({"modulos.0": {"$exists": True}}).to_list()
    print(f"[BACKFILL] Cursos con módulos: {len(cursos)}")

    cursos_actualizados = 0
    modulos_actualizados = 0

    for c in cursos:
        # Saltar si el curso no tiene fechas de programa
        if c.fecha_inicio is None and c.fecha_fin is None:
            print(f"  · {c.codigo} — sin fechas de programa, saltando")
            continue

        cambios = 0
        for m in c.modulos:
            if m.fecha_inicio is None and m.fecha_fin is None:
                # Aproximación: copiar las fechas del programa
                m.fecha_inicio = c.fecha_inicio
                m.fecha_fin = c.fecha_fin
                cambios += 1
                modulos_actualizados += 1
            elif m.fecha_inicio is None:
                m.fecha_inicio = c.fecha_inicio
                cambios += 1
                modulos_actualizados += 1
            elif m.fecha_fin is None:
                m.fecha_fin = c.fecha_fin
                cambios += 1
                modulos_actualizados += 1

        if cambios > 0:
            print(f"  ✓ {c.codigo} — {cambos} módulo(s) actualizados")
            if not dry_run:
                await c.save()
            cursos_actualizados += 1

    print("=" * 70)
    print(f"[BACKFILL] Cursos actualizados: {cursos_actualizados}")
    print(f"[BACKFILL] Módulos actualizados: {modulos_actualizados}")
    if dry_run:
        print(f"[BACKFILL] Modo DRY-RUN. Para aplicar: scripts/backfill_modulo_fechas.py --apply")
    else:
        print(f"[BACKFILL] Cambios aplicados a la BD.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill de fechas en módulos")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica los cambios a la BD (sin este flag, solo muestra el preview)",
    )
    args = parser.parse_args()

    asyncio.run(backfill(dry_run=not args.apply))
