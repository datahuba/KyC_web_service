import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from models.user import User
from models.classroom import Classroom
from core.config import settings

async def main():
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(database=client[settings.DATABASE_NAME], document_models=[User, Classroom])
    
    encargados = await User.find(User.rol == "encargado_curso").to_list()
    for e in encargados:
         print(f"Encargado: {e.username}, username: {e.username}, Cursos asignados: {e.cursos_asignados}")
         if e.cursos_asignados:
             classrooms = await Classroom.find({"course_id": {"$in": e.cursos_asignados}}).to_list()
             print(f"  Classrooms found: {len(classrooms)}")
             for c in classrooms:
                 print(f"    Classroom: {c.nombre}, Teacher ID: {c.teacher_user_id}")
                 teacher = await User.get(c.teacher_user_id)
                 if teacher:
                     print(f"      Teacher Name: {teacher.username}, Username: {teacher.username}")
                 else:
                     print(f"      Teacher NOT FOUND!")

asyncio.run(main())
