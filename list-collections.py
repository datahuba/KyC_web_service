"""Listar las colecciones en la BD.

F-SEC-CREDENCIALES (2026-08-16): antes este script traia la cadena de
conexion de Atlas (usuario + contrasena) HARDCODEADA y estaba commiteada
en el repo. Ahora se lee de la variable de entorno MONGODB_URL, igual que
`core/config.py`. Correr con el .env del proyecto cargado, o exportando
la variable a mano.
"""
import asyncio
import os
import sys

from motor.motor_asyncio import AsyncIOMotorClient

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

MONGODB_URL = os.getenv("MONGODB_URL")

if not MONGODB_URL:
    sys.exit(
        "ERROR: falta la variable de entorno MONGODB_URL.\n"
        "Defini el .env del proyecto o exportala antes de correr este script."
    )


async def main():
    client = AsyncIOMotorClient(MONGODB_URL)
    try:
        for db_name in await client.list_database_names():
            print(f"DB: {db_name}")
            db = client[db_name]
            for cname in await db.list_collection_names():
                count = await db[cname].count_documents({})
                print(f"  {cname}: {count} docs")
    finally:
        client.close()


asyncio.run(main())
