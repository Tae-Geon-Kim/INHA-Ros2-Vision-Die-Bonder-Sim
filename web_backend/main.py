from contextlib import asynccontextmanager

from fastapi import FastAPI

from web_backend.api.robot_log_api import router as robot_log_router
from web_backend.api.user_api import router as user_router
from web_backend.db.postgres_connection import create_db_pool
from web_backend.db.redis_connection import redis_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await create_db_pool()

    try:
        yield
    finally:
        await app.state.db_pool.close()
        redis_close = getattr(redis_db, "aclose", redis_db.close)
        await redis_close()


app = FastAPI(
    title="ROS2 Vision Web Backend",
    description="사용자 인증과 로봇 작업 로그를 관리하는 웹 백엔드 API입니다.",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(user_router, prefix="/users", tags=["Users"])
app.include_router(robot_log_router, prefix="/robot-logs", tags=["Robot Logs"])


@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "ok"}
