"""
Script para crear un usuario SUPERADMIN de prueba

Ejecutar con: python create_admin.py
"""

import asyncio
from core.database import init_db
from models.user import User
from models.enums import UserRole
from core.security import get_password_hash


async def create_admin():
    """Crear usuario SUPERADMIN"""
    # Inicializar base de datos
    await init_db()
    
    # Verificar si ya existe
    existing = await User.find_one(User.username == "admin")
    if existing:
        print(f"✅ Usuario 'admin' ya existe")
        print(f"   Email: {existing.email}")
        print(f"   Rol: {existing.rol}")
        print(f"   Activo: {existing.activo}")
        return
    
    # Crear nuevo usuario
    admin = User(
        username="admin",
        email="admin@example.com",
        password=get_password_hash("admin123"),  # Contraseña: admin123
        rol=UserRole.SUPERADMIN,
        activo=True
    )
    
    await admin.insert()
    print("✅ Usuario SUPERADMIN creado exitosamente!")
    print(f"   Username: admin")
    print(f"   Password: admin123")
    print(f"   Email: admin@example.com")
    print(f"   Rol: SUPERADMIN")


if __name__ == "__main__":
    asyncio.run(create_admin())
