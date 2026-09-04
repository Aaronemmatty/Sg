from __future__ import annotations

import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    SERVICE_NAME: str = "notification_service"
    SERVICE_PORT: int = 8014
    APP_ENV: str = "development"
    LOG_LEVEL: str = "INFO"

    # Redis configuration
    REDIS_URL: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    REDIS_EXECUTIONS_PATTERN: str = Field(default="sg:executions:*", alias="REDIS_EXECUTIONS_PATTERN")

    # Telegram configuration
    TELEGRAM_BOT_TOKEN: str = Field(default="", alias="TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID: str = Field(default="", alias="TELEGRAM_CHAT_ID")
    TELEGRAM_TIMEOUT_SECONDS: float = Field(default=5.0, alias="TELEGRAM_TIMEOUT_SECONDS")
    TELEGRAM_MAX_RETRIES: int = Field(default=3, alias="TELEGRAM_MAX_RETRIES")
    TELEGRAM_RETRY_BACKOFF_BASE_SECONDS: float = Field(default=0.5, alias="TELEGRAM_RETRY_BACKOFF_BASE_SECONDS")

    # Alerts configuration
    ALERT_ON_PARTIAL_FILLS: bool = True
    ALERT_ON_FULL_FILLS: bool = True

    # JWT Authentication configuration
    AUTH_JWT_PUBLIC_KEY_PATH: str = Field(default="secrets-templates/jwt/public.pem", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    AUTH_JWT_ALGORITHM: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    AUTH_JWT_ISSUER: str | None = Field(default="sg-auth-service", alias="AUTH_JWT_ISSUER")
    ENVIRONMENT: str = Field(default="development", alias="ENVIRONMENT")

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT.lower() in ("production", "prod")


settings = Settings()
