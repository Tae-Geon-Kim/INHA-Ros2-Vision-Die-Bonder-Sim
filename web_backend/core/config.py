from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class DBSettings(BaseSettings):
    DB_USER: str
    DB_PASSWORD: str
    DB_NAME: str
    DB_HOST: str
    DB_PORT: int
    DB_MAX_SIZE: int = 10
    DB_MIN_SIZE: int = 5
    
    model_config = SettingsConfigDict(
        env_file = str(ENV_FILE),
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

db_settings = DBSettings()

class JWTSettings(BaseSettings):
    SECRET_KEY: str = "your-secret-key"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    
    model_config = SettingsConfigDict(
        env_file = str(ENV_FILE),
        env_file_encoding = "utf-8",
        extra = "ignore"
    )
    
jwt_settings = JWTSettings()

class LogSettings(BaseSettings):
    LOGGING_DIR: str
    FILE_NAME: str
    WHEN: str
    INTERVAL: int
    BACKUP: int
    FORMAT: str
    DATEFMT: str

    model_config = SettingsConfigDict(
        env_file = str(ENV_FILE),
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

log_settings = LogSettings()

class InitialUserSettings(BaseSettings):
    INITIAL_USER_ID: str | None = None
    INITIAL_USER_PASSWORD: str | None = None

    model_config = SettingsConfigDict(
        env_file = str(ENV_FILE),
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

initial_user_settings = InitialUserSettings()

class FrontendSettings(BaseSettings):
    FRONTEND_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def allowed_origins(self):
        return [
            origin.strip()
            for origin in self.FRONTEND_ORIGINS.split(",")
            if origin.strip()
        ]

    model_config = SettingsConfigDict(
        env_file = str(ENV_FILE),
        env_file_encoding = "utf-8",
        extra = "ignore"
    )

frontend_settings = FrontendSettings()
