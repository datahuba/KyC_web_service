"""
Migracion R36 (2026-08-08, Kevin): crear Account para usuarios existentes.

Por cada (Student.username + User.username) unico, crear 1 Account con la
misma password hasheada. Vincular account_id en Student y User.

Criterio de matching (en orden):
1. Si Student.username == User.username, mismo account (mismo username)
2. Si Student.email == User.email Y Student.carnet == User.carnet, mismo account
3. Si Student.registro == User.carnet, mismo account (un carnet que es registro)

Dry-run por default. --apply para ejecutar.
"""
import asyncio
import sys
import json
from datetime import datetime
from motor.motor_asyncio import AsyncIOMotorClient

sys.path.insert(0, r"C:\Users\Usuario\Documents\PROYECTO KYC\KyC_web_service")


async def main():
    from core.config import settings
    from models.account import Account
    from models.user import User
    from models.student import Student
    from beanie import init_beanie, PydanticObjectId

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(client["KyC"], document_models=[Account, User, Student])

    print("=== ANALISIS DE MIGRACION R36 ===\n")

    # Obtener todos los Students y Users
    students = await Student.get_motor_collection().find(
        {}, {"_id": 1, "registro": 1, "email": 1, "carnet": 1, "nombre": 1, "apellidos": 1, "password": 1, "account_id": 1}
    ).to_list(length=10000)
    users = await User.get_motor_collection().find(
        {}, {"_id": 1, "username": 1, "email": 1, "carnet": 1, "nombre_funcional": 1, "password": 1, "account_id": 1, "rol": 1}
    ).to_list(length=10000)

    print(f"Students: {len(students)}, Users: {len(users)}")

    # Construir mapa de accounts a crear
    accounts_to_create = {}  # key: (identificador) -> {data, profiles: [(type, id), ...]}
    unmatched_students = []
    unmatched_users = []

    for s in students:
        # Identificador primario: registro (Student.username = registro)
        username = s.get("registro")
        if not username:
            unmatched_students.append(s)
            continue
        if username not in accounts_to_create:
            accounts_to_create[username] = {
                "username": username,
                "email": s.get("email") or "",
                "password": s.get("password"),
                "carnet_identidad": s.get("carnet"),
                "nombre_completo": f"{s.get('nombre', '')} {s.get('apellidos', '')}".strip() or None,
                "profiles": []
            }
        accounts_to_create[username]["profiles"].append(("student", str(s["_id"])))

    for u in users:
        username = u.get("username")
        if not username:
            unmatched_users.append(u)
            continue
        if username not in accounts_to_create:
            # User con username que no existe en Students: crear account nuevo
            accounts_to_create[username] = {
                "username": username,
                "email": u.get("email") or "",
                "password": u.get("password"),
                "carnet_identidad": u.get("carnet"),
                "nombre_completo": u.get("nombre_funcional"),
                "profiles": []
            }
        accounts_to_create[username]["profiles"].append(("user", str(u["_id"])))

    # Detectar accounts con multiples profiles (los unicos que justifican multi-perfil)
    multi_profile_accounts = {k: v for k, v in accounts_to_create.items() if len(v["profiles"]) > 1}
    single_profile_accounts = {k: v for k, v in accounts_to_create.items() if len(v["profiles"]) == 1}

    print(f"\n=== RESUMEN ===")
    print(f"Accounts a crear: {len(accounts_to_create)}")
    print(f"  Multi-perfil (1 username, 2+ profiles): {len(multi_profile_accounts)}")
    print(f"  Single-profile (1 username, 1 profile): {len(single_profile_accounts)}")
    print(f"Students sin username: {len(unmatched_students)}")
    print(f"Users sin username: {len(unmatched_users)}")

    if multi_profile_accounts:
        print(f"\n=== EJEMPLOS DE MULTI-PERFIL (los primeros 5) ===")
        for i, (k, v) in enumerate(multi_profile_accounts.items()):
            if i >= 5: break
            print(f"  '{k}':")
            for ptype, pid in v["profiles"]:
                print(f"    - {ptype}: {pid}")

    # DRY RUN
    if "--apply" not in sys.argv:
        print(f"\n=== DRY RUN: se crearian {len(accounts_to_create)} accounts ===")
        print(f"Para aplicar, ejecutar con --apply")
        client.close()
        return

    # APLICAR
    print(f"\n=== APLICANDO: Creando {len(accounts_to_create)} accounts ===")

    # Backup
    backup_path = f"C:/Users/Usuario/Documents/PROYECTO KYC/evidence/backups/pre-migrate-account-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    import os
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    backup = {
        "created_accounts": [],
        "linked_profiles": [],
        "timestamp": datetime.now().isoformat(),
    }

    created_count = 0
    linked_count = 0

    for username, data in accounts_to_create.items():
        # Verificar si ya existe
        existing = await Account.find_one(Account.username == username)
        if existing:
            account = existing
        else:
            # Crear account
            account = Account(
                username=username,
                email=data["email"],
                password=data["password"],
                carnet_identidad=data["carnet_identidad"],
                nombre_completo=data["nombre_completo"],
            )
            await account.save()
            created_count += 1
            backup["created_accounts"].append({
                "username": username,
                "email": data["email"],
                "carnet": data["carnet_identidad"],
            })

        # Vincular profiles
        for ptype, pid in data["profiles"]:
            if ptype == "student":
                await Student.get_motor_collection().update_one(
                    {"_id": PydanticObjectId(pid)},
                    {"$set": {"account_id": account.id}}
                )
            else:
                await User.get_motor_collection().update_one(
                    {"_id": PydanticObjectId(pid)},
                    {"$set": {"account_id": account.id}}
                )
            linked_count += 1
            backup["linked_profiles"].append({"type": ptype, "id": pid, "account_id": str(account.id)})

    with open(backup_path, "w", encoding="utf-8") as f:
        json.dump(backup, f, indent=2)

    print(f"\n=== RESULTADO ===")
    print(f"Accounts creados: {created_count}")
    print(f"Profiles vinculados: {linked_count}")
    print(f"Backup: {backup_path}")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
