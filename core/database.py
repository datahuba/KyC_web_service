"""
Conexión a Base de Datos
========================

Manejo de la conexión asíncrona a MongoDB usando Motor y Beanie ODM.
"""

import motor.motor_asyncio
from beanie import init_beanie
from .config import settings

# Importar todos los modelos para registrarlos en Beanie
from models.user import User
from models.student import Student
from models.course import Course
from models.enrollment import Enrollment
from models.payment import Payment
from models.payment_config import PaymentConfig
from models.discount import Discount
from models.classroom import Classroom, ClassroomStudent
from models.classroom_material import ClassroomMaterial
from models.assignment import Assignment
from models.submission import Submission

async def init_db():
    """
    Inicializa la conexión a la base de datos y Beanie ODM.

    Esta función debe ser llamada al inicio de la aplicación (startup event).
    """
    # Crear cliente de Motor
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URL
    )

    # Inicializar Beanie con la base de datos y los modelos
    await init_beanie(
        database=client[settings.DATABASE_NAME],
        document_models=[
            User,
            Student,
            Course,
            Enrollment,
            Payment,
            PaymentConfig,
            Discount,
            Classroom,
            ClassroomStudent,
            ClassroomMaterial,
            Assignment,
            Submission,
        ]
    )
    print(f"[OK] Conectado a MongoDB ({settings.DATABASE_NAME}) y Beanie inicializado.")
