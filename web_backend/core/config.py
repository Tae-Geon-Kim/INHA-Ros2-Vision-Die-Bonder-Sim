import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class DBSettings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: int
    DB_MAX_SIZE: int = 10
    DB_MIN_SIZE: int = 5
    
    model_config = SettingsConfigDict(
        env_file = os.path.join(os.path.dirname(__file__), ".env"),
        extra = "ignore"
    )

db_settings = DBSettings()

class JWTSettings(BaseSettings):
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    model_config = SettingsConfigDict(env_file = ".env", extra = "ignore")
    
jwt_settings = JWTSettings()

class RedisSettings(BaseSettings):
    REDIS_HOST: str
    REDIS_PORT: int
    REDIS_PASSWORD: str | None = None

    model_config = SettingsConfigDict(
        env_file = os.path.join(os.path.dirname(__file__), ".env"),
        extra = "ignore"
    )

redis_settings = RedisSettings()

class LogSettings(BaseSettings):
    LOGGING_DIR: str
    FILE_NAME: str
    WHEN: str
    INTERVAL: int
    BACKUP: int
    FORMAT: str
    DATEFMT: str

    model_config = SettingsConfigDict(
        env_file = os.path.join(os.path.dirname(__file__), ".env"),
        extra = "ignore"
    )

log_settings = LogSettings()