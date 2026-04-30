from functools import lru_cache
import secrets

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reach Assignment API"
    api_v1_prefix: str = "/api/v1"
    cors_allow_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://reach:reach@127.0.0.1:5432/reach"
    )
    database_echo: bool = False
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(32))
    access_token_expire_minutes: int = 30
    jwt_algorithm: str = "HS256"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
