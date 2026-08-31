"""
Configuration for regime_detection_service.

All settings are environment-driven (12-factor) with sane defaults for local/dev use.
Mirrors the conventions used by market_data_service / broker_service / strategy_service.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="", extra="ignore")

    # --- Service identity -------------------------------------------------
    SERVICE_NAME: str = "regime_detection_service"
    SERVICE_PORT: int = 8005
    ENV: Literal["dev", "staging", "prod"] = "dev"
    LOG_LEVEL: str = "INFO"

    # --- Database ----------------------------------------------------------
    DATABASE_URL: str = "postgresql+asyncpg://sg:sg@localhost:5432/sg_db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5
    DEFAULT_TENANT_ID: str = "00000000-0000-0000-0000-000000000001"

    # --- Redis ---------------------------------------------------------------
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_KEY_PREFIX_REGIME: str = "regime"
    REDIS_CHANNEL_CANDLE_PREFIX: str = "sg:market:candle"
    REDIS_CHANNEL_REGIME_PREFIX: str = "sg:regime"
    REDIS_CHANNEL_MARKET_STATUS: str = "sg:market:status"

    # --- Market data ----------------------------------------------------------
    MARKET_DATA_SERVICE_URL: str = "http://market_data_service:8002"
    PRIMARY_SYMBOL: str = "NIFTY50"  # market-wide proxy
    PRIMARY_EXCHANGE: str = "NSE"
    DEFAULT_TIMEFRAME: str = "5m"
    WATCHLIST_SYMBOLS: list[str] = Field(
        default_factory=lambda: [
            "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
            "TATAMOTORS", "SBIN", "ITC", "LT", "AXISBANK",
        ]
    )
    BREADTH_UNIVERSE_SYMBOLS: list[str] = Field(
        default_factory=lambda: [
            "RELIANCE", "HDFCBANK", "ICICIBANK", "INFY", "TCS",
            "TATAMOTORS", "SBIN", "ITC", "LT", "AXISBANK",
            "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "BHARTIARTL", "ASIANPAINT",
            "MARUTI", "SUNPHARMA", "TITAN", "ULTRACEMCO", "WIPRO",
        ]
    )
    VIX_SYMBOL: str = "INDIAVIX"

    # --- Feature engineering windows -----------------------------------------
    ADX_PERIOD: int = 14
    ATR_PERIOD: int = 14
    BB_PERIOD: int = 20
    BB_STD: float = 2.0
    VOLUME_AVG_PERIOD: int = 20
    TREND_SLOPE_PERIOD: int = 20
    RETURNS_STD_PERIOD: int = 20
    MIN_BARS_REQUIRED: int = 60  # warm-up window before classification is trusted

    # --- Classifier -----------------------------------------------------------
    REGIME_MODEL_PATH: str = "models/regime_classifier.joblib"
    CLASSIFIER_TYPE: Literal["gradient_boosting", "random_forest"] = "random_forest"
    MIN_CONFIDENCE_FOR_TRANSITION: float = 0.55
    PER_SYMBOL_DIVERGENCE_THRESHOLD: float = 0.6  # 0-1 normalized divergence score

    # --- Scheduling / debounce -------------------------------------------------
    RECALC_INTERVAL_SECONDS: int = 300  # 5 minutes - watchdog fallback
    TRANSITION_CONFIRM_BARS: int = 2  # require N consecutive bars before confirming a flip

    # --- Auth -------------------------------------------------------------------
    JWT_PUBLIC_KEY_PATH: str = "/run/secrets/auth_public_key.pem"
    AUTH_REQUIRED: bool = True

    @field_validator("WATCHLIST_SYMBOLS", "BREADTH_UNIVERSE_SYMBOLS", mode="before")
    @classmethod
    def _split_csv(cls, v):
        if isinstance(v, str):
            return [s.strip() for s in v.split(",") if s.strip()]
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()
