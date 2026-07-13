import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from models.user import User
from models.course import Course
from core.config import settings

async def main():
    client = AsyncIOMotorClient("mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC")
    await init_beanie(database=client["KyC"], document_models=[User, Course])
    
    encargado = await User.find_one({"nombre": "Encargado Diplomado IA Aplicada a la Educacion"})
    
    if not encargado.cursos_asignados:
        print("No assigned courses.")
        return
        
    courses = await Course.find({"_id": {"$in": encargado.cursos_asignados}}).to_list()
    print(f"Courses found: {len(courses)}")
    
    allowed_teacher_ids = set()
    for c in courses:
        for m in c.modulos:
            if m.docente_id:
                allowed_teacher_ids.add(m.docente_id)
                
    print(f"Allowed Teacher IDs: {allowed_teacher_ids}")
    
    for t_id in allowed_teacher_ids:
        t = await User.get(t_id)
        print(f"Teacher: {t.username}")

asyncio.run(main())
