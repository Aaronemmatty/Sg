"""Execution Orchestrator Service — settings."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME: str = "sg-execution-orchestrator"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    LOG_LEVEL: str = "INFO"
    HOST: str = "0.0.0.0"
    PORT: int = 8006

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: PostgresDsn = Field(...)
    DATABASE_POOL_SIZE: int = 10
    DATABASE_MAX_OVERFLOW: int = 5

    # ── Redis ─────────────────────────────────────────────────────────────────
    REDIS_URL: RedisDsn = Field(...)

    # Redis channel names — IN
    REDIS_CHANNEL_APPROVED_PREFIX: str = "sg:approved"      # sg:approved:{symbol}
    REDIS_CHANNEL_REGIME_PREFIX: str = "sg:regime"          # sg:regime:{symbol}

    # Redis channel names — OUT
    REDIS_CHANNEL_INTENTS_PREFIX: str = "sg:intents"        # sg:intents:{symbol}

    # Redis state keys written by downstream services (hot-path reads)
    REDIS_KEY_PORTFOLIO_STATE: str = "sg:portfolio:state:{portfolio_id}"
    REDIS_KEY_RISK_STATE: str = "sg:risk:state:{portfolio_id}"
    REDIS_KEY_REGIME: str = "sg:regime:{symbol}"

    # State cache TTL (seconds)
    PORTFOLIO_STATE_TTL_S: int = 30
    RISK_STATE_TTL_S: int = 15
    INTENT_CACHE_TTL_S: int = 300

    # ── Symbols / portfolio ────────────────────────────────────────────────────
    PRIMARY_SYMBOL: str = "NIFTY"
    WATCHLIST_SYMBOLS: list[str] = []
    DEFAULT_PORTFOLIO_ID: str = ""          # UUID string; empty = use broker default

    # ── Eligibility thresholds ────────────────────────────────────────────────
    MIN_CONFIDENCE: float = 0.60            # below this → REJECTED / low_confidence
    MIN_LIQUIDITY_VALUE_INR: float = 100_000.0  # notional required for liquidity gate

    # ── Position limits ───────────────────────────────────────────────────────
    MAX_POSITION_PCT: float = 0.10          # max 10% of portfolio in one symbol
    MAX_SECTOR_EXPOSURE_PCT: float = 0.30   # max 30% in one sector
    MAX_CORRELATION_SCORE: float = 0.80     # Pearson ρ above this → reject

    # ── Capital allocation ────────────────────────────────────────────────────
    DEFAULT_RISK_PCT: float = 1.0           # % of portfolio risked per trade
    PRODUCT_TYPE: str = "MIS"               # MIS (intraday) | CNC (delivery) | NRML
    MAX_ALLOCATION_INR: float = 500_000.0   # hard cap per single intent (5 lakh)
    MIN_ALLOCATION_INR: float = 1_000.0     # below this → not worth executing

    # ── Daily loss guard ──────────────────────────────────────────────────────
    DAILY_LOSS_LIMIT_INR: float = 50_000.0  # mirrors broker_service default
    DAILY_LOSS_LIMIT_PCT: float = 0.05      # 5% of portfolio NAV

    # ── Portfolio risk limits ─────────────────────────────────────────────────
    MAX_PORTFOLIO_DRAWDOWN_PCT: float = 0.15  # 15% max drawdown guard
    MAX_OPEN_INTENTS: int = 20               # concurrent live ELIGIBLE intents

    # ── Downstream service URLs (HTTP fallback) ───────────────────────────────
    BROKER_SERVICE_URL: str = "http://broker-service:8003"
    RISK_ENGINE_URL: str = "http://risk-engine:8007"         # next service

    # ── Observability ─────────────────────────────────────────────────────────
    PROMETHEUS_ENABLED: bool = True
    OTEL_ENDPOINT: str = "http://otel-collector:4317"
    OTEL_SERVICE_NAME: str = "execution-orchestrator"

    # ── Audit ─────────────────────────────────────────────────────────────────
    AUDIT_LOG_ENABLED: bool = True

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
