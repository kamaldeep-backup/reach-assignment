from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Reach Assignment API"
    api_v1_prefix: str = "/api/v1"
    database_url: PostgresDsn = Field(
        default="postgresql+asyncpg://reach:reach@127.0.0.1:5432/reach"
    )
    database_echo: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
