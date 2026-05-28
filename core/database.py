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


async def _sanitize_legacy_database(db):
    """
    Sanea de forma asíncrona la base de datos de registros duplicados y conflictos
    de índices legacy antes de la construcción e inicialización de índices de Beanie.
    """
    student_col = db["students"]
    course_col = db["courses"]

    # 1. Limpieza de duplicados en Registro Académico (students)
    dup_registros = await student_col.aggregate([
        {
            "$group": {
                "_id": "$registro",
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1}
            }
        },
        {
            "$match": {
                "count": {"$gt": 1}
            }
        }
    ]).to_list(length=None)

    for item in dup_registros:
        if item["_id"]:
            ids_to_delete = item["ids"][1:]  # Conservamos el primer registro, eliminamos el resto
            await student_col.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"[STARTUP-CLEANUP] Se purgaron {len(ids_to_delete)} estudiantes duplicados con Registro: '{item['_id']}'")

    # 2. Limpieza de duplicados en Carnet de Identidad (students)
    dup_carnets = await student_col.aggregate([
        {
            "$match": {
                "carnet": {"$ne": None, "$not": {"$regex": "^\\s*$"}}
            }
        },
        {
            "$group": {
                "_id": "$carnet",
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1}
            }
        },
        {
            "$match": {
                "count": {"$gt": 1}
            }
        }
    ]).to_list(length=None)

    for item in dup_carnets:
        if item["_id"]:
            ids_to_delete = item["ids"][1:]
            await student_col.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"[STARTUP-CLEANUP] Se purgaron {len(ids_to_delete)} estudiantes duplicados con Carnet C.I.: '{item['_id']}'")

    # 3. Limpieza de duplicados en Correos Electrónicos (students)
    dup_emails = await student_col.aggregate([
        {
            "$match": {
                "email": {"$ne": None, "$not": {"$regex": "^\\s*$"}}
            }
        },
        {
            "$group": {
                "_id": "$email",
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1}
            }
        },
        {
            "$match": {
                "count": {"$gt": 1}
            }
        }
    ]).to_list(length=None)

    for item in dup_emails:
        if item["_id"]:
            ids_to_delete = item["ids"][1:]
            await student_col.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"[STARTUP-CLEANUP] Se purgaron {len(ids_to_delete)} estudiantes duplicados con Email: '{item['_id']}'")

    # 4. Limpieza de duplicados en Código de Curso (courses)
    dup_courses = await course_col.aggregate([
        {
            "$group": {
                "_id": "$codigo",
                "ids": {"$push": "$_id"},
                "count": {"$sum": 1}
            }
        },
        {
            "$match": {
                "count": {"$gt": 1}
            }
        }
    ]).to_list(length=None)

    for item in dup_courses:
        if item["_id"]:
            ids_to_delete = item["ids"][1:]
            await course_col.delete_many({"_id": {"$in": ids_to_delete}})
            print(f"[STARTUP-CLEANUP] Se purgaron {len(ids_to_delete)} programas duplicados con Código: '{item['_id']}'")

    # 5. RESOLUCIÓN DE CONFLICTOS DE NOMBRES DE ÍNDICES LEGACY (IndexOptionsConflict / Error 85)
    # Dropeamos índices antiguos de colecciones modificadas para que Beanie los re-cree limpiamente con nombres estándar
    collections_to_reset_indexes = ["classrooms", "classroom_students", "enrollments", "users", "payments"]
    for col_name in collections_to_reset_indexes:
        try:
            # Eliminamos los índices existentes para evitar colisiones por nombres customizados (ej: 'idx_classrooms_teacher')
            await db[col_name].drop_indexes()
            print(f"[STARTUP-CLEANUP] Índices antiguos de '{col_name}' eliminados para prevenir conflictos de nombres.")
        except Exception:
            # Falla silenciosamente si la colección aún no tiene índices o no existe en esta BD
            pass


async def init_db():
    """
    Inicializa la conexión a la base de datos y Beanie ODM.

    Esta función debe ser llamada al inicio de la aplicación (startup event).
    """
    # Crear cliente de Motor
    client = motor.motor_asyncio.AsyncIOMotorClient(
        settings.MONGODB_URL
    )

    db = client[settings.DATABASE_NAME]

    # Ejecutar saneamiento de duplicados e índices históricos antes de inicializar Beanie
    await _sanitize_legacy_database(db)

    # Inicializar Beanie con la base de datos y los modelos
    await init_beanie(
        database=db,
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
    