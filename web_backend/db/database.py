import asyncpg
import logging
from asyncpg import Connection, Pool
from fastapi import FastAPI, Depends, Request, status, HTTPException
from contextlib import asynccontextmanager
from web_backend.core.config import settings

# create_db_pool로 DB 접속 정보를 따로 안빼면 각 api마다 접속 정보를 하드코딩 해야한다.
# 파일이 다르면 connection pool 정보를 불러올 수 없으니까 이를 app.state에 두고 각 라우터에서 request 객체를 통해 불러온다

# connection pool은 서버가 완전히 켜진 상태에서만 정상 연결 가능
# lifespan 으로 묶으면 서버가 완전히 켜진 후에 읽기 때문에 에러 발생 x (import는 읽자미자 실행)

async def create_db_pool():
    return await asyncpg.create_pool(
        user = settings.DB_USER,
        password = settings.DB_PASSWORD,
        database = settings.DB_NAME,
        host = settings.DB_HOST,
        port = settings.DB_PORT,
        max_size = settings.DB_MAX_SIZE,
        min_size = settings.DB_MIN_SIZE
    )

# app 객체가 정의되지 않은 파일에서 FastAPI 인스턴스에 접근하기 위해 request 사용
# get_db를 안쓰면 각 API마다 매개변수로 request 객체를 받아와서 그 객체를 통해서 connection pool에 대한 정보를 받아와야 했다.
# get_db를 쓴 덕분에 객체를 생성안하고 connection pool에 대한 정보를 받아올 수 있었다.
# 각 API 함수가 connection pool이 필요하면 선언 & Depends 의존성 주입 (get_db를 가져오고 끝나면 반납 - connection pool 사이즈는 한정적)

async def get_db(request : Request):

    if request.app.state.db_pool is None:
        raise HTTPException(
            status_code = status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail = "db pool이 초기화되지 않았습니다."
        )

    async with request.app.state.db_pool.acquire() as connection:
        yield connection