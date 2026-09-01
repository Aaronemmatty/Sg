"""Central settings — all values from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import AnyHttpUrl, EmailStr, Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "sg-auth-service"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"

    # ── Server ───────────────────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    WORKERS: int = 1
    ROOT_PATH: str = ""

    # ── Security ─────────────────────────────────────────────────────────────
    SECRET_KEY: str = Field(..., min_length=64)
    JWT_ALGORITHM: str = "RS256"
    JWT_PRIVATE_KEY: str = Field(...)       # PEM — RSA 4096
    JWT_PUBLIC_KEY: str = Field(...)        # PEM — RSA 4096
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    EMAIL_VERIFICATION_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_EXPIRE_MINUTES: int = 30
    MFA_OTP_PERIOD: int = 30               # TOTP window seconds
    MAX_LOGIN_ATTEMPTS: int = 5
    LOCKOUT_DURATION_MINUTES: int = 15
    ALLOWED_ORIGINS: list[AnyHttpUrl] = []

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # ── Redis ────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(...)
    REDIS_SESSION_TTL_SECONDS: int = 86_400 * 30   # 30 days

    # ── Email ────────────────────────────────────────────────────────────────
    SENDGRID_API_KEY: str = ""
    EMAIL_FROM: EmailStr = "noreply@sg-trading.com"
    EMAIL_FROM_NAME: str = "SG Trading Platform"

    # ── OAuth2 providers ─────────────────────────────────────────────────────
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = ""

    # ── Observability ────────────────────────────────────────────────────────
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    PROMETHEUS_ENABLED: bool = True

    # ── Celery ───────────────────────────────────────────────────────────────
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""

    # ── Feature flags ────────────────────────────────────────────────────────
    MFA_REQUIRED: bool = False
    EMAIL_VERIFICATION_REQUIRED: bool = True
    DEVICE_TRACKING_ENABLED: bool = True

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def validate_db_url(cls, v: str) -> str:
        # Ensure asyncpg driver is used
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql+psycopg://"):
            return v.replace("postgresql+psycopg://", "postgresql+asyncpg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
