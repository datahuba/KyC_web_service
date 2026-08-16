"""Listar las colecciones en la BD."""
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

MONGODB_URL = "mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC"

async def main():
    client = AsyncIOMotorClient(MONGODB_URL)
    for db_name in await client.list_database_names():
        print(f"DB: {db_name}")
        db = client[db_name]
        for cname in await db.list_collection_names():
            count = await db[cname].count_documents({})
            print(f"  {cname}: {count} docs")
    client.close()

asyncio.run(main())
