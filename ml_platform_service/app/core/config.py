"""Configuration for ml_platform_service (8011)."""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["development", "staging", "production"] = Field(default="development", alias="ENV")
    service_port: int = Field(default=8011, alias="SERVICE_PORT")
    service_name: str = Field(default="ml_platform_service", alias="SERVICE_NAME")

    # Postgres
    database_url: str = Field(..., alias="DATABASE_URL")
    db_pool_min_size: int = Field(default=3, alias="DB_POOL_MIN_SIZE")
    db_pool_max_size: int = Field(default=10, alias="DB_POOL_MAX_SIZE")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    redis_candle_pattern: str = Field(default="sg:market:candle:*", alias="REDIS_CANDLE_PATTERN")
    redis_ml_signals_prefix: str = Field(default="sg:ml:signals", alias="REDIS_ML_SIGNALS_CHANNEL_PREFIX")
    redis_ml_regime_prefix: str = Field(default="sg:ml:regime", alias="REDIS_ML_REGIME_CHANNEL_PREFIX")

    # Upstream
    market_data_service_url: str = Field(default="http://market_data_service:8002", alias="MARKET_DATA_SERVICE_URL")
    portfolio_management_service_url: str = Field(
        default="http://portfolio_management_service:8009", alias="PORTFOLIO_MANAGEMENT_SERVICE_URL"
    )
    market_data_timeout_seconds: float = Field(default=5.0, alias="MARKET_DATA_TIMEOUT_SECONDS")

    # Auth
    auth_jwt_public_key_path: str = Field(default="", alias="AUTH_JWT_PUBLIC_KEY_PATH")
    auth_jwt_algorithm: str = Field(default="RS256", alias="AUTH_JWT_ALGORITHM")
    auth_jwt_issuer: str = Field(default="auth_service", alias="AUTH_JWT_ISSUER")

    # Feature store
    feature_lookback_bars: int = Field(default=500, alias="FEATURE_LOOKBACK_BARS")
    feature_cache_ttl_seconds: int = Field(default=30, alias="FEATURE_CACHE_TTL_SECONDS")

    # Training
    train_min_samples: int = Field(default=1000, alias="TRAIN_MIN_SAMPLES")
    train_test_split: float = Field(default=0.2, alias="TRAIN_TEST_SPLIT")
    train_validation_split: float = Field(default=0.1, alias="TRAIN_VALIDATION_SPLIT")

    # Serving
    prediction_cache_ttl_seconds: int = Field(default=60, alias="PREDICTION_CACHE_TTL_SECONDS")
    serving_confidence_threshold: float = Field(default=0.55, alias="SERVING_CONFIDENCE_THRESHOLD")

    # Model registry
    model_artifacts_path: str = Field(default="/var/ml_platform/models", alias="MODEL_ARTIFACTS_PATH")
    model_champion_auto_promote: bool = Field(default=True, alias="MODEL_CHAMPION_AUTO_PROMOTE")

    # MLflow
    mlflow_tracking_uri: str = Field(default="sqlite:///var/ml_platform/mlflow.db", alias="MLFLOW_TRACKING_URI")
    mlflow_experiment_name: str = Field(default="sg_trading", alias="MLFLOW_EXPERIMENT_NAME")

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
