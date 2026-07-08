from fastapi import (
    APIRouter, Depends, HTTPException, Cookie,
    status, Response
)
from asyncpg import Connection

from web_backend.core.security import get_current_user
from web_backend.core.rate_limit import create_rate_limiter
from web_backend.db.postgres_connection import get_db
from web_backend.db.redis_connection import get_redis

from web_backend.schemas.common_schemas import CommonResponse
from web_backend.schemas.user_schemas import UserLogin

from web_backend.services.user_services import (
    refresh_access_token_services,
    token_login_services,
    token_logout_services
)

router = APIRouter()

# JWT 토큰 재발급
@router.post(
    "/refresh",
    dependencies = [Depends(create_rate_limiter(times = 3, seconds = 60))],
    response_model = CommonResponse,
    status_code = status.HTTP_201_CREATED,
    summary = "[인증] 만료된 JWT Access 토큰 재발급",
    description = """
    만료된 Access Token을 갱신하기 위해서 새로운 토큰을 발급받는다.

    - 브라우저 쿠키에 저장된 refresh_token을 자동으로 읽어와 검증.
    """
)
async def refresh_access_token(
    response: Response,
    refresh_token: str | None = Cookie(default = None),
    redis_client = Depends(get_redis),
    conn: Connection = Depends(get_db)
):

    if not refresh_token:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "Refresh Token이 존재하지 않습니다."
        )
    
    new_access = await refresh_access_token_services(conn, refresh_token, redis_client)

    response.set_cookie(key = "access_token", value = new_access, httponly = True, samesite = "lax")

    return CommonResponse(message = "토큰이 성공적으로 재발급 되었습니다.")

# JWT 사용자 로그인
@router.post(
    "/login",
    dependencies = [Depends(create_rate_limiter(times = 3, seconds = 60))],
    response_model = CommonResponse, 
    status_code = status.HTTP_201_CREATED,
    summary  = "[인증] 사용자 로그인", 
    description = """
    사용자의 아이디와 비밀번호를 검증하고 JWT Access, Refresh 토큰을 발급합니다.

     - 허용되는 id 형식: 영문자, 숫자가 무조건 포함한 5 ~ 30자 (선택적으로 특수문자 사용 가능: $!%*#?&._-)
     - 허용되는 password 형식: 영문자, 숫자, 특수문자가 무조건 포함한 8 ~ 30자 (허용되는 특수문자: @$!%*#?&._-)
    """
)
async def token_login(
    data: UserLogin,
    response: Response,
    redis_client = Depends(get_redis),
    conn: Connection = Depends(get_db)
):
    access_token, refresh_token = await token_login_services(data, conn, redis_client)

    response.set_cookie(key = "access_token", value = access_token, httponly = True, samesite = "lax")
    response.set_cookie(key = "refresh_token", value = refresh_token, httponly = True, samesite = "lax")

    return CommonResponse(message = "로그인에 성공하였습니다.")

# JWT 사용자 로그아웃
@router.post(
    "/logout",
    dependencies = [Depends(create_rate_limiter(times = 3, seconds = 60))],
    response_model = CommonResponse,
    status_code = status.HTTP_200_OK,
    summary = "[인증] 사용자 로그아웃",
    description = """
    사용자의 로그아웃을 처리하고 브라우저에 저장된 JWT 쿠키를 삭제합니다.

    """
)
async def token_logout(
    response: Response,
    redis_client = Depends(get_redis),
    current_user: dict = Depends(get_current_user),
    conn: Connection = Depends(get_db)
):
    await token_logout_services(conn, redis_client, current_user['index'])
    
    response.delete_cookie(key = "access_token", httponly = True, samesite = "lax")
    response.delete_cookie(key = "refresh_token", httponly = True, samesite = "lax")

    return CommonResponse(message = "성공적으로 로그아웃 되었습니다.")
