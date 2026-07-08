import asyncio

import asyncpg

from web_backend.core.config import db_settings, initial_user_settings
from web_backend.core.security import hash_password


async def create_initial_user():
    user_id = initial_user_settings.INITIAL_USER_ID
    raw_password = initial_user_settings.INITIAL_USER_PASSWORD

    if not user_id or not raw_password:
        raise RuntimeError(
            "INITIAL_USER_ID와 INITIAL_USER_PASSWORD를 .env에 설정해주세요."
        )

    hashed_password = hash_password(raw_password)

    conn = await asyncpg.connect(
        user=db_settings.DB_USER,
        password=db_settings.DB_PASSWORD,
        database=db_settings.DB_NAME,
        host=db_settings.DB_HOST,
        port=db_settings.DB_PORT
    )

    try:
        await conn.execute(
            """
            INSERT INTO "user" (id, password)
            VALUES ($1, $2)
            ON CONFLICT (id)
            DO UPDATE SET password = EXCLUDED.password
            """,
            user_id, hashed_password
        )
        print(f"[+] '{user_id}' 계정이 .env 기준으로 동기화되었습니다.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_initial_user())
