import uuid
import bcrypt
from asyncpg import Connection
from datetime import timedelta, datetime, timezone
from fastapi import HTTPException, status, Depends, Response, Request
from jose import jwt, JWTError
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from web_backend.core.config import jwt_settings
from web_backend.db.postgres_connection import get_db
from web_backend.models.user_models import get_current_user_info


secret_key = jwt_settings.SECRET_KEY
algorithm = jwt_settings.ALGORITHM
access_token_expire_minutes = jwt_settings.ACCESS_TOKEN_EXPIRE_MINUTES
refresh_token_expire_days = jwt_settings.REFRESH_TOKEN_EXPIRE_DAYS

credentials_exception = HTTPException(
    status_code = status.HTTP_401_UNAUTHORIZED,
    detail = "유효하지 않은 인증 자격입니다.",
    headers = {"WWW-Authenticate": "Bearer"}
)

# 비밀번호를 해싱해서 암호화 후 반환 (return 값: string)
def hash_password(password: str):   

    password = bytes(password, 'utf-8') # 암호화는 bytes에서 가능 -> bytes 변환
    hashed_password = bcrypt.hashpw(password, bcrypt.gensalt()) # hashed에는 bytes가 

    return hashed_password.decode('utf-8') # string으로

# DB에서 해싱처리된 비밀번호 값을 가져와 검증
def verify_password(plain_password: str, hashed_password: str):

    password = bytes(plain_password, 'utf-8')
    hashed_password = bytes(hashed_password, 'utf-8')

    # checkpw(password:bytes, hashed_password: bytes)

    return bcrypt.checkpw(password, hashed_password) # 반환 값: boolean

# access token 생성
def create_access_token(data: dict, expires_delta: timedelta | None = None):

    to_encode = data.copy()

    # 토큰 만료 시간 설정
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes = access_token_expire_minutes)

    to_encode.update({"exp": expire})

    # JWT access token 생성
    encode_jwt = jwt.encode(to_encode, secret_key, algorithm = algorithm)
    return encode_jwt

# refresh token 생성
def create_refresh_token(data:dict, expires_delta: timedelta | None = None):

    to_encode = data.copy()

    # 토큰 만료 시간 설정
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(days = refresh_token_expire_days)

    to_encode.update({"exp": expire})

    # JWT refresh token 생성
    encode_jwt = jwt.encode(to_encode, secret_key, algorithm = algorithm)
    return encode_jwt

# 토큰 확인
def verify_token(request: Request):

    token = request.cookies.get("access_token")

    if token is None:
        raise credentials_exception
    
    actual_token = token.split(" ")[1] if token.startswith("Bearer ") else token

    try:
        payload = jwt.decode(actual_token, secret_key, algorithms = [algorithm])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception

async def get_current_user(
    current_user_num: str = Depends(verify_token),
    conn: Connection = Depends(get_db)
):
    user_info = await get_current_user_info(conn, int(current_user_num))

    if not user_info:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail = "존재하지 않는 사용자입니다."
        )
    return user_info
