import asyncio
import sys
import os

sys.path.append(os.path.dirname(__file__))

from core.database import init_db
from models.student import Student
from models.user import User

async def cleanup():
    print("Conectando a BD...")
    await init_db()
    
    # 1. Eliminar Estudiante Prueba UI
    student_ui = await Student.find_one(Student.email == "estudiante_test_ui@datahuba.com")
    if student_ui:
        await student_ui.delete()
        print("Eliminado: estudiante_test_ui@datahuba.com")
        
    # 2. Eliminar Estudiante de test_docs.py
    # Como usamos unique_id, buscaremos por nombre
    students_test_docs = await Student.find(Student.nombre == "Test Docs").to_list()
    for s in students_test_docs:
        await s.delete()
        print(f"Eliminado test_docs_student: {s.email}")
        
    # 3. Eliminar Usuarios CPD de test_docs.py
    cpd_users = await User.find(User.nombre == "CPD Docs").to_list()
    for u in cpd_users:
        await u.delete()
        print(f"Eliminado CPD Docs: {u.email}")
        
    print("Limpieza completada con éxito.")

if __name__ == "__main__":
    asyncio.run(cleanup())
