from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    extractor_url: str = "http://extractor:8000"
    document_service_url: str = "http://documents:8000"
    port: int = 8000
    max_upload_bytes: int = 10 * 1024 * 1024
    extractor_timeout_seconds: float = 30
    document_timeout_seconds: float = 5
    ready_check_timeout_seconds: float = 2
    max_concurrent_requests: int = 0
    log_level: str = "INFO"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
