"""Service settings, read from environment variables (see .env.example)."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(..., description="SQLAlchemy URL, e.g. postgresql+psycopg://user:pass@host:5432/db")
    jwt_secret: str = Field(..., min_length=32, description="HS256 signing secret shared with the gateway")
    jwt_expires_min: int = Field(60, ge=1, le=24 * 60)
    jwt_issuer: str = "tuition-auth"

    api_prefix: str = "/api/v1"
    app_name: str = "Tuition API"
    app_version: str = "1.0.0"


@lru_cache
def get_settings() -> Settings:
    return Settings()
