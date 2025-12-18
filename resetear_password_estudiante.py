"""
Script para Resetear Contraseña de Estudiante
=============================================
"""

import asyncio
import motor.motor_asyncio
from beanie import init_beanie
from core.config import settings
from core.security import get_password_hash
from models.student import Student
from models.user import User
from models.course import Course
from models.enrollment import Enrollment
from models.payment import Payment
from models.payment_config import PaymentConfig
from models.discount import Discount


async def resetear_password():
    """
    Resetear contraseña de un estudiante
    """
    print("=" * 70)
    print("🔐 RESETEAR CONTRASEÑA DE ESTUDIANTE")
    print("=" * 70)
    
    # Conectar
    client = motor.motor_asyncio.AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(
        database=client[settings.DATABASE_NAME],
        document_models=[User, Student, Course, Enrollment, Payment, PaymentConfig, Discount]
    )
    
    print(f"\n✅ Conectado a: {settings.DATABASE_NAME}")
    
    # Pedir registro
    registro = input("\nIngresa el REGISTRO del estudiante: ").strip()
    
    # Buscar estudiante
    student = await Student.find_one(Student.registro == registro)
    
    if not student:
        print(f"\n❌ No se encontró estudiante con registro: {registro}")
        client.close()
        return
    
    print(f"\n✅ Estudiante encontrado:")
    print(f"   Nombre: {student.nombre}")
    print(f"   Email: {student.email}")
    print(f"   Registro: {student.registro}")
    
    # Pedir nueva contraseña
    nueva_password = input("\nIngresa la NUEVA contraseña: ").strip()
    
    if len(nueva_password) < 5:
        print("\n❌ La contraseña debe tener al menos 5 caracteres")
        client.close()
        return
    
    confirmar = input(f"\n¿Cambiar contraseña de '{student.nombre}' a '{nueva_password}'? (escribe 'SI'): ")
    
    if confirmar == "SI":
        # Hashear la nueva contraseña
        hashed = get_password_hash(nueva_password)
        
        print(f"\n🔒 Contraseña hasheada: {hashed[:30]}...")
        
        # Actualizar
        student.password = hashed
        await student.save()
        
        print(f"\n✅ Contraseña actualizada correctamente!")
        print(f"\nPuedes iniciar sesión con:")
        print(f"  Endpoint: POST /api/v1/auth/login/student")
        print(f"  username: {student.registro}")
        print(f"  password: {nueva_password}")
    else:
        print("\n❌ Operación cancelada")
    
    client.close()


if __name__ == "__main__":
    asyncio.run(resetear_password())
