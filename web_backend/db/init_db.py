import asyncio
import asyncpg
from web_backend.core.config import db_settings
from web_backend.db.tables import CREATE_TABLES_SQL

async def initialize_database():
    
    print(f"Connecting to GPU Server Database ({db_settings.DB_HOST}:{db_settings.DB_PORT})")
    
    conn = await asyncpg.connect(
        user=db_settings.DB_USER,
        password=db_settings.DB_PASSWORD,
        database=db_settings.DB_NAME,
        host=db_settings.DB_HOST,
        port=db_settings.DB_PORT
    )
    
    try:
        print("Raw SQL을 사용하여 테이블 생성을 시작합니다...")
        await conn.execute(CREATE_TABLES_SQL)
        print("성공: 모든 테이블이 정상적으로 생성되었습니다.")
        
    except Exception as e:
        print(f"에러 발생: 테이블 생성 중 문제가 생겼습니다.\n{e}")
        
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(initialize_database())
