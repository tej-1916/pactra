"""Runtime configuration via pydantic-settings. No secrets in source."""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async SQLAlchemy URL. Postgres in production/Docker; SQLite for tests.
    database_url: str = "postgresql+asyncpg://pactra:pactra@localhost:5432/pactra"
    redis_url: str = "redis://localhost:6379/0"

    # Payments are enforced to test mode. No real credentials in source.
    razorpay_key_id: str = "rzp_test_REPLACE_ME"
    payment_test_mode: bool = True

    # How long a freshly issued authorization stays usable (Phase 3). Short by
    # design: an approval is a commitment to one transaction at one moment, and
    # a long window is a long replay window.
    authorization_ttl_seconds: int = 900

    llm_provider: str = "mock"
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
