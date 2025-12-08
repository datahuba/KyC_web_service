"""
Script para resetear la contraseña de un usuario

Ejecutar con: python reset_password.py
"""

import asyncio
from core.database import init_db
from models.user import User
from core.security import get_password_hash


async def reset_password():
    """Resetear contraseña del usuario admin"""
    # Inicializar base de datos
    await init_db()
    
    # Buscar usuario
    user = await User.find_one(User.username == "admin")
    if not user:
        print("❌ Usuario 'admin' no encontrado")
        return
    
    # Nueva contraseña
    new_password = "admin123"
    user.password = get_password_hash(new_password)
    await user.save()
    
    print("✅ Contraseña reseteada exitosamente!")
    print(f"   Username: {user.username}")
    print(f"   Nueva Password: {new_password}")
    print(f"   Email: {user.email}")
    print(f"   Rol: {user.rol}")


if __name__ == "__main__":
    asyncio.run(reset_password())
