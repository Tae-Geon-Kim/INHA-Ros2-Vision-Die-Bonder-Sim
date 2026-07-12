import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware

from web_backend.api.robot_log_api import router as robot_log_router
from web_backend.api.robot_control_api import (
    router as robot_control_router,
    shutdown_managed_demo,
)
from web_backend.api.user_api import router as user_router
from web_backend.core.config import frontend_settings
from web_backend.db.postgres_connection import create_db_pool
from web_backend.services.robot_log_services import archive_expired_robot_data


LOGGER = logging.getLogger(__name__)
ARCHIVE_INTERVAL_SECONDS = 6 * 60 * 60
MAX_ARCHIVE_BATCHES_PER_CYCLE = 10


async def archive_expired_data_periodically(db_pool):
    while True:
        for _ in range(MAX_ARCHIVE_BATCHES_PER_CYCLE):
            try:
                result = await archive_expired_robot_data(db_pool)
                if result["status"] != "archived":
                    break
                LOGGER.info(
                    "Archived expired robot data to %s: work=%d, errors=%d, "
                    "vision=%d",
                    result["archive_path"],
                    result["work_history"],
                    result["robot_error_logs"],
                    result["vision_align_logs"],
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                LOGGER.exception("Failed to archive expired robot data")
                break

        await asyncio.sleep(ARCHIVE_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.db_pool = await create_db_pool()
    archive_task = asyncio.create_task(
        archive_expired_data_periodically(app.state.db_pool),
        name="expired-robot-data-archive",
    )

    try:
        yield
    finally:
        archive_task.cancel()
        try:
            await archive_task
        except asyncio.CancelledError:
            pass
        await shutdown_managed_demo(app.state.db_pool)
        await app.state.db_pool.close()


app = FastAPI(
    title="ROS2 Vision Web Backend",
    description="사용자 인증과 로봇 작업 로그를 관리하는 웹 백엔드 API입니다.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=frontend_settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router, prefix="/users", tags=["Users"])
app.include_router(robot_log_router, prefix="/robot-logs", tags=["Robot Logs"])
app.include_router(robot_control_router, prefix="/robot-control", tags=["Robot Control"])


@app.get("/health", tags=["Health"])
async def health_check(request: Request):
    async def check_database():
        async with request.app.state.db_pool.acquire() as conn:
            return await conn.fetchval("SELECT 1")

    try:
        await asyncio.wait_for(check_database(), timeout=1.0)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database connection is unavailable.",
        ) from exc
    return {"status": "ok"}
