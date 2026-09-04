from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(
        default="development", alias="ENV"
    )

    service_name: str = Field(default="backtesting_engine_service", alias="SERVICE_NAME")
    port: int = Field(default=8010, alias="PORT")

    database_url: str = Field(..., alias="DATABASE_URL")
    redis_url: str = Field(default="redis://redis:6379/0", alias="REDIS_URL")

    # Auth
    auth_jwt_public_key_path: str = Field(default="", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    auth_jwt_algorithm: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    auth_jwt_issuer: str = Field(default="auth_service", alias="AUTH_JWT_ISSUER")

    # Upstream services
    market_data_service_url: str = Field(
        default="http://market_data_service:8002", alias="MARKET_DATA_SERVICE_URL"
    )
    strategy_service_url: str = Field(
        default="http://strategy_service:8004", alias="STRATEGY_SERVICE_URL"
    )
    portfolio_management_service_url: str = Field(
        default="http://portfolio_management_service:8009",
        alias="PORTFOLIO_MANAGEMENT_SERVICE_URL",
    )
    broker_service_url: str = Field(
        default="http://broker_service:8003", alias="BROKER_SERVICE_URL"
    )

    # OTel
    otel_exporter_otlp_endpoint: str = Field(
        default="http://otel-collector:4317", alias="OTEL_EXPORTER_OTLP_ENDPOINT"
    )

    # DB pool
    db_pool_min_size: int = Field(default=5, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=20, alias="DB_POOL_MAX_SIZE")

    # Backtest execution
    max_concurrent_backtests: int = Field(default=3, alias="MAX_CONCURRENT_BACKTESTS")
    backtest_job_ttl_days: int = Field(default=90, alias="BACKTEST_JOB_TTL_DAYS")
    default_initial_capital_inr: float = Field(
        default=9_000.0, alias="DEFAULT_INITIAL_CAPITAL_INR"
    )
    default_commission_bps: float = Field(default=3.0, alias="DEFAULT_COMMISSION_BPS")
    default_slippage_bps: float = Field(default=5.0, alias="DEFAULT_SLIPPAGE_BPS")
    benchmark_symbol: str = Field(default="NIFTY50", alias="BENCHMARK_SYMBOL")

    # Monte Carlo
    monte_carlo_default_iterations: int = Field(
        default=2000, alias="MONTE_CARLO_DEFAULT_ITERATIONS"
    )

    http_client_timeout_seconds: float = Field(
        default=15.0, alias="HTTP_CLIENT_TIMEOUT_SECONDS"
    )


settings = Settings()  # type: ignore[call-arg]
