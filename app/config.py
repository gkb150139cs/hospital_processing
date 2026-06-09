from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, overridable via environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    hospital_api_base_url: str = "https://hospital-directory.onrender.com"
    max_csv_rows: int = 20
    max_concurrent_requests: int = 5
    request_timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_backoff_base_seconds: float = 0.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
