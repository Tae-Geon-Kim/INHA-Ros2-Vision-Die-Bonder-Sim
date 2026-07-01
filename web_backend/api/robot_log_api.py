from fastapi import APIRouter, Depends, status
from fastapi_limiter.depends import RateLimiter

from web_backend.schemas.robot_log_schemas import CommonResponse

router = APIRouter()

@router.post(
    "/robot_log",
    dependencies = [Depends(RateLimiter(times = 60, seconds = 60))],
    response_model = CommonResponse,
    status_code = status.HTTP_200_OK,
    summary = "로봇 로그 등록"
    description = """
    """
)