from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_secret_key: SecretStr = Field(validation_alias="APP_SECRET_KEY")
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: SecretStr = Field(validation_alias="ADMIN_PASSWORD")
    cookie_secure: bool = Field(default=False, validation_alias="COOKIE_SECURE")
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
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
