import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient("mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC")
    db = client["KyC"]
    
    classrooms = await db["classrooms"].find().to_list(length=None)
    print(f"Total classrooms in 'KyC.classrooms': {len(classrooms)}")
    for c in classrooms:
        print(f"  Classroom: {c.get('nombre')}, Teacher: {c.get('teacher_user_id')}")
        
    courses = await db["courses"].find().to_list(length=None)
    print(f"Total courses in 'KyC.courses': {len(courses)}")

asyncio.run(main())
