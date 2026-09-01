"""
Configuration for execution_engine_service (8008).

Loaded once as a module-level singleton `settings`. Matches the
pydantic-settings pattern used across 8001-8007.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development", alias="ENV")

    service_port: int = Field(default=8008, alias="SERVICE_PORT")
    service_name: str = Field(default="execution_engine_service", alias="SERVICE_NAME")

    # Postgres
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_min_size: int = Field(default=5, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=20, alias="DB_POOL_MAX_SIZE")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_risk_approved_pattern: str = Field(default="sg:risk_approved:*", alias="REDIS_RISK_APPROVED_PATTERN")
    redis_execution_channel_prefix: str = Field(default="sg:executions", alias="REDIS_EXECUTION_CHANNEL_PREFIX")
    redis_execution_events_channel: str = Field(default="sg:execution:events", alias="REDIS_EXECUTION_EVENTS_CHANNEL")

    # Auth (auth_service / 8001)
    auth_jwt_public_key_path: str = Field(default="", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    auth_jwt_algorithm: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    auth_jwt_issuer: str = Field(default="auth_service", alias="AUTH_JWT_ISSUER")

    # broker_service (8003)
    broker_service_base_url: str = Field(default="http://localhost:8003", alias="BROKER_SERVICE_BASE_URL")
    broker_service_timeout_seconds: float = Field(default=5.0, alias="BROKER_SERVICE_TIMEOUT_SECONDS")
    broker_call_max_retries: int = Field(default=3, alias="BROKER_CALL_MAX_RETRIES")
    broker_call_backoff_base_seconds: float = Field(default=0.5, alias="BROKER_CALL_BACKOFF_BASE_SECONDS")

    # Routing / smart execution
    default_execution_style: Literal["AGGRESSIVE", "PASSIVE"] = Field(
        default="AGGRESSIVE", alias="DEFAULT_EXECUTION_STYLE"
    )
    product_type: str = Field(default="MIS", alias="PRODUCT_TYPE")
    passive_limit_band_bps: float = Field(default=15.0, alias="PASSIVE_LIMIT_BAND_BPS")
    order_validity: Literal["DAY", "IOC"] = Field(default="DAY", alias="ORDER_VALIDITY")

    # Post-submit polling
    post_submit_poll_interval_seconds: float = Field(default=2.0, alias="POST_SUBMIT_POLL_INTERVAL_SECONDS")
    post_submit_poll_timeout_seconds: float = Field(default=60.0, alias="POST_SUBMIT_POLL_TIMEOUT_SECONDS")

    # Reconciliation
    reconciliation_interval_seconds: float = Field(default=30.0, alias="RECONCILIATION_INTERVAL_SECONDS")

    # RISK_HOLD handling
    hold_sweep_interval_seconds: float = Field(default=15.0, alias="HOLD_SWEEP_INTERVAL_SECONDS")
    hold_max_age_seconds: float = Field(default=900.0, alias="HOLD_MAX_AGE_SECONDS")

    # Idempotency
    idempotency_key_ttl_seconds: int = Field(default=86400, alias="IDEMPOTENCY_KEY_TTL_SECONDS")

    # Observability
    otel_exporter_otlp_endpoint: str = Field(default="http://otel-collector:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
