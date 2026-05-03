from functools import lru_cache
import os
import secrets
import socket

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    worker_id: str = Field(default_factory=lambda: _default_worker_id())
    worker_poll_interval_seconds: float = 1
    worker_lease_seconds: int = 60
    worker_batch_size: int = 10
    worker_base_backoff_seconds: float = 2
    worker_max_backoff_seconds: float = 300
    worker_jitter_seconds: float = 3
    lease_reaper_interval_seconds: float = 10
    lease_reaper_batch_size: int = 50

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


def _default_worker_id() -> str:
    suffix = secrets.token_hex(3)
    return f"{socket.gethostname()}-{os.getpid()}-{suffix}"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings()
