"""Script de limpieza de enrollments huerfanos (cursos eliminados).
F-R35-CLEANUP (2026-08-04): borrar enrollments cuyo curso_id no existe en Course.

Uso:
    python cleanup-huerfanos.py --dry-run    # solo muestra que se borraria
    python cleanup-huerfanos.py --apply      # aplica los cambios
"""
import asyncio
import argparse
from motor.motor_asyncio import AsyncIOMotorClient


MONGODB_URL = "mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC"
DB_NAME = "KyC"


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Solo mostrar que se borraria")
    parser.add_argument("--apply", action="store_true", help="Aplicar la limpieza")
    args = parser.parse_args()

    if not args.dry_run and not args.apply:
        print("ERROR: especifica --dry-run o --apply")
        return

    # Conectar a MongoDB
    client = AsyncIOMotorClient(MONGODB_URL)
    db = client[DB_NAME]
    print(f"Conectado a MongoDB. DB: {DB_NAME}")

    # 1. Listar todos los curso_id de courses
    cursos = await db["courses"].find({}, {"_id": 1, "codigo": 1, "nombre_programa": 1}).to_list(None)
    curso_ids_visibles = {c["_id"] for c in cursos}
    print(f"\nCursos visibles: {len(cursos)}")
    for c in cursos:
        codigo = c.get("codigo", "?")
        nombre = (c.get("nombre_programa", "") or "")[:40]
        print(f"  {codigo:25s} | {nombre:40s} | id: {str(c['_id'])[:24]}")

    # 2. Listar todos los enrollments
    total_enrollments = await db["enrollments"].count_documents({})
    print(f"\nTotal enrollments: {total_enrollments}")

    # 3. Identificar huerfanos
    huerfanos = await db["enrollments"].find(
        {"curso_id": {"$nin": list(curso_ids_visibles)}}
    ).to_list(None)
    huerfanos_ids = [e["_id"] for e in huerfanos]
    print(f"Huerfanos (curso_id no existe en courses): {len(huerfanos)}")

    if not huerfanos:
        print("\nNo hay huerfanos que limpiar")
        client.close()
        return

    # 4. Mostrar agrupados por curso_id
    from collections import Counter
    por_curso = Counter(str(e["curso_id"]) for e in huerfanos)
    print("\nDetalle por curso_id (todos eliminados):")
    for cid, count in sorted(por_curso.items(), key=lambda x: -x[1]):
        ejemplo = next(e for e in huerfanos if str(e["curso_id"]) == cid)
        created = ejemplo.get("created_at")
        if hasattr(created, "strftime"):
            fecha = created.strftime("%Y-%m-%d %H:%M")
        else:
            fecha = str(created)[:16] if created else "?"
        print(f"  {cid[:24]} | {count:3d} enrollments | primer: {fecha}")

    # 5. Verificar pagos asociados
    huerfanos_ids_str = [str(eid) for eid in huerfanos_ids]
    pagos_asociados = await db["payments"].find(
        {"inscripcion_id": {"$in": huerfanos_ids_str}}
    ).to_list(None)
    print(f"\nPagos asociados a huerfanos: {len(pagos_asociados)}")
    if pagos_asociados:
        print("(estos pagos tambien se borraran para no dejar referencias rotas)")

    if args.dry_run:
        print("\n[DRY-RUN] No se borro nada. Corre con --apply para aplicar.")
        client.close()
        return

    if args.apply:
        print("\n[APPLY] Borrando...")

        # Borrar pagos primero (cascada)
        if pagos_asociados:
            pago_ids = [p["_id"] for p in pagos_asociados]
            result = await db["payments"].delete_many({"_id": {"$in": pago_ids}})
            print(f"  Pagos borrados: {result.deleted_count}")

        # Borrar enrollments
        result = await db["enrollments"].delete_many({"_id": {"$in": huerfanos_ids}})
        print(f"  Enrollments borrados: {result.deleted_count}")

        # Verificar
        total_after = await db["enrollments"].count_documents({})
        huerfanos_after = await db["enrollments"].count_documents(
            {"curso_id": {"$nin": list(curso_ids_visibles)}}
        )
        print(f"\nTotal enrollments: {total_after} (antes: {total_enrollments})")
        print(f"Huerfanos restantes: {huerfanos_after}")
        print(f"Diferencia: -{total_enrollments - total_after} enrollments")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
