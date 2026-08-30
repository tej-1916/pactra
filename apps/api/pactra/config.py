"""Runtime configuration via pydantic-settings. No secrets in source."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Async SQLAlchemy URL. Postgres in production/Docker; SQLite for tests.
    database_url: str = "postgresql+asyncpg://pactra:pactra@localhost:5432/pactra"
    redis_url: str = "redis://localhost:6379/0"

    # Payments are enforced to test mode. No real credentials in source. The
    # two secrets use SecretStr so settings repr/debug output cannot disclose
    # them accidentally. Empty defaults fail closed in the provider factory.
    razorpay_key_id: str = "rzp_test_REPLACE_ME"
    razorpay_key_secret: SecretStr = SecretStr("")
    razorpay_webhook_secret: SecretStr = SecretStr("")
    razorpay_connect_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    razorpay_read_timeout_seconds: float = Field(default=7.0, gt=0, le=60)
    razorpay_write_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    razorpay_pool_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    razorpay_overall_timeout_seconds: float = Field(default=10.0, gt=0, le=60)
    payment_test_mode: bool = True

    # How long a freshly issued authorization stays usable (Phase 3). Short by
    # design: an approval is a commitment to one transaction at one moment, and
    # a long window is a long replay window.
    authorization_ttl_seconds: int = 900

    # LOCAL CRYPTOGRAPHIC APPROVAL PROOF demo trust root.  The corresponding
    # DEMO USER-CONTROLLED SIGNING KEY remains outside PACTRA.  The public key
    # is 32 Ed25519 bytes encoded as exactly 64 lowercase hex characters.
    demo_approver_signing_key_id: str = Field(
        default="demo-user-ed25519-v1", min_length=1, max_length=120
    )
    demo_approver_public_key_hex: str | None = None

    llm_provider: str = "mock"
    app_env: str = "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
