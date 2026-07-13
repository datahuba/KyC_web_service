import asyncio
import sys
import os
sys.path.append(os.path.dirname(__file__))
from core.database import init_db
from models.user import User
from core.security import create_access_token
from datetime import timedelta
from core.config import settings

async def run():
    await init_db()
    users = await User.find_all().to_list()
    for user in users:
        print(f'User: {user.username}, Role: {user.rol.value}')
        if user.rol.value == 'superadmin':
            access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
            access_token = create_access_token(
                data={'sub': user.username, 'rol': user.rol.value}, expires_delta=access_token_expires
            )
            print(f'TOKEN={access_token}')
            return
    print('No superadmin found')

asyncio.run(run())
