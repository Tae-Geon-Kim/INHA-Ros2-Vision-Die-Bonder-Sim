import asyncio
import asyncpg

from web_backend.core.security import hash_password


USER_ID = "admin_team05"
RAW_PASSWORD = "Inha_vision05!@"

async def create_initial_user():

    # 비밀번호 해싱
    hashed_password = hash_password(RAW_PASSWORD)
    print(f"[*] 생성된 해시값: {hashed_password}")

    # DB 연결
    conn = await asyncpg.connect(
        user="team05_db",
        password="inha05",
        database="team05_db",
        host="127.0.0.1",
        port=54320
    )

    try:
        await conn.execute(
            """
            INSERT INTO users (id, password) 
            VALUES ($1, $2)
            """,
            USER_ID, hashed_password
        )
        print(f"[+] 성공적으로 '{USER_ID}' 계정이 DB에 추가되었습니다!")
    except asyncpg.exceptions.UniqueViolationError:
        print(f"[-] 이미 존재하는 아이디입니다.")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(create_initial_user())