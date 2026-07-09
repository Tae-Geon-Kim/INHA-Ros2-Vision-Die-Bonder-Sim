from fastapi import HTTPException, status
from jose import jwt, JWTError, ExpiredSignatureError
from asyncpg import Connection
from datetime import datetime, timezone, timedelta

from web_backend.schemas.user_schemas import UserLogin

from web_backend.core.security import(
    verify_password,
    create_access_token,
    create_refresh_token,
    credentials_exception
)

from web_backend.models.user_models  import get_current_user_info, get_info_by_id
from web_backend.core.config import jwt_settings
from web_backend.models.user_logs_models import insert_user_log

secret_key = jwt_settings.SECRET_KEY
algorithm = jwt_settings.ALGORITHM
KST = timezone(timedelta(hours=9))


def _now_kst():
    return datetime.now(KST).replace(tzinfo = None)


# JWT 토큰 재발급
async def refresh_access_token_services(conn: Connection, refresh_token: str):

    try:
        payload = jwt.decode(refresh_token, secret_key, algorithms = [algorithm])
        user_id: str = payload.get("sub")

        if user_id is None:
            raise credentials_exception

        user_info = await get_current_user_info(conn, int(user_id))
        if not user_info:
            raise HTTPException(
                status_code = status.HTTP_401_UNAUTHORIZED,
                detail = "존재하지 않는 사용자입니다."
            )

        new_access = create_access_token(data = {"sub": str(user_id)})

        return new_access
    
    # 토큰 만료 에러
    except ExpiredSignatureError:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "만료된 토큰입니다. 다시 로그인해주세요."
        )

    # 다른 모든 JWT error
    except (JWTError, ValueError):
        raise credentials_exception

# JWT Token 사용자 로그인
async def token_login_services(data: UserLogin, conn: Connection):

    user_info = await login(conn, data) # user의 인덱스 값

    # 로그인에 실패한 경우
    if user_info is None:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "로그인 정보를 다시 확인해주세요."
        )
    
    user_num = user_info['index']

    access_token = create_access_token(data = {"sub": str(user_num)})
    refresh_token = create_refresh_token(data = {"sub": str(user_num)})

    current_time = _now_kst()

    await insert_user_log(
        conn = conn,
        user_index = user_num,
        action_type = "LOGIN",
        created_at = current_time
    )

    return access_token, refresh_token


async def token_logout_services(conn: Connection, user_index: int):

    current_time = _now_kst()
    
    await insert_user_log(
        conn = conn,
        user_index = user_index,
        action_type = "LOGOUT",
        created_at = current_time
    )


async def login(conn: Connection, data: UserLogin):

    login_data = await get_info_by_id(conn, data.id)

    # 사용자가 입력한 아이디가 DB에 존재하지 않을 때
    if login_data is None:
        return None

    # 비밀번호 일치
    if verify_password(data.password, login_data['password']):
        return login_data
    else:
        return None
