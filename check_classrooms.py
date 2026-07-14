import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from beanie import init_beanie
from models.classroom import Classroom
from models.course import Course
from core.config import settings

async def main():
    client = AsyncIOMotorClient(settings.MONGODB_URL)
    await init_beanie(database=client["KyC"], document_models=[Classroom, Course])
    
    classrooms = await Classroom.find_all().to_list()
    print(f"Total Classrooms in DB: {len(classrooms)}")
    for c in classrooms:
        course = await Course.get(c.course_id)
        c_name = course.nombre if course else "NO COURSE"
        print(f"  Classroom: {c.nombre}, Course ID: {c.course_id} ({c_name}), Teacher ID: {c.teacher_user_id}")

asyncio.run(main())
