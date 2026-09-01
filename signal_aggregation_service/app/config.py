"""
Configuration for signal_aggregation_service.

Includes the static default regime -> strategy weight tables (the brief's example
values). These are the fallback layer; `app/services/weight_store.py` overlays any
DB-backed overrides on top of these at runtime.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Regime -> strategy -> weight. Weights need not sum to 1; the WeightingEngine
# renormalizes over whichever strategies actually have a fresh signal at compute time.
DEFAULT_REGIME_WEIGHTS: dict[str, dict[str, float]] = {
    "TRENDING": {
        "trend_following": 0.40,
        "breakout": 0.30,
        "momentum": 0.20,
        "ml_prediction": 0.10,
    },
    "RANGING": {
        "mean_reversion": 0.50,
        "rsi": 0.20,
        "ml_prediction": 0.20,
        "trend_following": 0.10,
    },
    # Sensible, conservative defaults for the remaining regime types. These are starting
    # points, not platform wisdom — tune via the DB-backed override API once you have
    # live performance data per regime.
    "HIGH_VOLATILITY": {
        "mean_reversion": 0.30,
        "ml_prediction": 0.30,
        "breakout": 0.20,
        "trend_following": 0.20,
    },
    "LOW_VOLATILITY": {
        "trend_following": 0.35,
        "breakout": 0.25,
        "momentum": 0.25,
        "ml_prediction": 0.15,
    },
    "BULLISH": {
        "trend_following": 0.35,
        "momentum": 0.30,
        "breakout": 0.20,
        "ml_prediction": 0.15,
    },
    "BEARISH": {
        "trend_following": 0.30,
        "mean_reversion": 0.25,
        "ml_prediction": 0.25,
        "momentum": 0.20,
    },
    "RISK_ON": {
        "momentum": 0.35,
        "breakout": 0.30,
        "trend_following": 0.20,
        "ml_prediction": 0.15,
    },
    "RISK_OFF": {
        "mean_reversion": 0.40,
        "ml_prediction": 0.30,
        "trend_following": 0.30,
    },
    "SIDEWAYS": {
        "mean_reversion": 0.40,
        "rsi": 0.30,
        "ml_prediction": 0.30,
    },
}

# Fallback applied to ANY regime not explicitly listed above (defensive default).
FALLBACK_WEIGHTS: dict[str, float] = {
    "trend_following": 0.25,
    "mean_reversion": 0.25,
    "breakout": 0.20,
    "momentum": 0.15,
    "ml_prediction": 0.15,
}


from sg_security.universe import get_tradeable_universe


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # --- Service identity -------------------------------------------------
    SERVICE_NAME: str = "signal_aggregation_service"
    SERVICE_PORT: int = 8006
    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # --- Database ----------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://sg:sg@localhost:5432/sg_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"

    # --- Redis ---------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_KEY_PREFIX_AGGREGATED: str = "aggregated_signal"
    REDIS_CHANNEL_SIGNALS_PREFIX: str = "sg:signals"
    REDIS_CHANNEL_REGIME_PREFIX: str = "sg:regime"
    REDIS_CHANNEL_AGGREGATED_PREFIX: str = "sg:aggregated_signal"
    REDIS_CHANNEL_WEIGHTS_UPDATED: str = "sg:weights:updated"
    SIGNAL_KEY_SCAN_PATTERN: str = "signal:*:{symbol}:{timeframe}"

    # --- Scope ---------------------------------------------------------------
    DEFAULT_TIMEFRAME: str = "5m"
    PRIMARY_SYMBOL: str = "NIFTY50"
    WATCHLIST_SYMBOLS: list[str] = Field(
        default_factory=lambda: get_tradeable_universe(prefix=False)
    )
    STRATEGY_REGISTRY: list[str] = Field(
        default_factory=lambda: [
            "trend_following", "mean_reversion", "breakout", "momentum", "ml_prediction", "rsi",
        ]
    )


    # --- Aggregation behavior -------------------------------------------------
    BUY_THRESHOLD: float = 0.20  # net_score >= this -> BUY
    SELL_THRESHOLD: float = -0.20  # net_score <= this -> SELL
    MIN_STRATEGIES_REQUIRED: int = 2  # below this, force HOLD / cap confidence
    MIN_INDIVIDUAL_CONFIDENCE_FOR_CONTRIBUTOR: float = 0.50
    SIGNAL_STALENESS_SECONDS: int = 900  # ignore a strategy signal older than this
    DEFAULT_UNMAPPED_STRATEGY_WEIGHT: float = 0.05  # weight for strategies not in any weight map
    AGREEMENT_DAMPENING_FLOOR: float = 0.5  # confidence multiplier floor at zero agreement

    # --- Recalculation / debounce -----------------------------------------------
    RECALC_INTERVAL_SECONDS: int = 300  # 5-minute watchdog cadence
    STALE_AFTER_SECONDS: int = 600

    # --- Weight cache ----------------------------------------------------------
    WEIGHT_CACHE_TTL_SECONDS: int = 60

    # --- Auth -------------------------------------------------------------------
    JWT_PUBLIC_KEY_PATH: str = "/run/secrets/auth_public_key.pem"
    AUTH_REQUIRED: bool = True

    @field_validator("WATCHLIST_SYMBOLS", "STRATEGY_REGISTRY", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
