"""Broker Service — settings."""
from __future__ import annotations
from functools import lru_cache
from typing import Literal
from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")

    APP_NAME: str = "sg-broker-service"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8003

    # ── Kite ──────────────────────────────────────────────────────────────────
    KITE_API_KEY: str = ""
    KITE_API_SECRET: str = ""
    KITE_ACCESS_TOKEN: str = ""
    # "live" or "paper" — paper uses Paper broker, live uses Kite
    BROKER_MODE: Literal["live", "paper"] = "paper"
    # Thread pool workers for sync Kite SDK calls
    KITE_EXECUTOR_WORKERS: int = 4

    # ── Rate limiting (Kite limits) ───────────────────────────────────────────
    KITE_ORDERS_PER_SECOND: float = 10.0
    KITE_REQUESTS_PER_MINUTE: int = 200

    # ── Circuit breaker ───────────────────────────────────────────────────────
    CB_FAILURE_THRESHOLD: int = 5        # consecutive failures to open circuit
    CB_RECOVERY_TIMEOUT_S: int = 60      # seconds before half-open attempt
    CB_SUCCESS_THRESHOLD: int = 2        # successes in half-open to close circuit

    # ── Retry ─────────────────────────────────────────────────────────────────
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_MIN_WAIT_S: float = 1.0
    RETRY_MAX_WAIT_S: float = 10.0

    # ── Retail account capital reference ─────────────────────────────────────
    # Initial / default capital base used when live broker balance is unavailable.
    # Set once in .env — do NOT update after every P&L move. Percentage limits
    # below are computed from the live available_cash at pre-trade-check time.
    ACCOUNT_CAPITAL_INR: float = 9000.0

    # ── Pre-trade risk — percentage-based (applied to live available_cash) ────
    # The risk engine derives effective INR limits at runtime via
    # get_account_info(); these pct values are the authoritative knobs.
    MAX_ORDER_VALUE_PCT: float = 0.20     # 20% of live available cash per order
    MAX_POSITION_VALUE_PCT: float = 0.20  # 20% of live available cash per position
    MAX_DAILY_LOSS_PCT: float = 0.02      # 2% of live available cash as daily kill-switch
    MAX_ORDERS_PER_SYMBOL_PER_DAY: int = 50
    ALLOWED_EXCHANGES: list[str] = ["NSE", "BSE"]
    ALLOWED_PRODUCTS: list[str] = ["CNC", "MIS", "NRML"]

    # ── Paper broker ──────────────────────────────────────────────────────────
    PAPER_INITIAL_CAPITAL_INR: float = 9_000.0  # mirrors ACCOUNT_CAPITAL_INR (was ₹10 lakh)
    PAPER_SLIPPAGE_PCT: float = 0.05             # 0.05% simulated slippage
    PAPER_FILL_DELAY_MS: int = 100               # simulated fill latency

    # ── Storage ───────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    REDIS_URL: RedisDsn = Field(...)

    # ── Market data service (for paper broker fills) ──────────────────────────
    MARKET_DATA_SERVICE_URL: str = "http://market-data:8002"

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


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
