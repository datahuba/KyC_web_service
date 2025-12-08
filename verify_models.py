import asyncio
from datetime import datetime
from models.student import Student
from models.enrollment import Enrollment
from models.enums import TipoEstudiante, EstadoInscripcion, TipoPago
from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient

async def verify_models():
    print("Verifying Student model...")
    student_data = {
        "registro": "TEST-001",
        "password": "hashed_password",
        "nombre": "Test Student",
        "extension": "1234567 LP",
        "fecha_nacimiento": datetime.now(),
        "celular": "70000000",
        "email": "test@example.com",
        "carrera": "Systems",
        "es_estudiante_interno": TipoEstudiante.INTERNO,
        # New fields
        "lugar_nacimiento": "La Paz",
        "universidad": "UMSA",
        "universidad_otra": None,
        "numero_titulo_profesional": "12345-A",
        "fecha_emision_titulo": 2023,
        "tipo_titulo_profesion": "Ingeniero",
        "hoja_vida_url": "http://example.com/cv.pdf",
        "titulo_url": "http://example.com/title.pdf",
        "carnet_url": "http://example.com/id.pdf",
        "certificado_afiliacion_url": "http://example.com/cert.pdf"
    }
    student = Student(**student_data)
    print(f"Student created successfully: {student.nombre}, Universidad: {student.universidad}")

    print("\nVerifying Enrollment model...")
    enrollment_data = {
        "estudiante_id": "507f1f77bcf86cd799439011",
        "curso_id": "507f1f77bcf86cd799439012",
        "es_estudiante_interno": TipoEstudiante.INTERNO,
        "total_a_pagar": 1000,
        "saldo_pendiente": 1000,
        "tipo_pago": TipoPago.CONTADO,
        # New fields
        "comprobante_matricula_url": "http://example.com/matricula.jpg",
        "comprobante_modulo_url": "http://example.com/modulo.jpg",
        "requisitos_url": ["http://example.com/req1.jpg", "http://example.com/req2.jpg"]
    }
    enrollment = Enrollment(**enrollment_data)
    print(f"Enrollment created successfully. Matricula URL: {enrollment.comprobante_matricula_url}")
    print(f"Requisitos: {len(enrollment.requisitos_url)}")

if __name__ == "__main__":
    asyncio.run(verify_models())
