from __future__ import annotations

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    service_name: str = "risk_engine_service"
    service_port: int = 8007
    env: str = "production"

    postgres_dsn: str = "postgresql://sg_user:sg_pass@localhost:5432/sg_db"
    redis_url: str = "redis://localhost:6379/0"

    broker_service_url: str = "http://broker_service:8003"
    market_data_service_url: str = "http://market_data_service:8002"
    execution_orchestrator_url: str = "http://execution_orchestrator_service:8006"
    auth_service_url: str = "http://auth_service:8001"
    auth_jwt_public_key_path: str = "/run/secrets/jwt_public_key.pem"

    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_service_name: str = "risk_engine_service"

    margin_check_mode: str = "resilient"  # resilient | strict | disabled
    margin_cache_ttl_seconds: int = 30

    var_method: str = "parametric"  # parametric | historical
    var_confidence: float = 0.95
    var_horizon_days: int = 1

    kill_switch_auto_reset_requires_role: str = "risk_officer"

    redis_intents_pattern: str = "sg:intents:*"
    redis_risk_approved_prefix: str = "sg:risk_approved:"
    redis_risk_rejected_prefix: str = "sg:risk_rejected:"
    redis_risk_events_channel: str = "sg:risk:events"
    redis_regime_prefix: str = "sg:regime:"


@lru_cache
def get_settings() -> Settings:
    return Settings()
