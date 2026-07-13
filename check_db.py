import asyncio
from motor.motor_asyncio import AsyncIOMotorClient

async def main():
    client = AsyncIOMotorClient("mongodb+srv://joelgonzalesdmc:yBSZrAirOJXt0J6T@kyc.eflzqkm.mongodb.net/?appName=KyC")
    db = client["KyC"]
    collections = await db.list_collection_names()
    print("Collections in 'KyC':", collections)
    
    db2 = client["kyc_db"]
    collections2 = await db2.list_collection_names()
    print("Collections in 'kyc_db':", collections2)

asyncio.run(main())
