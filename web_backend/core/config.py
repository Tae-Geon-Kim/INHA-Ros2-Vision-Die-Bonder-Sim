import os
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
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

settings = Settings()