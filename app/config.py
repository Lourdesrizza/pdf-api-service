from functools import lru_cache
from re import fullmatch

from pydantic import Field, HttpUrl, SecretStr, TypeAdapter, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BEARER_TOKEN_PATTERN = r"[A-Za-z0-9._~+/-]{32,512}={0,2}"


class Settings(BaseSettings):
    extractor_url: str = "http://extractor:8000"
    document_service_url: str = "http://documents:8000"
    documents_api_token: SecretStr = SecretStr("")
    api_require_auth: bool = False
    api_access_token: SecretStr = SecretStr("")
    port: int = Field(default=8000, ge=1, le=65535)
    max_upload_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    extractor_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    document_timeout_seconds: float = Field(default=5, gt=0, allow_inf_nan=False)
    ready_check_timeout_seconds: float = Field(default=2, gt=0, allow_inf_nan=False)
    body_timeout_seconds: float = Field(default=30, gt=0, allow_inf_nan=False)
    max_concurrent_requests: int = Field(default=0, ge=0)
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", hide_input_in_errors=True,
    )

    @field_validator("documents_api_token")
    @classmethod
    def validate_documents_api_token(cls, value: SecretStr) -> SecretStr:
        token = value.get_secret_value()
        if token and not fullmatch(BEARER_TOKEN_PATTERN, token):
            raise ValueError("DOCUMENTS_API_TOKEN no tiene un formato Bearer válido")
        return value

    @field_validator("api_access_token")
    @classmethod
    def validate_api_access_token(cls, value: SecretStr, info: ValidationInfo) -> SecretStr:
        if info.data.get("api_require_auth") and not fullmatch(
            BEARER_TOKEN_PATTERN, value.get_secret_value()
        ):
            raise ValueError("Configurá API_ACCESS_TOKEN con un token Bearer válido.")
        return value

    @field_validator("extractor_url", "document_service_url")
    @classmethod
    def validate_service_url(cls, value: str) -> str:
        url = TypeAdapter(HttpUrl).validate_python(value)
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("Use a base HTTP URL without credentials, query or fragment")
        return str(url).rstrip("/")


@lru_cache
def get_settings() -> Settings:
    return Settings()
