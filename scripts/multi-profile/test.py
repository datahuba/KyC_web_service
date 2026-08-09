"""Test del flujo multi-perfil R36."""
import asyncio
import sys

sys.path.insert(0, r"C:\Users\Usuario\Documents\PROYECTO KYC\KyC_web_service")


async def main():
    from core.config import settings
    from core.security import get_password_hash, verify_password
    from beanie import init_beanie, PydanticObjectId
    from models.account import Account
    from models.user import User
    from models.student import Student
    from motor.motor_asyncio import AsyncIOMotorClient

    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(client["KyC"], document_models=[Account, User, Student])

    # Limpiar cuenta de prueba
    await Account.find_one(Account.username == "test.multi").delete()

    # Crear Account de prueba
    password = "TestPass123!"
    hashed = get_password_hash(password)
    account = Account(
        username="test.multi",
        email="test.multi@uagrm.edu",
        password=hashed,
        carnet_identidad="9999999",
        nombre_completo="Test Multi Profile",
    )
    await account.save()
    print(f"Account creado: {account.id}")

    # Crear Student de prueba
    student = await Student.find_one(Student.registro == "TEST-MULTI")
    if not student:
        student = Student(
            registro="TEST-MULTI",
            password=hashed,
            nombre="Test",
            apellidos="Multi",
            email="test.multi@uagrm.edu",
            account_id=account.id,
        )
    else:
        student.password = hashed
        student.account_id = account.id
    await student.save()
    print(f"Student creado/vinculado: {student.id}")

    # Crear User de prueba
    user = await User.find_one(User.username == "test.multi")
    if not user:
        user = User(
            username="test.multi",
            email="test.multi@uagrm.edu",
            password=hashed,
            rol="docente",
            account_id=account.id,
        )
    else:
        user.password = hashed
        user.account_id = account.id
    await user.save()
    print(f"User creado/vinculado: {user.id}")

    # Verificar que el endpoint /login/account encuentra 2 perfiles
    from api.dependencies import get_password_hash
    print("\n=== Verificacion manual ===")
    print(f"Account.username: {account.username}")
    print(f"Profiles:")
    students_with_acc = await Student.find(Student.account_id == account.id).to_list()
    print(f"  Students: {len(students_with_acc)}")
    users_with_acc = await User.find(User.account_id == account.id).to_list()
    print(f"  Users: {len(users_with_acc)}")
    print(f"TOTAL: {len(students_with_acc) + len(users_with_acc)} (esperado: 2 = multi-perfil)")

    # Verificar password
    print(f"\nPassword verification: {verify_password(password, hashed)}")

    # Cleanup
    print("\n=== Limpiando cuenta de prueba ===")
    await Student.find_one(Student.registro == "TEST-MULTI").delete()
    await User.find_one(User.username == "test.multi").delete()
    await Account.find_one(Account.username == "test.multi").delete()
    print("Limpieza completa")

    client.close()


if __name__ == "__main__":
    asyncio.run(main())
