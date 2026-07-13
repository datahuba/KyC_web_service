import asyncio
import sys
import os

sys.path.append(os.path.dirname(__file__))

from core.database import init_db
from models.student import Student
from models.user import User
from api.api import api_router
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from beanie import PydanticObjectId
from core.security import create_access_token

app = FastAPI()
app.include_router(api_router, prefix="/api/v1")

async def run_tests():
    print("Iniciando conexión a base de datos...")
    await init_db()
    
    import uuid
    # 1. Crear un estudiante de prueba
    print("Creando estudiante de prueba...")
    unique_id = str(uuid.uuid4())[:8]
    student = Student(
        email=f"test_docs_student_{unique_id}@datahuba.com",
        nombre="Test Docs",
        apellido="Student",
        registro=f"reg{unique_id}",
        carnet=f"ci{unique_id}",
        celular="12345678",
        domicilio="Test",
        password="fake",
        cv_url="http://fake.com/cv.pdf",
        carnet_url="http://fake.com/carnet.pdf",
        afiliacion_url="http://fake.com/afiliacion.pdf"
    )
    await student.insert()
    
    print(f"Estudiante creado con ID: {student.id}")
    print(f"Estado inicial CV: {student.cv_estado}")
    print(f"Estado inicial Carnet: {student.carnet_estado}")
    print(f"Estado inicial Afiliación: {student.afiliacion_estado}")
    
    # Aseguramos que inician en 'pendiente'
    assert student.cv_estado == "pendiente"
    assert student.carnet_estado == "pendiente"
    assert student.afiliacion_estado == "pendiente"
    
    # 2. Generar token de encargado de curso o CPD para poder verificar
    # Crearemos un usuario mock CPD
    cpd_user = User(
        email=f"cpd_test_docs_{unique_id}@datahuba.com",
        username=f"cpd_test_{unique_id}",
        nombre="CPD Docs",
        apellido="Test",
        rol="cpd",
        activo=True,
        password="fake"
    )
    await cpd_user.insert()
    
    print(f"Usuario CPD creado con ID: {cpd_user.id}")
    
    # Token
    token = create_access_token({"sub": str(cpd_user.id), "user_type": "user"})
    headers = {"Authorization": f"Bearer {token}"}
    
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # 3. Probar verificar CV
            print("Probando verificación de CV...")
            res = await client.put(f"/api/v1/students/{student.id}/documentos/cv/verificar", headers=headers)
            assert res.status_code == 200, res.text
            
            # 4. Probar rechazar Carnet
            print("Probando rechazo de Carnet...")
            res = await client.put(f"/api/v1/students/{student.id}/documentos/carnet/rechazar", data={"motivo": "Documento borroso"}, headers=headers)
            assert res.status_code == 200, res.text
            
            # 5. Probar verificar Afiliación
            print("Probando verificación de Afiliación...")
            res = await client.put(f"/api/v1/students/{student.id}/documentos/afiliacion/verificar", headers=headers)
            assert res.status_code == 200, res.text
        
        # 6. Consultar desde BD para validar que los estados guardados son correctos
        student_db = await Student.get(student.id)
        print(f"Estado Final CV: {student_db.cv_estado} (Motivo: {student_db.cv_motivo_rechazo})")
        print(f"Estado Final Carnet: {student_db.carnet_estado} (Motivo: {student_db.carnet_motivo_rechazo})")
        print(f"Estado Final Afiliación: {student_db.afiliacion_estado} (Motivo: {student_db.afiliacion_motivo_rechazo})")
        
        assert student_db.cv_estado == "verificado"
        assert student_db.carnet_estado == "rechazado"
        assert student_db.carnet_motivo_rechazo == "Documento borroso"
        assert student_db.afiliacion_estado == "verificado"
        
        print("✅ TODOS LOS TESTS PASARON CON ÉXITO")
        
    finally:
        # Cleanup
        print("Limpiando datos de prueba...")
        await student.delete()
        await cpd_user.delete()
        print("Limpieza completada.")

if __name__ == "__main__":
    asyncio.run(run_tests())
