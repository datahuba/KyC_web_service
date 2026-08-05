"""
F-MAESTRIA-EN-EJECUCION (2026-08-05, Kevin): seed de descuentos
institucionales del Organo Judicial.

Crea 3 descuentos predefinidos:
- Descuento 50% (Organo Judicial - Interno)
- Descuento 70% (?)
- Descuento 100% (Beca por merito / Exoneracion)

Estos descuentos se usan al cargar el Excel de la Maestria del
Organo Judicial (76% de los admitidos tienen 50%).

El script es IDEMPOTENTE: si el descuento ya existe, no lo duplica.
Se puede correr multiples veces sin riesgo.

Uso:
    python seed_descuentos_institucionales.py --dry-run    # Solo muestra
    python seed_descuentos_institucionales.py --apply      # Aplica
"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

from pymongo import MongoClient

MONGODB_URL = "mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC"
DB_NAME = "KyC"

# F-MAESTRIA-EN-EJECUCION (2026-08-05, Kevin): 3 descuentos institucionales
# del Organo Judicial basados en el analisis del Excel de la Maestria.
# El nombre incluye el porcentaje y la institucion para evitar confusion.
DESCUENTOS_INSTITUCIONALES = [
    {
        "nombre": "Descuento Organo Judicial Interno 50%",
        "porcentaje": 50.0,
        "descripcion": "Descuento del 50% para personal INTERNO del Organo Judicial. Aplica a programas del Postgrado UAGRM.",
        "curso_id": None,  # Aplica a todos los cursos
        "fecha_inicio": None,
        "fecha_fin": None,
        "activo": True,
        "es_institucional": True,  # F-MAESTRIA: flag para identificar descuentos auto-creados
        "institucion": "ORGANO_JUDICIAL",
    },
    {
        "nombre": "Descuento Organo Judicial Externo 30%",
        "porcentaje": 30.0,
        "descripcion": "Descuento del 30% para personal EXTERNO del Organo Judicial. Aplica a programas del Postgrado UAGRM.",
        "curso_id": None,
        "fecha_inicio": None,
        "fecha_fin": None,
        "activo": True,
        "es_institucional": True,
        "institucion": "ORGANO_JUDICIAL",
    },
    {
        "nombre": "Beca por Merito 100%",
        "porcentaje": 100.0,
        "descripcion": "Beca del 100% por merito academico. Aplica a programas del Postgrado UAGRM. Requiere aprobacion de CPD.",
        "curso_id": None,
        "fecha_inicio": None,
        "fecha_fin": None,
        "activo": True,
        "es_institucional": True,
        "institucion": "POSTGRADO_UAGRM",
    },
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo muestra que haria")
    parser.add_argument("--apply", action="store_true", help="Aplica los cambios")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: debes pasar --dry-run o --apply")
        sys.exit(1)

    modo = "DRY-RUN" if args.dry_run else "APPLY"
    print("=" * 80)
    print(f"F-MAESTRIA-EN-EJECUCION: Seed de descuentos institucionales")
    print(f"Modo: {modo}")
    print(f"Fecha: {datetime.utcnow().isoformat()}")
    print("=" * 80)

    client = MongoClient(MONGODB_URL, serverSelectionTimeoutMS=15000)
    db = client[DB_NAME]
    print(f"\n[OK] Conectado a MongoDB Atlas, DB={DB_NAME}")

    discounts_col = db["discounts"]
    existing = list(discounts_col.find({
        "nombre": {"$in": [d["nombre"] for d in DESCUENTOS_INSTITUCIONALES]}
    }))
    existing_names = {d["nombre"] for d in existing}

    print(f"\nDescuentos institucionales a sembrar: {len(DESCUENTOS_INSTITUCIONALES)}")
    print(f"Ya existentes: {len(existing)}")

    a_insertar = []
    for d in DESCUENTOS_INSTITUCIONALES:
        if d["nombre"] in existing_names:
            print(f"  [SKIP] {d['nombre']} (ya existe)")
            continue
        # Agregar timestamps
        d["created_at"] = datetime.utcnow()
        d["updated_at"] = datetime.utcnow()
        a_insertar.append(d)
        print(f"  [INSERT] {d['nombre']} ({d['porcentaje']}%)")

    if not a_insertar:
        print(f"\n[OK] Nada que insertar. Los 3 descuentos ya existen.")
        return

    print(f"\nDescuentos a insertar: {len(a_insertar)}")

    if args.dry_run:
        print("\n[DRY-RUN] No se aplica ningun cambio a la BD.")
        print("Para aplicar: python seed_descuentos_institucionales.py --apply")
        return

    # APPLY
    result = discounts_col.insert_many(a_insertar)
    print(f"\n[OK] {len(result.inserted_ids)} descuentos insertados")

    # Verificar
    print("\n--- Verificacion ---")
    all_inst = list(discounts_col.find({"es_institucional": True}))
    print(f"Total descuentos institucionales en BD: {len(all_inst)}")
    for d in all_inst:
        print(f"  - {d['nombre']} ({d['porcentaje']}%) - institucion={d.get('institucion', '?')}")


if __name__ == "__main__":
    main()
