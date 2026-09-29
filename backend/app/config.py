from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        env_ignore_empty=True,
        extra="ignore",
    )

    app_secret_key: SecretStr = Field(validation_alias="APP_SECRET_KEY")
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: SecretStr = Field(validation_alias="ADMIN_PASSWORD")
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")
    gemini_api_key: SecretStr | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    gemini_model: str = Field(default="gemini-3.8-flash", validation_alias="GEMINI_MODEL")
    gemini_timeout_seconds: float = Field(default=25.0, validation_alias="GEMINI_TIMEOUT_SECONDS", gt=0, le=120)
    gemini_retry_attempts: int = Field(default=3, validation_alias="GEMINI_RETRY_ATTEMPTS", ge=1, le=6)
    enable_regex_fallback: bool = Field(default=False, validation_alias="ENABLE_REGEX_FALLBACK")
    telegram_api_id: int | None = Field(default=None, validation_alias="TELEGRAM_API_ID", gt=0)
    telegram_api_hash: SecretStr | None = Field(default=None, validation_alias="TELEGRAM_API_HASH")
    database_url: str = Field(
        default="sqlite:///backend/data/app.db",
        validation_alias="DATABASE_URL",
    )

    @model_validator(mode="after")
    def validate_credentials(self) -> "Settings":
        if len(self.app_secret_key.get_secret_value()) < 32:
            raise ValueError("APP_SECRET_KEY must contain at least 32 characters")
        if len(self.admin_password.get_secret_value()) < 12:
            raise ValueError("ADMIN_PASSWORD must contain at least 12 characters")
        if not self.admin_username.strip():
            raise ValueError("ADMIN_USERNAME cannot be empty")
        if not self.gemini_model.strip():
            raise ValueError("GEMINI_MODEL cannot be empty")
        if (self.telegram_api_id is None) != (self.telegram_api_hash is None):
            raise ValueError("TELEGRAM_API_ID dan TELEGRAM_API_HASH harus diisi bersamaan")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
