"""Strategy Service — central settings."""
from __future__ import annotations
from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    APP_NAME: str = "sg-strategy-service"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8004

    # ── Strategy paths ────────────────────────────────────────────────────────
    # Built-in strategies: app/strategies/builtin/
    # User strategy drop folder (hot-loaded)
    USER_STRATEGIES_DIR: Path = Path("/app/strategies")
    # Max file size for user strategies (bytes)
    MAX_STRATEGY_FILE_SIZE: int = 512_000   # 512 KB

    # ── Execution modes ───────────────────────────────────────────────────────
    TRADING_MODE: Literal["live", "paper", "backtest"] = "paper"

    # ── Per-strategy timeout ──────────────────────────────────────────────────
    STRATEGY_EXECUTION_TIMEOUT_S: float = 5.0   # max seconds per on_bar() call
    STRATEGY_MAX_RESTARTS: int = 5              # before marking as FAILED
    STRATEGY_RESTART_BACKOFF_S: float = 10.0    # wait between restarts

    # ── Signal publishing ─────────────────────────────────────────────────────
    REDIS_SIGNAL_CHANNEL_PREFIX: str = "sg:signals"
    SIGNAL_EXPIRY_S: int = 300   # signals older than 5 min are stale

    # ── Market data service ───────────────────────────────────────────────────
    MARKET_DATA_SERVICE_URL: str = "http://market-data:8002"
    REDIS_MARKET_CHANNEL_PREFIX: str = "sg:market"

    # ── NSE market hours ──────────────────────────────────────────────────────
    MARKET_TIMEZONE: str = "Asia/Kolkata"
    MARKET_OPEN_TIME: str = "09:15"
    MARKET_CLOSE_TIME: str = "15:30"

    # ── Performance tracking ──────────────────────────────────────────────────
    PERFORMANCE_WINDOW_BARS: int = 100   # rolling window for Sharpe etc.

    # ── Storage ───────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    REDIS_URL: RedisDsn = Field(...)

    # ── Observability ─────────────────────────────────────────────────────────
    PROMETHEUS_ENABLED: bool = True

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
        return v.replace("postgresql://", "postgresql+asyncpg://", 1) if v.startswith("postgresql://") else v

    @field_validator("USER_STRATEGIES_DIR", mode="before")
    @classmethod
    def ensure_path(cls, v) -> Path:
        p = Path(v)
        p.mkdir(parents=True, exist_ok=True)
        return p


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
