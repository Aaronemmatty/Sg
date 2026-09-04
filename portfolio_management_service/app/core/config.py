"""
Configuration for portfolio_management_service (8009).

Matches the pydantic-settings pattern used across 8001–8008.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development", alias="ENV")

    service_port: int = Field(default=8009, alias="SERVICE_PORT")
    service_name: str = Field(default="portfolio_management_service", alias="SERVICE_NAME")

    # Postgres
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_min_size: int = Field(default=5, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=20, alias="DB_POOL_MAX_SIZE")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Inbound: execution fill events (from execution_engine_service / 8008)
    redis_executions_pattern: str = Field(default="sg:executions:*", alias="REDIS_EXECUTIONS_PATTERN")
    redis_execution_events_channel: str = Field(
        default="sg:execution:events", alias="REDIS_EXECUTION_EVENTS_CHANNEL"
    )

    # Outbound: portfolio state events (for dashboards / downstream)
    redis_portfolio_events_channel: str = Field(
        default="sg:portfolio:events", alias="REDIS_PORTFOLIO_EVENTS_CHANNEL"
    )

    # Auth
    auth_jwt_public_key_path: str = Field(default="", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    auth_jwt_algorithm: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    auth_jwt_issuer: str = Field(default="auth_service", alias="AUTH_JWT_ISSUER")

    # Upstream
    market_data_service_url: str = Field(
        default="http://market_data_service:8002", alias="MARKET_DATA_SERVICE_URL"
    )
    market_data_timeout_seconds: float = Field(default=3.0, alias="MARKET_DATA_TIMEOUT_SECONDS")

    # Mark-to-market
    mtm_refresh_interval_seconds: float = Field(default=5.0, alias="MTM_REFRESH_INTERVAL_SECONDS")
    mtm_market_hours_only: bool = Field(default=True, alias="MTM_MARKET_HOURS_ONLY")

    # Snapshot persistence
    snapshot_interval_seconds: float = Field(default=60.0, alias="SNAPSHOT_INTERVAL_SECONDS")

    # Benchmark
    benchmark_symbol: str = Field(default="NIFTY50", alias="BENCHMARK_SYMBOL")

    # Upstream Broker & Risk Engine Services
    broker_service_url: str = Field(default="http://localhost:8003", alias="BROKER_SERVICE_URL")
    broker_timeout_seconds: float = Field(default=5.0, alias="BROKER_TIMEOUT_SECONDS")
    risk_engine_service_url: str = Field(default="http://localhost:8007", alias="RISK_ENGINE_SERVICE_URL")
    risk_timeout_seconds: float = Field(default=5.0, alias="RISK_TIMEOUT_SECONDS")

    # Position reconciliation
    position_reconciliation_enabled: bool = Field(default=True, alias="POSITION_RECONCILIATION_ENABLED")
    position_reconciliation_poll_interval_seconds: float = Field(
        default=30.0, alias="POSITION_RECONCILIATION_POLL_INTERVAL_SECONDS"
    )

    # Observability
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    @property
    def is_production(self) -> bool:
        return self.env == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
