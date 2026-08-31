"""Market Data Service — central settings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ───────────────────────────────────────────────────────────────────
    APP_NAME: str = "sg-market-data-service"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8002

    # ── Kite Connect ──────────────────────────────────────────────────────────
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_ACCESS_TOKEN: str = ""
    # Feed mode: "live" uses real KiteTicker, "mock" uses synthetic generator
    KITE_MODE: Literal["live", "mock"] = "live"
    # Max symbols per WebSocket session (Kite limit = 3000)
    KITE_MAX_SUBSCRIPTIONS: int = 3000
    # Reconnect settings
    KITE_RECONNECT_MAX_TRIES: int = 50
    KITE_RECONNECT_MAX_DELAY: int = 60

    # ── Yahoo Finance ─────────────────────────────────────────────────────────
    YAHOO_ENABLED: bool = True
    YAHOO_MAX_RETRIES: int = 3
    YAHOO_RETRY_DELAY: float = 2.0

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(...)
    # TTL for live tick cache (24 hours — cleared at market open)
    REDIS_TICK_TTL: int = 86_400
    # TTL for current candle in-progress
    REDIS_CANDLE_TTL: int = 90  # 90 seconds — 1 minute + buffer
    # Pub/Sub channel prefix
    REDIS_CHANNEL_PREFIX: str = "sg:market"

    # ── ClickHouse (optional raw tick archive) ────────────────────────────────
    CLICKHOUSE_ENABLED: bool = False
    CLICKHOUSE_HOST: str = "clickhouse"
    CLICKHOUSE_PORT: int = 9000
    CLICKHOUSE_DB: str = "sg_ticks"
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""

    # ── Aggregation ───────────────────────────────────────────────────────────
    # Base candle timeframe in minutes (everything aggregated from this)
    BASE_TIMEFRAME_MINUTES: int = 1
    # All timeframes to maintain (in minutes; 1D = 375 = NSE full session)
    AGGREGATION_TIMEFRAMES: list[int] = [1, 3, 5, 15, 30, 60, 240, 375]

    # ── NSE Market hours (IST) ────────────────────────────────────────────────
    MARKET_OPEN_TIME: str = "09:15"     # IST
    MARKET_CLOSE_TIME: str = "15:30"    # IST
    PREOPEN_START_TIME: str = "09:00"   # IST
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    # Trading days (0=Mon … 4=Fri)
    TRADING_DAYS: list[int] = [0, 1, 2, 3, 4]

    # ── Data quality ──────────────────────────────────────────────────────────
    # Reject ticks with price deviation > X% from last price
    MAX_PRICE_DEVIATION_PCT: float = 20.0
    # Reject ticks with volume > X * avg_volume
    MAX_VOLUME_SPIKE_MULTIPLIER: float = 50.0
    # Minimum valid price
    MIN_VALID_PRICE: float = 0.05

    # ── Retention ─────────────────────────────────────────────────────────────
    # Keep 1-min bars for N days before summarising to daily
    TICK_RETENTION_DAYS: int = 365
    # Purge daily OHLCV older than N years
    DAILY_RETENTION_YEARS: int = 10

    # ── Observability ─────────────────────────────────────────────────────────
    PROMETHEUS_ENABLED: bool = True
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"

    # ── Auth (auth_service / 8001) ────────────────────────────────────────────
    AUTH_JWT_PUBLIC_KEY_PATH: str = ""
    AUTH_JWT_ALGORITHM: str = "RS256"
    AUTH_JWT_ISSUER: str = "auth_service"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def ensure_asyncpg(cls, v: str) -> str:
        if v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
