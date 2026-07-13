import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def test_db():
    client = AsyncIOMotorClient("mongodb://localhost:27017")
    db = client.kyc_db
    sa = await db.users.find_one({"rol": "superadmin"})
    if sa:
        print("Superadmin found:", sa.get("username"), sa.get("rol"))
    else:
        print("No superadmin found")

asyncio.run(test_db())
