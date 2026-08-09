"""Cleanup del test multi-perfil (borra Account de prueba)."""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\Usuario\Documents\PROYECTO KYC\KyC_web_service")


async def main():
    from core.config import settings
    from beanie import init_beanie
    from models.account import Account
    from models.user import User
    from models.student import Student
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(client["KyC"], document_models=[Account, User, Student])

    # Limpiar
    acc = await Account.find_one(Account.username == "test.multi")
    if acc:
        await acc.delete()
        print(f"Account test.multi borrado: {acc.id}")
    else:
        print("Account test.multi no existe")

    # Limpiar students/users con account_id vinculado (no a la cuenta borrada, sino todos con username test.multi)
    s = await Student.find_one(Student.registro == "TEST-MULTI")
    if s:
        await s.delete()
        print(f"Student TEST-MULTI borrado: {s.id}")

    u = await User.find_one(User.username == "test.multi")
    if u:
        await u.delete()
        print(f"User test.multi borrado: {u.id}")

    print("Cleanup completo")
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
