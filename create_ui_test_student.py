import asyncio
import sys
import os

sys.path.append(os.path.dirname(__file__))

from core.database import init_db
from models.student import Student
from core.security import get_password_hash

async def run():
    print("Conectando a BD...")
    await init_db()
    
    email = "estudiante_test_ui@datahuba.com"
    
    # Borramos si ya existe para evitar errores
    existing = await Student.find_one(Student.email == email)
    if existing:
        await existing.delete()
        
    print("Creando estudiante permanente para pruebas de UI...")
    student = Student(
        email=email,
        nombre="Estudiante",
        apellido="Prueba UI",
        registro="REG-TEST-UI",
        carnet="12345678-TEST",
        celular="77777777",
        domicilio="Av. Test UI",
        password=get_password_hash("password123"),
        
        # Simulamos que ya subió documentos
        cv_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        cv_estado="verificado",
        
        carnet_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        carnet_estado="rechazado",
        carnet_motivo_rechazo="La foto del carnet está muy oscura y no se leen los datos.",
        
        afiliacion_url="https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf",
        afiliacion_estado="pendiente"
    )
    await student.insert()
    
    print("\n✅ Estudiante de prueba creado con éxito en la base de datos.")
    print("-" * 50)
    print("DATOS PARA INICIAR SESIÓN COMO ESTUDIANTE:")
    print(f"Email: {email}")
    print(f"Contraseña: password123")
    print("-" * 50)
    print("PARA VERLO COMO ADMINISTRADOR/CPD:")
    print("Ve a la lista de estudiantes y busca 'Estudiante Prueba UI'.")

if __name__ == "__main__":
    asyncio.run(run())
